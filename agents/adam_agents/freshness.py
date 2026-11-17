"""Agent 4 – Správce aktuálnosti.

* plánuje opakované kontroly podle blížícího se termínu, uzávěrky open callu a stáří záznamu
  (venues/gigy mají kratší platnost než festivaly),
* detekuje změny (nový ročník, posun termínu, zrušení, nový open call, změna dramaturgie) -> change_log,
* hlídá zastaralé a nedostupné záznamy,
* zadává práci Průzkumníkovi (další ročník, mezery v pokrytí zemí).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from . import db

# ----------------------------------------------------------------- konfigurace
FESTIVAL_DEFAULT_DAYS = 30
VENUE_DEFAULT_TTL_DAYS = 7
CANCELLED_DAYS = 90
TARGET_COUNTRIES = ["CZ", "SK", "PL", "AT", "DE"]
MIN_FESTIVALS_PER_COUNTRY = 15
MAX_GAP_TASKS_PER_RUN = 10
MAX_NEXT_EDITION_TASKS_PER_RUN = 20
MAX_RECHECK_TASKS_PER_RUN = 50   # ochrana rozpočtu Firecrawl/Exa
FAILED_RECHECKS_UNREACHABLE = 2

FESTIVAL_TRACKED = ("name", "url", "date_from", "date_to", "edition", "status", "open_call",
                    "genres", "lineup", "capacity_cat")
VENUE_TRACKED = ("name", "url", "type", "capacity", "genres", "band_size", "call_for_bands",
                 "booking_contact")


def _d(value) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


# ----------------------------------------------------------------- plánování kontrol
def check_interval_days(entity: str, rec: dict, today: date) -> float:
    if entity == "venue":
        days = float(rec.get("ttl_days") or VENUE_DEFAULT_TTL_DAYS)
        call = rec.get("call_for_bands") or {}
        dl = _d(call.get("deadline")) if isinstance(call, dict) else None
        if dl and 0 <= (dl - today).days <= 14:
            days = min(days, 2)
    else:
        if rec.get("status") == "cancelled":
            return CANCELLED_DAYS
        start, end = _d(rec.get("date_from")), _d(rec.get("date_to") or rec.get("date_from"))
        if not start:
            days = 14                     # ohlášeno bez termínu: termín brzy vyjde
        elif end and end < today:
            days = 30                     # proběhlo: čekáme na ohlášení dalšího ročníku
        else:
            to_start = (start - today).days
            days = 2 if to_start <= 14 else 7 if to_start <= 60 else 14 if to_start <= 180 else FESTIVAL_DEFAULT_DAYS
        call = rec.get("open_call") or {}
        dl = _d(call.get("deadline")) if isinstance(call, dict) else None
        if dl and 0 <= (dl - today).days <= 30:
            days = min(days, 3)
    if (rec.get("confidence") or 1) < 0.5:
        days = max(1, days / 2)           # nejisté záznamy kontrolujeme častěji
    return days


def compute_next_check(entity: str, rec: dict, now: datetime) -> datetime:
    return now + timedelta(days=check_interval_days(entity, rec, now.date()))


def recheck_priority(entity: str, rec: dict, today: date) -> int:
    prio = 50
    if entity == "venue":
        prio = 30
    else:
        start = _d(rec.get("date_from"))
        if start and 0 <= (start - today).days <= 14:
            prio = 10
    call = rec.get("open_call") if entity == "festival" else rec.get("call_for_bands")
    dl = _d(call.get("deadline")) if isinstance(call, dict) else None
    if dl and 0 <= (dl - today).days <= 14:
        prio = min(prio, 15)
    if (rec.get("confidence") or 1) < 0.5:
        prio = max(0, prio - 10)
    return prio


# ----------------------------------------------------------------- detekce změn (KIQ 5)
def tracked_snapshot(entity: str, rec: dict) -> dict:
    fields = FESTIVAL_TRACKED if entity == "festival" else VENUE_TRACKED
    snap = {}
    for f in fields:
        v = rec.get(f)
        if isinstance(v, str) and f in db.JSON_COLUMNS:
            try:
                v = json.loads(v)
            except json.JSONDecodeError:
                pass
        if isinstance(v, list) and all(isinstance(x, str) for x in v):
            v = sorted(v)
        snap[f] = v
    return snap


def _call_has(call) -> bool:
    return bool(isinstance(call, dict) and call.get("has"))


def detect_changes(entity: str, old: dict | None, new: dict) -> list[dict]:
    """Porovná poslední schválený snímek s novým. Vrací záznamy pro change_log."""
    if not old:
        return [{"change_type": "new"}]
    out: list[dict] = []

    def add(t, f, o, n):
        out.append({"change_type": t, "field": f, "old": o, "new": n})

    if entity == "festival":
        o_status, n_status = old.get("status"), new.get("status")
        if n_status == "cancelled" and o_status != "cancelled":
            add("cancelled", "status", o_status, n_status)
        elif o_status == "cancelled" and n_status != "cancelled":
            add("reinstated", "status", o_status, n_status)

        o_start, n_start = _d(old.get("date_from")), _d(new.get("date_from"))
        def _int(v):
            try:
                return int(v)
            except (TypeError, ValueError):
                return None
        o_ed, n_ed = _int(old.get("edition")), _int(new.get("edition"))
        new_edition = bool((o_ed and n_ed and n_ed > o_ed)
                           or (o_start and n_start and n_start.year > o_start.year))
        if new_edition:
            add("new_edition", "date_from", old.get("date_from"), new.get("date_from"))
        elif (old.get("date_from"), old.get("date_to")) != (new.get("date_from"), new.get("date_to")):
            add("date_shift", "dates", f"{old.get('date_from')}..{old.get('date_to')}",
                f"{new.get('date_from')}..{new.get('date_to')}")
        call_field = "open_call"
        dramaturgy = ("genres", "lineup")
        other = ("url", "capacity_cat", "name")
    else:
        call_field = "call_for_bands"
        dramaturgy = ("genres", "band_size")
        other = ("url", "capacity", "type", "name", "booking_contact")

    o_call, n_call = old.get(call_field), new.get(call_field)
    if _call_has(n_call) and not _call_has(o_call):
        add("new_open_call", call_field, o_call, n_call)
    elif (o_call or {}) != (n_call or {}):
        add("open_call_changed", call_field, o_call, n_call)

    for f in dramaturgy:
        if (old.get(f) or []) != (new.get(f) or []) and (old.get(f) or new.get(f)):
            add("lineup_changed" if f == "lineup" else "genres_changed" if f == "genres"
                else "dramaturgy_changed", f, old.get(f), new.get(f))
    for f in other:
        if old.get(f) != new.get(f):
            add({"url": "url_changed", "capacity_cat": "capacity_changed",
                 "capacity": "capacity_changed"}.get(f, "field_changed"), f, old.get(f), new.get(f))
    return out


# ----------------------------------------------------------------- běh agenta
def _notes(rec: dict) -> dict:
    n = rec.get("validation_notes")
    return n if isinstance(n, dict) else {}


def _schedule_rechecks(conn, now: datetime, summary: dict) -> None:
    today = now.date()
    budget = MAX_RECHECK_TASKS_PER_RUN
    due = []
    for entity, table in db.TABLE_FOR.items():
        for row in conn.execute(
            f"SELECT * FROM {table} WHERE record_state='validated' AND "
            "(next_check_at IS NULL OR next_check_at <= ?)", (db.iso(now),)
        ):
            rec = db.row_to_dict(row)
            due.append((recheck_priority(entity, rec, today), entity, rec))
    due.sort(key=lambda x: x[0])
    for prio, entity, rec in due:
        if budget <= 0:
            summary["recheck_deferred"] = summary.get("recheck_deferred", 0) + 1
            continue
        if rec.get("url"):
            tid = db.enqueue_task(
                conn, type="extract", priority=prio, created_by="freshness", assigned_to="extractor",
                payload={"entity": entity, "id": rec["id"], "url": rec["url"],
                         "reason": "scheduled_recheck"},
                dedupe_key=f"recheck:{entity}:{rec['id']}")
        else:
            tid = db.enqueue_task(
                conn, type="search", priority=prio, created_by="freshness", assigned_to="explorer",
                payload={"kind": "find_official_url", "entity": entity, "id": rec["id"],
                         "name": rec["name"], "country": rec.get("country"), "city": rec.get("city")},
                dedupe_key=f"recheck:{entity}:{rec['id']}")
        if tid:
            budget -= 1
            summary["recheck_tasks"] = summary.get("recheck_tasks", 0) + 1
        nxt = compute_next_check(entity, rec, now)
        db.update_record(conn, entity, rec["id"], {"next_check_at": db.iso(nxt)})


def _mark_stale(conn, now: datetime, summary: dict) -> None:
    """Záznam, který se dlouho nepodařilo ověřit, ztrácí jistotu a je označen jako zastaralý."""
    today = now.date()
    for entity, table in db.TABLE_FOR.items():
        for row in conn.execute(f"SELECT * FROM {table} WHERE record_state='validated'"):
            rec = db.row_to_dict(row)
            last = db.parse_dt(rec.get("last_checked"))
            limit = 2 * check_interval_days(entity, {**rec, "confidence": 1}, today)
            notes = _notes(rec)
            is_stale = last is None or (now - last).days > limit
            if is_stale and not notes.get("stale"):
                notes["stale"] = True
                conf = max(0.05, round((rec.get("confidence") or 0.5) - 0.2, 2))
                label = "high" if conf >= 0.75 else "medium" if conf >= 0.5 else "low"
                db.update_record(conn, entity, rec["id"], {
                    "validation_notes": notes, "confidence": conf, "confidence_label": label})
                db.log_change(conn, entity=entity, entity_id=rec["id"], change_type="stale",
                              old=rec.get("last_checked"), source_url=rec.get("url"), at=now)
                summary["stale"] = summary.get("stale", 0) + 1
            elif not is_stale and notes.get("stale"):
                notes.pop("stale")
                db.update_record(conn, entity, rec["id"], {"validation_notes": notes})


def _handle_failed_rechecks(conn, now: datetime, summary: dict) -> None:
    """Neúspěšné rechecky (web nedostupný) -> po N pokusech hlásíme možný zánik."""
    rows = conn.execute(
        "SELECT * FROM tasks WHERE status='failed' AND created_by='freshness' "
        "AND (result IS NULL OR result NOT LIKE '%handled_by_freshness%')").fetchall()
    for t in rows:
        payload = json.loads(t["payload"] or "{}")
        entity, rid = payload.get("entity"), payload.get("id")
        if entity in db.TABLE_FOR and rid:
            row = conn.execute(f"SELECT * FROM {db.TABLE_FOR[entity]} WHERE id=?", (rid,)).fetchone()
            if row:
                rec = db.row_to_dict(row)
                notes = _notes(rec)
                notes["failed_rechecks"] = notes.get("failed_rechecks", 0) + 1
                db.update_record(conn, entity, rid, {"validation_notes": notes})
                if notes["failed_rechecks"] == FAILED_RECHECKS_UNREACHABLE:
                    db.log_change(conn, entity=entity, entity_id=rid, change_type="unreachable",
                                  new=f"{notes['failed_rechecks']} failed rechecks",
                                  source_url=rec.get("url"), at=now)
                    db.enqueue_task(
                        conn, type="search", priority=25, created_by="freshness", assigned_to="explorer",
                        payload={"kind": "verify_existence", "entity": entity, "id": rid,
                                 "name": rec["name"], "country": rec.get("country")},
                        dedupe_key=f"verify:{entity}:{rid}")
                    summary["unreachable"] = summary.get("unreachable", 0) + 1
        result = {"handled_by_freshness": True, "prev": t["result"]}
        conn.execute("UPDATE tasks SET result=? WHERE id=?", (json.dumps(result), t["id"]))


def _plan_next_editions(conn, now: datetime, summary: dict) -> None:
    today = now.date()
    made = 0
    for row in conn.execute("SELECT * FROM festivals WHERE record_state='validated' "
                            "AND status != 'cancelled' AND date_to < ?", (today.isoformat(),)):
        rec = db.row_to_dict(row)
        last = _d(rec.get("date_from")) or _d(rec.get("date_to"))
        tid = db.enqueue_task(
            conn, type="search", priority=40, created_by="freshness", assigned_to="explorer",
            payload={"kind": "next_edition", "entity": "festival", "id": rec["id"],
                     "name": rec["name"], "country": rec.get("country"), "url": rec.get("url"),
                     "last_date": rec.get("date_from")},
            dedupe_key=f"next_edition:{rec['id']}:{last.year + 1}")
        if tid:
            summary["next_edition_tasks"] = summary.get("next_edition_tasks", 0) + 1
            made += 1
            if made >= MAX_NEXT_EDITION_TASKS_PER_RUN:
                break


def _plan_coverage_gaps(conn, now: datetime, summary: dict, countries, min_per_country) -> None:
    season = now.year + 1 if now.month >= 9 else now.year
    made = 0
    for c in countries:
        if made >= MAX_GAP_TASKS_PER_RUN:
            break
        n = conn.execute("SELECT COUNT(*) FROM festivals WHERE record_state='validated' AND "
                         "country=? AND status!='cancelled'", (c,)).fetchone()[0]
        if n < min_per_country:
            tid = db.enqueue_task(
                conn, type="search", priority=60, created_by="freshness", assigned_to="explorer",
                payload={"kind": "coverage_gap", "entity": "festival", "country": c,
                         "season": season, "have": n, "want": min_per_country},
                dedupe_key=f"gap:festival:{c}:{season}")
            if tid:
                made += 1
                summary["gap_tasks"] = summary.get("gap_tasks", 0) + 1


def run_freshness(conn, now: datetime | None = None, countries=None,
                  min_per_country: int = MIN_FESTIVALS_PER_COUNTRY) -> dict:
    now = now or db.utcnow()
    summary: dict[str, int] = {}
    _handle_failed_rechecks(conn, now, summary)
    _mark_stale(conn, now, summary)
    _schedule_rechecks(conn, now, summary)
    _plan_next_editions(conn, now, summary)
    _plan_coverage_gaps(conn, now, summary, countries or TARGET_COUNTRIES, min_per_country)
    conn.commit()
    return summary


def is_fresh(entity: str, rec: dict, now: datetime | None = None) -> bool:
    """Pro Chatbota a mapu: platný = validovaný a ne zastaralý (u gigů dle TTL)."""
    now = now or db.utcnow()
    if rec.get("record_state") != "validated" or _notes(rec).get("stale"):
        return False
    if entity == "venue":
        last = db.parse_dt(rec.get("last_checked"))
        ttl = rec.get("ttl_days") or VENUE_DEFAULT_TTL_DAYS
        return bool(last and (now - last).days <= ttl)
    return True
