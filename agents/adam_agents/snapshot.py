"""Snímek datasetu pro obhajobu (záloha při výpadku API) a report změn pro KIQ 5."""
from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from . import db
from .freshness import is_fresh

PUBLIC_FESTIVAL = ["id", "external_id", "event_type", "name", "url", "country", "city", "lat", "lon", "date_from", "date_to",
                   "edition", "genres", "capacity_cat", "lineup", "open_call", "status", "sources",
                   "last_checked", "confidence", "confidence_label"]
PUBLIC_VENUE = ["id", "name", "type", "url", "country", "region", "city", "lat", "lon", "capacity",
                "genres", "band_size", "call_for_bands", "booking_contact", "sources",
                "last_checked", "ttl_days", "confidence", "confidence_label"]

CHANGE_LABELS_CS = {
    "new": "nový záznam", "date_shift": "posun termínu", "cancelled": "zrušeno",
    "reinstated": "obnoveno", "new_edition": "nový ročník", "new_open_call": "nový open call",
    "open_call_changed": "změna open callu", "lineup_changed": "změna line-upu",
    "genres_changed": "změna žánrů (dramaturgie)", "dramaturgy_changed": "změna dramaturgie",
    "url_changed": "změna webu", "capacity_changed": "změna kapacity", "field_changed": "jiná změna",
    "stale": "zastaralé, neověřeno", "unreachable": "web nedostupný (možný zánik)",
    "merged_duplicate": "sloučena duplicita", "rejected": "zamítnuto validací",
}


def _public(rec: dict, fields: list[str], entity: str, now) -> dict:
    out = {k: rec.get(k) for k in fields}
    notes = rec.get("validation_notes") if isinstance(rec.get("validation_notes"), dict) else {}
    out["fresh"] = is_fresh(entity, rec, now)
    out["warnings"] = notes.get("warnings", [])
    return out


def export_snapshot(conn, out_dir: str | Path, now: datetime | None = None) -> Path:
    now = now or db.utcnow()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y%m%d-%H%M")

    fest = [_public(db.row_to_dict(r), PUBLIC_FESTIVAL, "festival", now) for r in conn.execute(
        "SELECT * FROM festivals WHERE record_state='validated' ORDER BY country, date_from")]
    ven = [_public(db.row_to_dict(r), PUBLIC_VENUE, "venue", now) for r in conn.execute(
        "SELECT * FROM venues WHERE record_state='validated' ORDER BY country, city, name")]
    changes = [dict(r) for r in conn.execute("SELECT * FROM change_log ORDER BY detected_at, id")]
    states = {t: dict(Counter(r[0] for r in conn.execute(f"SELECT record_state FROM {t}")))
              for t in db.TABLE_FOR.values()}

    data = {
        "generated_at": db.iso(now),
        "stats": {
            "festivals_validated": len(fest), "venues_validated": len(ven),
            "record_states": states,
            "confidence": dict(Counter(f["confidence_label"] for f in fest + ven)),
            "festivals_by_country": dict(Counter(f["country"] for f in fest)),
            "venues_by_city": dict(Counter(f"{v['country']}/{v['city']}" for v in ven)),
        },
        "festivals": fest,
        "venues": ven,
        "change_log": changes,
    }
    path = out / f"snapshot-{stamp}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "snapshot-latest.json").write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                              encoding="utf-8")

    for name, rows, fields in (("festivals", fest, PUBLIC_FESTIVAL), ("venues", ven, PUBLIC_VENUE)):
        with open(out / f"{name}-{stamp}.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(fields + ["fresh"])
            for r in rows:
                w.writerow([json.dumps(r[f], ensure_ascii=False) if isinstance(r[f], (list, dict))
                            else r[f] for f in fields] + [r["fresh"]])
    (out / f"changes-{stamp}.md").write_text(change_report(conn, days=3650, now=now), encoding="utf-8")
    return path


def load_snapshot(conn, path: str | Path) -> dict:
    """Obnoví validované záznamy ze snímku do prázdné DB (demo bez API)."""
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    n = {"festivals": 0, "venues": 0}
    for entity, key in (("festival", "festivals"), ("venue", "venues")):
        for rec in data.get(key, []):
            rec = {k: v for k, v in rec.items() if k not in ("fresh", "warnings")}
            rec["record_state"] = "validated"
            db.insert_record(conn, entity, rec)
            n[key] += 1
    conn.commit()
    return n


def change_report(conn, days: int = 30, now: datetime | None = None) -> str:
    """Markdown přehled změn = odpověď na KIQ 5."""
    now = now or db.utcnow()
    since = db.iso(now - timedelta(days=days))
    rows = conn.execute(
        "SELECT c.*, COALESCE(f.name, v.name) AS name, COALESCE(f.country, v.country) AS country "
        "FROM change_log c "
        "LEFT JOIN festivals f ON c.entity='festival' AND f.id=c.entity_id "
        "LEFT JOIN venues v ON c.entity='venue' AND v.id=c.entity_id "
        "WHERE c.detected_at >= ? ORDER BY c.change_type, c.detected_at", (since,)).fetchall()
    lines = [f"# Změny v datasetu (KIQ 5)", "",
             f"Období: posledních {days} dní, vygenerováno {db.iso(now)}.", ""]
    counts = Counter(r["change_type"] for r in rows)
    lines += ["| Typ změny | Počet |", "|---|---|"]
    lines += [f"| {CHANGE_LABELS_CS.get(t, t)} | {n} |" for t, n in counts.most_common()]
    lines.append("")
    for t in counts:
        if t == "new":
            continue
        lines += [f"## {CHANGE_LABELS_CS.get(t, t)}", ""]
        for r in rows:
            if r["change_type"] != t:
                continue
            detail = ""
            if r["old_value"] or r["new_value"]:
                detail = f": {r['old_value'] or '–'} → {r['new_value'] or '–'}"
            src = f" ([zdroj]({r['source_url']}))" if r["source_url"] else ""
            lines.append(f"- **{r['name']}** ({r['entity']}, {r['country']}), "
                         f"{r['detected_at'][:10]}{detail}{src}")
        lines.append("")
    return "\n".join(lines)
