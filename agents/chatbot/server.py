"""HTTP endpoint chatbota: POST /api/chat, GET /api/health. Jen standardní knihovna.

Spuštění (ze složky agents):  python -m chatbot.server --port 8787
Uživatel dostane jen obecnou chybu, detail jde do logu (bez klíčů a bez textu dotazu).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import agent, limits
from .config import Settings
from .gemini import LLMError

log = logging.getLogger("chatbot")
MAX_BODY = 16 * 1024


def load_dotenv(path) -> None:
    """Načte .env bez balíčku python-dotenv; existující proměnné prostředí nepřepisuje."""
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def make_handler(settings: Settings, state_conn, llm=None):
    llm = llm or agent.gemini.generate

    class Handler(BaseHTTPRequestHandler):
        server_version = "festivaly-chatbot"
        sys_version = ""

        def log_message(self, fmt, *args):  # bez IP a bez obsahu do logu
            log.info("%s %s", self.command, self.path.split("?")[0])

        def _cors(self):
            origin = self.headers.get("Origin")
            if origin and origin in settings.allowed_origins:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Max-Age", "600")

        def _send(self, status: int, payload: dict):
            body = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
            self.send_header("Referrer-Policy", "no-referrer")
            self._cors()
            self.end_headers()
            self.wfile.write(body)

        def _client_ip(self) -> str:
            # Za proxy je soketová adresa vždy proxy (127.0.0.1) → všichni by sdíleli jeden limit.
            if settings.client_ip_header:
                value = (self.headers.get(settings.client_ip_header) or "").strip()
                if value:
                    return value[:64]
            if settings.trust_proxy:
                # Poslední položku přidává naše proxy; první může podvrhnout klient.
                fwd = [p.strip() for p in self.headers.get("X-Forwarded-For", "").split(",") if p.strip()]
                if fwd:
                    return fwd[-1][:64]
            return self.client_address[0]

        def do_OPTIONS(self):
            if self.path != "/api/chat":
                return self._send(404, {"error": "not found"})
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self):
            if self.path == "/api/health":
                ok = bool(settings.gemini_api_key) and settings.dataset_db.is_file()
                return self._send(200 if ok else 503, {"ok": ok})
            self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/api/chat":
                return self._send(404, {"error": "not found"})
            origin = self.headers.get("Origin")
            if origin and origin not in settings.allowed_origins:
                return self._send(403, {"error": "origin not allowed"})
            if "application/json" not in (self.headers.get("Content-Type") or ""):
                return self._send(415, {"error": "use application/json"})
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if length <= 0 or length > MAX_BODY:
                return self._send(413, {"error": "request too large"})
            try:
                body = json.loads(self.rfile.read(length))
                message = body.get("message") if isinstance(body, dict) else None
            except (json.JSONDecodeError, UnicodeDecodeError):
                return self._send(400, {"error": "invalid json"})
            if not isinstance(message, str) or not message.strip():
                return self._send(400, {"error": "message is required"})
            if len(message) > settings.max_message_chars:
                return self._send(400, {"error": f"message is longer than {settings.max_message_chars} characters"})
            if not settings.gemini_api_key:
                return self._send(503, {"error": "chatbot is not available right now"})
            client = limits.client_id(self._client_ip(), settings.salt)
            try:
                limits.check_client(state_conn, client, settings)
                result = agent.answer(message.strip(), body.get("history"), client, settings, state_conn, llm=llm)
            except limits.LimitExceeded as e:
                log.warning("limit reached scope=%s", e.scope)
                return self._send(429, {"error": "too many requests, please try again later"})
            except LLMError as e:
                log.error("llm error: %s", e)
                return self._send(503, {"error": "chatbot is not available right now"})
            except (sqlite3.Error, FileNotFoundError) as e:
                log.error("dataset error: %s", type(e).__name__)
                return self._send(503, {"error": "chatbot is not available right now"})
            except Exception:
                log.exception("unexpected error")
                return self._send(500, {"error": "something went wrong"})
            self._send(200, result)

    return Handler


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--env", default=os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_dotenv(a.env)
    settings = Settings.from_env()
    if not settings.gemini_api_key:
        log.warning("GEMINI_API_KEY is not set: /api/chat will answer 503")
    if not settings.salt:
        log.warning("CHAT_CLIENT_SALT is not set: client hashes are guessable")
    state = limits.connect(settings.chatbot_db)
    limits.purge_old(state)
    httpd = ThreadingHTTPServer((a.host, a.port), make_handler(settings, state))
    log.info("chatbot on http://%s:%s model=%s", a.host, a.port, settings.gemini_model)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
