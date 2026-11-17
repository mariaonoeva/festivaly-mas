"""Run the festival agents and publish the validated frontend snapshot."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from contextlib import closing
import unicodedata
from datetime import date
from pathlib import Path

from adam_agents import db
from adam_agents.freshness import run_freshness
from adam_agents.genres import GENRES
from adam_agents.importer import map_festival
from adam_agents.snapshot import export_snapshot
from adam_agents.validator import run_validator
import extraktor
import scout

ROOT = Path(__file__).resolve().parents[1]
COUNTRIES = {"CZ": "Czech Republic", "SK": "Slovakia"}
CAPACITY = {"do 5 000": "<5k", "5 000–25 000": "5k-25k", "25 000–50 000": "25k-50k", "nad 50 000": ">50k"}
COUNTRY_CODES = {**{name: code for code, name in COUNTRIES.items()}, "Czechia": "CZ"}


def country_code(country):
    return COUNTRY_CODES.get(country, country)


def read_dataset(path):
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    rows = data["festivals"]
    if not isinstance(rows, list) or data.get("count", len(rows)) != len(rows):
        raise ValueError(f"Invalid festival count in {path}")
    ids = [row["id"] for row in rows]
    if any(not isinstance(key, str) or not key for key in ids) or len(set(ids)) != len(ids):
        raise ValueError(f"Festival IDs must be unique strings in {path}")
    return data


def normalized(value):
    return "".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c))


def identity(row):
    city = normalized(row.get("city") or "")
    if city == "praha":
        city = "prague"
    return country_code(row.get("country")), city, normalized(row.get("name") or "")


def website_identity(row):
    url = extraktor.cista_url(row.get("website"))
    return (*identity(row)[:2], extraktor.klic_url(url)) if url else None


def compatible_record(candidate, previous):
    row = {**candidate, "country": country_code(candidate["country"])}
    for key in ("name", "city"):
        if not isinstance(row.get(key), str) or not row[key].strip():
            raise ValueError(f"Missing {key}")
    fetched_at = candidate.get("checked_at") or db.iso(db.utcnow())
    carried = set()
    if previous:
        row["id"] = previous["id"]
        row["type"] = previous["type"]
        row["city"] = previous["city"]
        if row.get("observed_edition") is False:
            for field in ("edition_year", "date_from", "date_to"):
                row[field] = previous.get(field)
                carried.add("edition" if field == "edition_year" else field)
        if row.get("observed_status") is False:
            row["status"] = previous["status"]
            carried.add("status")
        if row.get("observed_open_call") is False and row["edition_year"] == previous["edition_year"]:
            row["open_call"] = previous["open_call"]
            row["open_call_url"] = previous["open_call_url"]
            carried.add("open_call")
        if not row.get("genres"):
            row["genres"] = previous["genres"]
        for field in ("lat", "lon"):
            if row.get(field) is None:
                row[field] = previous.get(field)
    record = map_festival(row, fetched_at)
    if carried:
        for source in record["sources"]:
            if source["field"] in carried:
                source["url"] = previous.get("source_url") or previous.get("website") or source["url"]
                source["fetched_at"] = None
    record["open_call"]["deadline"] = row.get("open_call_deadline") or (
        previous.get("open_call_deadline") if previous and "open_call" in carried else None
    )
    capacity = CAPACITY.get(row.get("capacity_label"))
    if capacity:
        record["capacity_cat"] = capacity
    field_names = {"gps": "coordinates", "event_status": "status"}
    for field, entries in (candidate.get("source_entries") or {}).items():
        value = row.get(field_names.get(field, field))
        if value is None or field_names.get(field, field) in carried:
            continue
        for entry in entries:
            record["sources"].append({
                "field": field_names.get(field, field), "value": value,
                "url": entry.get("url"), "fetched_at": entry.get("fetched_at") or fetched_at,
            })
    lineup = row.get("lineup_by_edition")
    if lineup:
        record["lineup"] = lineup
    elif row.get("lineup"):
        record["lineup"] = [{"year": row["edition_year"], "artists": row["lineup"]}]
    return record


def import_candidates(conn, candidates, baseline):
    by_id = {row["id"]: row for row in baseline}
    by_name = {identity(row): row for row in baseline}
    by_url = {website_identity(row): row for row in baseline if website_identity(row)}
    conn.execute("CREATE TABLE IF NOT EXISTS imports (external_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL)")
    imported = skipped = 0
    for candidate in candidates:
        if country_code(candidate.get("country")) not in COUNTRIES:
            skipped += 1
            continue
        previous = by_id.get(candidate["id"]) or by_name.get(identity(candidate)) or by_url.get(website_identity(candidate))
        try:
            record = compatible_record(candidate, previous)
        except ValueError:
            skipped += 1
            continue
        external_id = record["external_id"]
        fingerprint = hashlib.sha256(json.dumps(candidate, sort_keys=True).encode()).hexdigest()
        seen = conn.execute("SELECT fingerprint FROM imports WHERE external_id=?", (external_id,)).fetchone()
        if seen and seen[0] == fingerprint:
            continue
        existing = conn.execute("SELECT id, record_state FROM festivals WHERE external_id=?", (external_id,)).fetchone()
        if existing:
            if existing["record_state"] != "needs_rework":
                record["rework_count"] = 0
            record["record_state"] = "pending_validation"
            db.update_record(conn, "festival", existing["id"], record)
        else:
            db.insert_record(conn, "festival", record)
        conn.execute("INSERT OR REPLACE INTO imports VALUES (?, ?)", (external_id, fingerprint))
        imported += 1
    conn.commit()
    return {"imported": imported, "skipped": skipped}


def public_record(row):
    call = row["open_call"] or {}
    links = [s.get("url") for s in row["sources"] or [] if isinstance(s, dict)]
    source = next((link for link in links if extraktor.cista_url(link)), row["url"])
    return {
        "id": row["external_id"], "name": row["name"],
        "type": row["event_type"] or "festival", "genres": row["genres"] or [],
        "country": COUNTRIES[row["country"]], "city": row["city"],
        "edition_year": row["edition"] or (int(row["date_from"][:4]) if row["date_from"] else date.today().year),
        "date_from": row["date_from"], "date_to": row["date_to"], "status": row["status"] or "announced",
        "open_call": bool(call.get("has")), "open_call_url": call.get("url"),
        "open_call_deadline": call.get("deadline"), "website": row["url"], "source_url": source,
        "lat": row["lat"], "lon": row["lon"], "lineup": row["lineup"] or [],
        "confidence_label": row["confidence_label"], "capacity_cat": row["capacity_cat"],
        "last_checked": row["last_checked"], "fresh": row["fresh"],
    }


def publish(path, baseline, validated):
    rows = {row["id"]: row for row in baseline["festivals"]}
    for row in validated:
        if not row["external_id"] or not row["city"] or row["country"] not in COUNTRIES:
            continue
        public = public_record(row)
        rows[public["id"]] = public
    if list(rows.values()) == baseline["festivals"]:
        return False
    document = {"generated": date.today().isoformat(), "count": len(rows), "festivals": list(rows.values())}
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as out:
        temporary = Path(out.name)
        try:
            json.dump(document, out, ensure_ascii=False, indent=2)
            out.write("\n")
        except BaseException:
            temporary.unlink()
            raise
    try:
        temporary.chmod(path.stat().st_mode & 0o777)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def queue_refresh(validator, collector, limit):
    """Move scheduled re-extractions and their outcomes across the two queues."""
    collector.execute("""CREATE TABLE IF NOT EXISTS refresh_jobs (
        validator_task INTEGER PRIMARY KEY, collector_task INTEGER NOT NULL)""")
    rows = validator.execute("""SELECT * FROM tasks WHERE status='queued'
        AND type='extract' AND assigned_to='extractor' ORDER BY priority, id LIMIT ?""", (limit,))
    for task in rows.fetchall():
        payload = json.loads(task["payload"])
        if payload.get("entity") != "festival" or not extraktor.cista_url(payload.get("url")):
            continue
        if collector.execute("SELECT 1 FROM refresh_jobs WHERE validator_task=?", (task["id"],)).fetchone():
            continue
        record = validator.execute("SELECT name, country, city FROM festivals WHERE id=?", (payload.get("id"),)).fetchone()
        params = {"url": payload["url"], "kind": "festival", "hint": dict(record) if record else {}}
        with collector:
            job = collector.execute("""INSERT INTO tasks(type, params, created_by, priority, created_at)
                VALUES ('extract', ?, ?, ?, ?)""",
                (json.dumps(params), task["created_by"], 101 - task["priority"], extraktor.ted()))
            collector.execute("INSERT INTO refresh_jobs VALUES (?, ?)", (task["id"], job.lastrowid))


CHATBOT_PRIORITY = 5   # Adamova fronta: 0 = nejvyšší; ad hoc od kapel má přednost před plánem


def forward_chatbot_requests(validator, chatbot_path, limit):
    """Převede ad hoc požadavky chatbota (pevná šablona) na úkoly pro Průzkumníka.

    Chatbot nemá zápis do datasetu ani do fronty agentů; tuhle hranici překračuje jen runner.
    """
    if not chatbot_path.is_file():
        return {"forwarded": 0}
    from chatbot.limits import template_params  # stejná validace jako při vzniku požadavku
    forwarded = unsupported = 0
    with closing(db.connect(chatbot_path)) as chat:
        rows = chat.execute("SELECT * FROM adhoc_requests WHERE status='new' ORDER BY id LIMIT ?", (limit,)).fetchall()
        for req in rows:
            try:
                params = template_params(json.loads(req["params"]))
            except (ValueError, TypeError):
                chat.execute("UPDATE adhoc_requests SET status='unsupported' WHERE id=?", (req["id"],))
                continue
            if params["kind"] != "festival":
                # Gigy: pipeline venues (OSM, setlist.fm) zatím neexistuje.
                chat.execute("UPDATE adhoc_requests SET status='unsupported' WHERE id=?", (req["id"],))
                unsupported += 1
                continue
            season = int((params["period_from"] or str(date.today().year + 1))[:4])
            db.enqueue_task(
                validator, type="search", priority=CHATBOT_PRIORITY, created_by="chatbot", assigned_to="explorer",
                payload={"entity": "festival", "kind": "chatbot_request", "country": params["country"],
                         "genre": params["genre"], "city": params["city"], "season": season,
                         "chatbot_request": req["id"]},
                dedupe_key=f"chatbot:{params['country']}:{params['genre']}:{season}",
            )
            chat.execute("UPDATE adhoc_requests SET status='forwarded', forwarded_at=? WHERE id=?",
                         (db.iso(db.utcnow()), req["id"]))
            forwarded += 1
        chat.commit()
    validator.commit()
    return {"forwarded": forwarded, "unsupported_gigs": unsupported}


def run_scheduled_searches(validator, collector_path, limit):
    """Consume queued CZ/SK discovery tasks when Exa credentials are available."""
    if not os.getenv("EXA_API_KEY"):
        return
    tasks = validator.execute("""SELECT * FROM tasks WHERE type='search'
        AND assigned_to='explorer' AND status='queued' ORDER BY priority, id LIMIT ?""", (limit,)).fetchall()
    for task in tasks:
        payload = json.loads(task["payload"])
        country = COUNTRIES.get(country_code(payload.get("country")))
        if not country or payload.get("entity") != "festival":
            continue
        year = payload.get("season") or date.today().year + 1
        genre = payload.get("genre") if payload.get("genre") in GENRES else "multi-genre"
        try:
            found = scout.search_new_festivals(
                country, genre, str(year), limit, festival_name=payload.get("name"),
            )
            queued = scout.save_to_queue(found, genre, country, str(collector_path))
        except Exception:
            print(f"Scheduled Exa task {task['id']} will retry on the next refresh.")
            break
        validator.execute("UPDATE tasks SET status='done', result=? WHERE id=?", (json.dumps({"queued": queued}), task["id"]))
        validator.commit()


def finish_refresh(validator, collector):
    rows = collector.execute("""SELECT validator_task, tasks.status, tasks.result FROM refresh_jobs
        JOIN tasks ON tasks.id=collector_task WHERE tasks.status IN ('done', 'failed')""")
    for task_id, status, result in rows:
        validator.execute("UPDATE tasks SET status=?, result=? WHERE id=? AND status='queued'", (status, result, task_id))
    validator.commit()


def run(args):
    baseline = read_dataset(args.dataset)
    args.state.mkdir(parents=True, exist_ok=True)
    candidates = []
    validators_path = args.state / "validator.sqlite"
    with closing(db.connect(validators_path)) as validator:
        db.init_db(validator)
        if args.seed_baseline:
            known = {row[0] for row in validator.execute("SELECT external_id FROM festivals")}
            new_baseline = [row for row in baseline["festivals"] if row["id"] not in known]
            print("Baseline import:", import_candidates(validator, new_baseline, baseline["festivals"]))
        if args.candidates:
            candidates = read_dataset(args.candidates)["festivals"]
        else:
            collector_path = args.state / "collector.sqlite"
            with closing(extraktor.pripoj_db(str(collector_path))) as collector:
                extraktor.GEO_CACHE = str(args.state / "geocache.sqlite")
                if args.scout:
                    found = scout.search_new_festivals(args.country, args.genre, args.year, args.limit)
                    count = scout.save_to_queue(found, args.genre, args.country, str(collector_path))
                    print(f"Scout queued {count} URLs")
                for url in args.url:
                    if not extraktor.cista_url(url):
                        raise ValueError(f"Invalid festival URL: {url}")
                    extraktor.pridej_ukol(collector, "extract", {"url": url, "kind": "festival"}, "manual")
                if args.refresh:
                    print("Chatbot requests:", forward_chatbot_requests(
                        validator, args.state / "chatbot.sqlite", args.limit))
                    queue_refresh(validator, collector, args.limit)
                    run_scheduled_searches(validator, collector_path, args.limit)
                extraktor.zpracuj_frontu(collector, args.limit)
                if args.refresh:
                    finish_refresh(validator, collector)
                candidate_file = args.state / "candidates.json"
                extraktor.export_web(collector, candidate_file, include_provenance=True)
                candidates = read_dataset(candidate_file)["festivals"]
        print("Import:", import_candidates(validator, candidates, baseline["festivals"]))
        print("Validation:", run_validator(validator))
        print("Freshness:", run_freshness(validator, countries=list(COUNTRIES)))
        snapshot = export_snapshot(validator, args.state / "snapshots")
        validated = json.loads(snapshot.read_text(encoding="utf-8"))["festivals"]
        changed = publish(args.dataset, baseline, validated)
        print(f"{'Updated' if changed else 'Kept'} {args.dataset} ({len(validated)} validated agent records)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "data/festivals.json")
    parser.add_argument("--state", type=Path, default=ROOT / ".agent-state")
    parser.add_argument("--seed-baseline", action="store_true", help="Register the current snapshot for future checks")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--candidates", type=Path, help="Validate a saved Extractor export without network calls")
    mode.add_argument("--scout", action="store_true", help="Find festival URLs using Exa")
    mode.add_argument("--url", action="append", default=[], help="Extract a known festival URL (repeatable)")
    mode.add_argument("--refresh", action="store_true", help="Process scheduled URL rechecks")
    parser.add_argument("--country", choices=tuple(COUNTRIES.values()), default="Czech Republic")
    parser.add_argument("--genre", default="multi-genre")
    parser.add_argument("--year", type=int, default=date.today().year + 1)
    parser.add_argument("--limit", type=int, choices=range(1, 51), metavar="1-50", default=5)
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
