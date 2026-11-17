"""Import festivalů ve formátu Extraktoru/Průzkumníka:

{"generated": "YYYY-MM-DD", "count": N, "festivals": [
   {"id": "cz-...", "name", "type", "genres": [...], "country": "Czech Republic", "city",
    "edition_year", "date_from", "date_to", "status", "open_call": bool, "open_call_url",
    "website", "source_url"}, ...]}

Opakovaný import stejného `id` záznam aktualizuje a vrátí ho na validaci; Validátor a
Správce aktuálnosti pak sami zapíšou změny (posun termínu, zrušení, nový open call...).
"""
from __future__ import annotations

from . import db

# pole, která se při opakovaném importu přepisují
MAPPED = ("name", "event_type", "genres", "country", "city", "edition", "date_from", "date_to",
          "status", "open_call", "url", "sources")


def map_festival(item: dict, fetched_at: str) -> dict:
    src = item.get("source_url") or item.get("website")
    rec = {
        "external_id": item.get("id"),
        "name": item.get("name"),
        "event_type": item.get("type"),
        "genres": item.get("genres") or [],
        "country": item.get("country"),
        "city": item.get("city"),
        "edition": item.get("edition_year"),
        "date_from": item.get("date_from"),
        "date_to": item.get("date_to"),
        "status": item.get("status"),
        "open_call": {"has": bool(item.get("open_call")), "url": item.get("open_call_url")}
        if item.get("open_call") or item.get("open_call_url") else {"has": False},
        "url": item.get("website"),
        "sources": [],
    }
    if src:
        for field in ("date_from", "date_to", "status", "edition"):
            if rec[field] not in (None, ""):
                rec["sources"].append({"field": field, "value": str(rec[field]), "url": src,
                                       "fetched_at": fetched_at})
        if not rec["sources"]:
            rec["sources"].append({"field": "name", "value": rec["name"], "url": src,
                                   "fetched_at": fetched_at})
    if rec["open_call"].get("url"):
        rec["sources"].append({"field": "open_call", "value": "true",
                               "url": rec["open_call"]["url"], "fetched_at": fetched_at})
    for k in ("lat", "lon"):  # GPS doplní geokódování, pokud ho formát přinese
        if item.get(k) is not None:
            rec[k] = item[k]
    return rec


def import_festivals(conn, data: dict) -> dict:
    items = data.get("festivals")
    if not isinstance(items, list):
        raise ValueError("chybí pole 'festivals'")
    gen = str(data.get("generated") or db.iso(db.utcnow()))
    fetched_at = gen if "T" in gen else f"{gen[:10]}T00:00:00Z"
    stats = {"inserted": 0, "updated": 0, "skipped": 0}
    for item in items:
        if not isinstance(item, dict) or not item.get("id") or not item.get("name"):
            stats["skipped"] += 1
            continue
        rec = map_festival(item, fetched_at)
        row = conn.execute("SELECT id FROM festivals WHERE external_id = ?",
                           (rec["external_id"],)).fetchone()
        if row:
            upd = {k: rec[k] for k in MAPPED}
            upd.update(record_state="pending_validation", rework_count=0)
            db.update_record(conn, "festival", row["id"], upd)
            stats["updated"] += 1
        else:
            db.insert_record(conn, "festival", rec)
            stats["inserted"] += 1
    if data.get("count") is not None and data["count"] != len(items):
        stats["count_mismatch"] = f"count={data['count']}, festivals={len(items)}"
    conn.commit()
    return stats
