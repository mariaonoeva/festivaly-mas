"""Limity a ad hoc požadavky chatbota ve vlastní databázi (chatbot.sqlite).

Chatbot do datasetu nezapisuje. Jediné, co smí vytvořit, je ad hoc požadavek z pevné
šablony (druh, země, město, žánr, období). Runner ho převede na úkol pro Průzkumníka.
IP adresy se neukládají, jen jejich solený hash (žádné osobní údaje).
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from .data import COUNTRIES, GENRE_CODES, ToolError, norm

SCHEMA = """
CREATE TABLE IF NOT EXISTS usage (
    bucket TEXT PRIMARY KEY,           -- např. 'llm:2026-11-17', 'c:<hash>:m:202611171403'
    count  INTEGER NOT NULL DEFAULT 0,
    day    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS adhoc_requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,         -- festival | gigs
    params      TEXT NOT NULL,         -- JSON ze šablony, nic jiného
    dedupe_key  TEXT NOT NULL,
    client      TEXT NOT NULL,         -- solený hash, ne IP
    status      TEXT NOT NULL DEFAULT 'new',   -- new | forwarded | unsupported
    created_at  TEXT NOT NULL,
    forwarded_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_adhoc ON adhoc_requests(status, dedupe_key);
"""
KINDS = ("festival", "gigs")
_lock = threading.Lock()


class LimitExceeded(Exception):
    def __init__(self, scope: str):
        super().__init__(scope)
        self.scope = scope


def now() -> datetime:
    return datetime.now(timezone.utc)


def connect(path: Path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def client_id(ip: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}|{ip}".encode()).hexdigest()[:16]


def _bump(conn, bucket: str, limit: int, day: str) -> None:
    """Atomicky zvýší čítač; když by překročil limit, nic nezapíše a vyhodí výjimku."""
    with _lock, conn:
        row = conn.execute("SELECT count FROM usage WHERE bucket = ?", (bucket,)).fetchone()
        if row and row["count"] >= limit:
            raise LimitExceeded(bucket.split(":")[0])
        conn.execute("INSERT INTO usage (bucket, count, day) VALUES (?, 1, ?) "
                     "ON CONFLICT(bucket) DO UPDATE SET count = count + 1", (bucket, day))


def check_client(conn, client: str, settings) -> None:
    t = now()
    day = t.strftime("%Y-%m-%d")
    _bump(conn, f"client:{client}:m:{t:%Y%m%d%H%M}", settings.per_client_per_minute, day)
    _bump(conn, f"client:{client}:d:{day}", settings.per_client_per_day, day)


def consume_llm_call(conn, settings) -> None:
    day = now().strftime("%Y-%m-%d")
    _bump(conn, f"llm:{day}", settings.llm_calls_per_day, day)


def purge_old(conn, keep_days: int = 3) -> None:
    cutoff = now().timestamp() - keep_days * 86400
    day = datetime.fromtimestamp(cutoff, timezone.utc).strftime("%Y-%m-%d")
    with _lock, conn:
        conn.execute("DELETE FROM usage WHERE day < ?", (day,))


def _month(value, name: str) -> str | None:
    if value in (None, ""):
        return None
    value = str(value).strip()
    if not re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])", value):
        raise ToolError(f"{name} must be YYYY-MM")
    return value


def template_params(args: dict) -> dict:
    """Pevná šablona: z argumentů modelu projde jen tohle, volný text nikdy."""
    kind = args.get("kind")
    if kind not in KINDS:
        raise ToolError(f"kind must be one of {KINDS}")
    country = args.get("country")
    if country not in COUNTRIES:
        raise ToolError(f"country must be one of {list(COUNTRIES)}")
    genre = args.get("genre")
    if genre not in GENRE_CODES:
        raise ToolError(f"genre must be one of {list(GENRE_CODES)}")
    city = args.get("city")
    if city not in (None, ""):
        city = str(city).strip()
        if len(city) > 50 or not re.fullmatch(r"[^\W\d_]+(?:[ \-][^\W\d_]+)*", city):
            raise ToolError("city must be a plain place name")
    else:
        city = None
    if kind == "gigs" and not city:
        raise ToolError("gigs search needs a city")
    period_from, period_to = _month(args.get("period_from"), "period_from"), _month(args.get("period_to"), "period_to")
    if period_from and period_to and period_to < period_from:
        raise ToolError("period_to is before period_from")
    return {"kind": kind, "country": country, "city": city, "genre": genre,
            "period_from": period_from, "period_to": period_to}


def create_request(conn, args: dict, client: str, settings) -> dict:
    params = template_params(args)
    key = "|".join(str(params[k] or "") for k in ("kind", "country", "genre", "period_from", "period_to"))
    key += "|" + norm(params["city"])
    day = now().strftime("%Y-%m-%d")
    open_req = conn.execute("SELECT id FROM adhoc_requests WHERE dedupe_key = ? AND status = 'new'",
                            (key,)).fetchone()
    if open_req:
        return {"queued": True, "already_pending": True, "request_id": open_req["id"]}
    try:
        _bump(conn, f"adhoc:{day}", settings.adhoc_per_day, day)
        _bump(conn, f"adhocclient:{client}:{day}", settings.adhoc_per_client_per_day, day)
    except LimitExceeded:
        return {"queued": False, "reason": "daily search limit reached, try again tomorrow"}
    with _lock, conn:
        cur = conn.execute("INSERT INTO adhoc_requests (kind, params, dedupe_key, client, created_at) "
                           "VALUES (?, ?, ?, ?, ?)",
                           (params["kind"], json.dumps(params, ensure_ascii=False), key, client,
                            now().strftime("%Y-%m-%dT%H:%M:%SZ")))
    result = {"queued": True, "request_id": cur.lastrowid, "params": params}
    if params["kind"] == "gigs":
        result["note"] = ("recorded only: automatic search for clubs and venues is not running yet, "
                          "so do not promise results")
    return result
