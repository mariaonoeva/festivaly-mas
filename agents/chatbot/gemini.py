"""Minimální klient Gemini API (REST, jen standardní knihovna, žádný balíček navíc).

Klíč jde v hlavičce x-goog-api-key, ne v URL, takže se neobjeví v chybových hláškách.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


TRANSIENT = {500, 502, 503, 504}   # přetížení / výpadek na straně Googlu → má smysl zkusit znovu


class LLMError(Exception):
    """Selhání LLM. Zpráva (HTTP kód + důvod od Googlu) jde jen do logu, nikdy klíč."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status

    @property
    def transient(self) -> bool:
        return self.status in TRANSIENT or self.status is None


def _reason(err: urllib.error.HTTPError) -> str:
    """Krátký důvod chyby od Googlu, jen pro log serveru (neobsahuje klíč, uživateli se neposílá)."""
    try:
        with err:
            detail = json.load(err).get("error", {})
        return f"{detail.get('status', '')} {str(detail.get('message', ''))[:300]}".strip()
    except Exception:
        return "no detail"


def generate(*, api_key: str, model: str, system: str, contents: list, tools: list,
             max_output_tokens: int = 1024, timeout: float = 30) -> dict:
    if not api_key:
        raise LLMError("missing api key", status=401)
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": contents,
        "tools": [{"functionDeclarations": tools}],
        "toolConfig": {"functionCallingConfig": {"mode": "AUTO"}},
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": max_output_tokens},
    }
    req = urllib.request.Request(
        API.format(model=model), data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        raise LLMError(f"gemini http {e.code} ({model}): {_reason(e)}", status=e.code) from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        raise LLMError(f"gemini unreachable: {type(e).__name__}") from None
