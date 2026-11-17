"""Read-only nástroje chatbota nad validovaným datasetem.

- DB se otevírá v režimu `mode=ro`: i kdyby model "chtěl" zapisovat, SQLite to odmítne.
- Ven jde jen record_state='validated' (fail closed: chyba čtení = žádná data).
- Argumenty od LLM se kontrolují proti číselníkům, filtruje se v Pythonu, žádné skládání SQL.
- Texty z datasetu pocházejí z cizích webů: jsou to data, ne pokyny.
"""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from adam_agents.freshness import is_fresh
from adam_agents.genres import GENRES

GENRE_CODES = tuple(GENRES)
COUNTRIES = {"CZ": "Czech Republic", "SK": "Slovakia"}
MAX_RESULTS = 15
JSON_COLS = ("genres", "lineup", "open_call", "sources", "validation_notes", "call_for_bands")
_ID_RE = re.compile(r"^[a-z0-9-]{3,120}$")


class ToolError(ValueError):
    """Neplatný argument od modelu. Model dostane krátkou chybu a může to zkusit znovu."""


def connect_ro(path: Path) -> sqlite3.Connection:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError("dataset database missing")
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def norm(text: str | None) -> str:
    text = unicodedata.normalize("NFKD", (text or "").casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _row(row: sqlite3.Row) -> dict:
    d = dict(row)
    for k in JSON_COLS:
        if isinstance(d.get(k), str):
            try:
                d[k] = json.loads(d[k])
            except json.JSONDecodeError:
                d[k] = None
    return d


def _validated(conn, table: str) -> list[dict]:
    rows = conn.execute(f"SELECT * FROM {table} WHERE record_state = 'validated'")  # table je konstanta
    return [_row(r) for r in rows]


# --- validace argumentů ---------------------------------------------------

def _date(value, name: str) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise ToolError(f"{name} must be YYYY-MM-DD")


def _list(value, allowed, name: str) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        raise ToolError(f"{name} must be a list")
    out = [str(v).strip() for v in value][:10]
    bad = [v for v in out if v not in allowed]
    if bad:
        raise ToolError(f"unknown {name}: {bad[:3]}; allowed: {list(allowed)}")
    return out


def _text(value, name: str, max_len: int = 60) -> str | None:
    if value in (None, ""):
        return None
    value = str(value).strip()
    if len(value) > max_len or not re.fullmatch(r"[\w .,'()\-]+", value):
        raise ToolError(f"{name} contains unsupported characters")
    return value


def _limit(value, default=8) -> int:
    try:
        return max(1, min(MAX_RESULTS, int(value or default)))
    except (TypeError, ValueError):
        return default


# --- výstupní tvary ---------------------------------------------------------

def _source_links(rec: dict, limit: int = 3) -> list[dict]:
    seen, out = set(), []
    for s in rec.get("sources") or []:
        url = s.get("url") if isinstance(s, dict) else None
        if isinstance(url, str) and url.startswith(("https://", "http://")) and url not in seen:
            seen.add(url)
            out.append({"url": url, "field": s.get("field"), "fetched_at": s.get("fetched_at")})
        if len(out) >= limit:
            break
    return out


def _summary(rec: dict, today: date) -> dict:
    end = rec.get("date_to") or rec.get("date_from")
    call = rec.get("open_call") or {}
    return {
        "id": rec["external_id"], "name": rec["name"], "type": rec.get("event_type") or "festival",
        "country": COUNTRIES.get(rec.get("country"), rec.get("country")), "city": rec.get("city"),
        "edition": rec.get("edition"), "date_from": rec.get("date_from"), "date_to": rec.get("date_to"),
        "edition_already_took_place": bool(end and end < today.isoformat()),
        "status": rec.get("status"), "genres": rec.get("genres") or [],
        "capacity_category": rec.get("capacity_cat"),
        "open_call": {"has": bool(call.get("has")), "url": call.get("url"), "deadline": call.get("deadline")},
        "website": rec.get("url"), "confidence": rec.get("confidence_label"),
        "sources": _source_links(rec, 2), "last_checked": rec.get("last_checked"),
    }


# --- nástroje ---------------------------------------------------------------

def search_festivals(conn, today: date, genres=None, countries=None, city=None, date_from=None,
                     date_to=None, open_call_only=False, include_past=False,
                     include_cancelled=False, limit=None) -> dict:
    genres = _list(genres, GENRE_CODES, "genres")
    countries = _list(countries, tuple(COUNTRIES), "countries")
    city = norm(_text(city, "city"))
    d_from, d_to = _date(date_from, "date_from"), _date(date_to, "date_to")
    if d_from and d_to and d_to < d_from:
        raise ToolError("date_to is before date_from")
    hits = []
    for rec in _validated(conn, "festivals"):
        if not is_fresh("festival", rec):
            continue
        start, end = rec.get("date_from"), rec.get("date_to") or rec.get("date_from")
        if genres and not set(genres) & set(rec.get("genres") or []):
            continue
        if countries and rec.get("country") not in countries:
            continue
        if city and city not in norm(rec.get("city")):
            continue
        if open_call_only and not (rec.get("open_call") or {}).get("has"):
            continue
        if rec.get("status") == "cancelled" and not include_cancelled:
            continue
        if not include_past and end and end < today.isoformat():
            continue
        if (d_from or d_to) and not start:
            continue  # bez termínu nevíme, jestli do období spadá
        if d_from and end < d_from.isoformat():
            continue
        if d_to and start > d_to.isoformat():
            continue
        overlap = len(set(genres) & set(rec.get("genres") or [])) if genres else 0
        hits.append((-overlap, start or "9999", rec))
    hits.sort(key=lambda h: (h[0], h[1]))
    n = _limit(limit, 10)
    out = {"total_matches": len(hits), "returned": min(n, len(hits)),
           "festivals": [_summary(h[2], today) for h in hits[:n]]}
    if len(hits) > n:
        out["more_available"] = (f"{len(hits) - n} more matches not shown; tell the user and offer them, "
                                 f"or call again with a higher limit or a narrower period")
    return out


def get_festival(conn, today: date, festival_id=None) -> dict:
    fid = str(festival_id or "").strip()
    if not _ID_RE.fullmatch(fid):
        raise ToolError("festival_id must be an id returned by search_festivals")
    row = conn.execute("SELECT * FROM festivals WHERE external_id = ? AND record_state = 'validated'",
                       (fid,)).fetchone()
    if not row:
        return {"found": False}
    rec = _row(row)
    out = _summary(rec, today)
    out["sources"] = _source_links(rec, 10)
    out["lineup"] = [{"year": e.get("year"), "artists": (e.get("artists") or [])[:80],
                      "labels": (e.get("labels") or [])[:40]}
                     for e in (rec.get("lineup") or []) if isinstance(e, dict)]
    out["recent_changes"] = _changes(conn, "festival", rec["id"], limit=10)
    return {"found": True, "festival": out}


def lineup_overlap(conn, today: date, festival_id=None, limit=None) -> dict:
    """KIQ 4: s kým kapela soupeří – festivaly se sdílenými interprety."""
    base = get_festival(conn, today, festival_id)
    if not base["found"]:
        return base
    mine = {norm(a): a for e in base["festival"]["lineup"] for a in e["artists"] if norm(a)}
    if not mine:
        return {"found": True, "lineup_known": False, "overlaps": []}
    overlaps = []
    for rec in _validated(conn, "festivals"):
        if rec["external_id"] == base["festival"]["id"]:
            continue
        theirs = {norm(a) for e in rec.get("lineup") or [] if isinstance(e, dict)
                  for a in e.get("artists") or []}
        shared = sorted(mine[k] for k in mine.keys() & theirs)
        if shared:
            overlaps.append({"id": rec["external_id"], "name": rec["name"], "date_from": rec.get("date_from"),
                             "shared_count": len(shared), "shared_artists": shared[:20]})
    overlaps.sort(key=lambda o: -o["shared_count"])
    return {"found": True, "lineup_known": True, "lineup_size": len(mine),
            "overlaps": overlaps[:_limit(limit, 5)]}


def _changes(conn, entity: str, entity_id: int | None, since: str | None = None, limit: int = 20) -> list[dict]:
    q = "SELECT * FROM change_log WHERE entity = ?"
    args: list = [entity]
    if entity_id is not None:
        q += " AND entity_id = ?"
        args.append(entity_id)
    if since:
        q += " AND detected_at >= ?"
        args.append(since)
    q += " ORDER BY detected_at DESC LIMIT ?"
    args.append(limit)
    return [{"type": r["change_type"], "field": r["field"], "old": r["old_value"], "new": r["new_value"],
             "source_url": r["source_url"], "detected_at": r["detected_at"]}
            for r in conn.execute(q, args)]


def recent_changes(conn, today: date, days=None, change_types=None) -> dict:
    """KIQ 5: nové, zrušené, posunuté festivaly a nové open cally."""
    allowed = ("new", "date_shift", "cancelled", "reinstated", "new_edition", "new_open_call",
               "open_call_changed", "lineup_changed", "genres_changed", "url_changed")
    types = _list(change_types, allowed, "change_types") or [t for t in allowed if t != "new"]
    try:
        days = max(1, min(90, int(days or 30)))
    except (TypeError, ValueError):
        days = 30
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    names = {r["id"]: (r["external_id"], r["name"]) for r in
             conn.execute("SELECT id, external_id, name FROM festivals WHERE record_state = 'validated'")}
    out = []
    for c in conn.execute("SELECT * FROM change_log WHERE entity = 'festival' AND detected_at >= ? "
                          "ORDER BY detected_at DESC LIMIT 200", (since,)):
        if c["change_type"] in types and c["entity_id"] in names:
            fid, name = names[c["entity_id"]]
            out.append({"festival_id": fid, "name": name, "type": c["change_type"], "field": c["field"],
                        "old": c["old_value"], "new": c["new_value"], "source_url": c["source_url"],
                        "detected_at": c["detected_at"]})
    return {"days": days, "changes": out[:30]}


def search_venues(conn, today: date, city=None, countries=None, genres=None, limit=None) -> dict:
    """Gigy (KIQ 6). Platí jen záznamy v TTL; prázdný výsledek = chybí platná cache."""
    city = norm(_text(city, "city"))
    countries = _list(countries, tuple(COUNTRIES), "countries")
    genres = _list(genres, GENRE_CODES, "genres")
    hits = []
    for rec in _validated(conn, "venues"):
        if not is_fresh("venue", rec):
            continue
        if city and city not in norm(rec.get("city")):
            continue
        if countries and rec.get("country") not in countries:
            continue
        if genres and not set(genres) & set(rec.get("genres") or []):
            continue
        call = rec.get("call_for_bands") or {}
        hits.append({"name": rec["name"], "type": rec.get("type"), "city": rec.get("city"),
                     "region": rec.get("region"), "capacity": rec.get("capacity"),
                     "genres": rec.get("genres") or [], "band_size": rec.get("band_size"),
                     "call_for_bands": {"has": bool(call.get("has")), "url": call.get("url"),
                                        "deadline": call.get("deadline")},
                     "booking_contact": rec.get("booking_contact"), "website": rec.get("url"),
                     "confidence": rec.get("confidence_label"), "sources": _source_links(rec, 2)})
    n = _limit(limit)
    return {"total_matches": len(hits), "cache_valid": bool(hits), "venues": hits[:n]}


def city_country(conn, city) -> str | None:
    """Země města podle validovaných záznamů (Brno → CZ). Jen když je jednoznačná."""
    key = norm(city)
    if not key:
        return None
    found = set()
    for table in ("festivals", "venues"):
        for row in conn.execute(f"SELECT city, country FROM {table} WHERE record_state = 'validated'"):
            if norm(row["city"]) == key and row["country"] in COUNTRIES:
                found.add(row["country"])
    return found.pop() if len(found) == 1 else None


TOOLS = {
    "search_festivals": search_festivals,
    "get_festival": get_festival,
    "lineup_overlap": lineup_overlap,
    "recent_changes": recent_changes,
    "search_venues": search_venues,
}
