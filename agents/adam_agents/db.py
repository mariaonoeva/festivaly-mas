"""Přístup ke sdílené SQLite databázi. Agenti spolu nemluví napřímo, jen přes DB."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

JSON_COLUMNS = {
    "genres", "lineup", "open_call", "sources", "validation_notes",
    "last_validated", "call_for_bands", "payload",
}

TABLE_FOR = {"festival": "festivals", "venue": "venues"}
_COLUMNS: dict[str, set[str]] = {}


def _columns(conn, table: str) -> set[str]:
    """Povolené sloupce tabulky. Klíče ze záznamu (data z cizích webů) se nikdy
    nevkládají do SQL bez kontroly proti tomuto seznamu."""
    if table not in _COLUMNS:
        _COLUMNS[table] = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    return _COLUMNS[table]


def _safe_fields(conn, table: str, fields: dict) -> dict:
    allowed = _columns(conn, table)
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"unknown columns for {table}: {sorted(unknown)[:5]}")
    return fields


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    v = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # víc agentů nad jednou DB
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()


def row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    for k in JSON_COLUMNS & d.keys():
        if isinstance(d[k], str) and d[k]:
            try:
                d[k] = json.loads(d[k])
            except json.JSONDecodeError:
                pass
    return d


def update_record(conn, entity: str, rec_id: int, fields: dict) -> None:
    table = TABLE_FOR[entity]
    fields = dict(fields)
    fields["updated_at"] = iso(utcnow())
    _safe_fields(conn, table, fields)
    cols, vals = [], []
    for k, v in fields.items():
        if k in JSON_COLUMNS and not isinstance(v, str) and v is not None:
            v = json.dumps(v, ensure_ascii=False)
        cols.append(f"{k} = ?")
        vals.append(v)
    vals.append(rec_id)
    conn.execute(f"UPDATE {table} SET {', '.join(cols)} WHERE id = ?", vals)


def enqueue_task(conn, *, type: str, payload: dict, priority: int, created_by: str,
                 assigned_to: str, dedupe_key: str | None = None) -> int | None:
    """Vloží úkol do fronty. Pokud už stejný otevřený úkol čeká, nevloží nic."""
    if dedupe_key:
        exists = conn.execute(
            "SELECT id FROM tasks WHERE dedupe_key = ? AND status IN ('queued','in_progress')",
            (dedupe_key,),
        ).fetchone()
        if exists:
            return None
    cur = conn.execute(
        "INSERT INTO tasks (type, payload, priority, created_by, assigned_to, dedupe_key) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (type, json.dumps(payload, ensure_ascii=False), int(priority), created_by,
         assigned_to, dedupe_key),
    )
    return cur.lastrowid


def log_change(conn, *, entity: str, entity_id: int, change_type: str, field: str | None = None,
               old=None, new=None, source_url: str | None = None, at: datetime | None = None) -> None:
    def ser(v):
        if v is None or isinstance(v, str):
            return v
        return json.dumps(v, ensure_ascii=False, sort_keys=True)

    conn.execute(
        "INSERT INTO change_log (entity, entity_id, change_type, field, old_value, new_value, "
        "source_url, detected_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (entity, entity_id, change_type, field, ser(old), ser(new), source_url,
         iso(at or utcnow())),
    )


def insert_record(conn, entity: str, data: dict) -> int:
    """Pomocník pro testovací data a Extraktor: vloží záznam ve stavu pending_validation."""
    table = TABLE_FOR[entity]
    data = {k: v for k, v in dict(data).items() if not str(k).startswith("_")}
    data.setdefault("record_state", "pending_validation")
    _safe_fields(conn, table, data)
    cols, vals = [], []
    for k, v in data.items():
        if k in JSON_COLUMNS and not isinstance(v, str) and v is not None:
            v = json.dumps(v, ensure_ascii=False)
        cols.append(k)
        vals.append(v)
    cur = conn.execute(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(vals))})", vals
    )
    return cur.lastrowid
