"""CLI: python -m adam_agents <příkaz> --db mas.sqlite

  init                 vytvoří tabulky (návrh schématu)
  seed FILE.json       nahraje testovací záznamy ve formátu schématu {"festivals":[...],"venues":[...]}
  import FILE.json     import festivalů od Extraktoru (formát s id, website, source_url...)
  validate             Agent 3: zpracuje frontu pending_validation
  freshness            Agent 4: plánování kontrol, zastaralé záznamy, úkoly pro Průzkumníka
  tick                 validate + freshness (jeden krok pro společný runner)
  revalidate           vrátí záznamy se stavem validation_error znovu na validaci
  snapshot --out DIR   snímek datasetu pro obhajobu (JSON + CSV + report změn)
  load-snapshot FILE   obnoví DB ze snímku (demo bez API)
  report --days N      report změn (KIQ 5) v markdownu
"""
import argparse
import json
import sys
from pathlib import Path

from . import db
from .freshness import run_freshness
from .snapshot import change_report, export_snapshot, load_snapshot
from .validator import run_validator


def load_json_file(path: str) -> dict:
    """Načte JSON se srozumitelnou chybou místo tracebacku."""
    p = Path(path)
    if not p.is_file():
        sys.exit(f"Chyba: soubor '{path}' neexistuje. Spusť příkaz ze složky 'adam' "
                 f"(tam, kde jsou složky data a tests), nebo zadej celou cestu.")
    raw = p.read_bytes()
    text = raw.decode("utf-8-sig", errors="replace").lstrip()
    if text and text[0] not in "{[":
        first = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
        junk = text[:first] if first > 0 else text[:20]
        sys.exit(f"Chyba: '{path}' nezačíná JSONem, na začátku je navíc text {junk!r}. "
                 f"Smaž ho, soubor musí začínat znakem {{ nebo [.")
    if not raw.strip():
        sys.exit(f"Chyba: soubor '{path}' je prázdný ({len(raw)} B). Rozbal znovu zip, "
                 f"data/festivaly.json má mít asi 118 kB.")
    if raw.startswith(b"SQLite format"):
        sys.exit(f"Chyba: '{path}' je databáze, ne JSON. Databáze patří za --db PŘED příkaz:\n"
                 f"  python -m adam_agents --db mas.sqlite import data/festivaly.json")
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        sys.exit(f"Chyba: '{path}' není platný JSON ({e}). Začátek souboru: {raw[:60]!r}")


def is_extractor_format(data: dict) -> bool:
    """Dataset od Extraktoru má textové id a pole website/source_url/edition_year."""
    items = data.get("festivals") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        return False
    first = items[0]
    return isinstance(first.get("id"), str) or bool({"website", "source_url", "edition_year"} & set(first))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="adam_agents")
    ap.add_argument("--db", default="mas.sqlite")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    s = sub.add_parser("seed"); s.add_argument("file")
    im = sub.add_parser("import"); im.add_argument("file")
    sub.add_parser("validate")
    f = sub.add_parser("freshness")
    f.add_argument("--countries", default=None, help="např. CZ,SK,PL,AT,DE")
    f.add_argument("--min-per-country", type=int, default=15)
    sub.add_parser("tick")
    sub.add_parser("revalidate")
    sn = sub.add_parser("snapshot"); sn.add_argument("--out", default="snapshots")
    ls = sub.add_parser("load-snapshot"); ls.add_argument("file")
    r = sub.add_parser("report"); r.add_argument("--days", type=int, default=30)
    a = ap.parse_args(argv)

    conn = db.connect(a.db)
    db.init_db(conn)
    if a.cmd == "init":
        print(f"OK: {a.db}")
    elif a.cmd == "seed":
        data = load_json_file(a.file)
        if is_extractor_format(data):
            from .importer import import_festivals
            print("Soubor je ve formátu Extraktoru (website, source_url...), použiji import.")
            print(import_festivals(conn, data))
        else:
            try:
                n = {}
                for entity, key in (("festival", "festivals"), ("venue", "venues")):
                    for rec in data.get(key, []):
                        db.insert_record(conn, entity, rec)
                        n[key] = n.get(key, 0) + 1
            except ValueError as e:
                conn.rollback()
                sys.exit(f"Chyba: záznam neodpovídá schématu ({e}). Pro dataset od Extraktoru "
                         f"použij příkaz import.")
            conn.commit()
            print(n)
    elif a.cmd == "import":
        from .importer import import_festivals
        print(import_festivals(conn, load_json_file(a.file)))
    elif a.cmd == "validate":
        print(run_validator(conn))
    elif a.cmd == "freshness":
        countries = a.countries.split(",") if a.countries else None
        print(run_freshness(conn, countries=countries, min_per_country=a.min_per_country))
    elif a.cmd == "tick":
        print({"validator": run_validator(conn), "freshness": run_freshness(conn)})
    elif a.cmd == "revalidate":
        n = sum(conn.execute(f"UPDATE {t} SET record_state='pending_validation' "
                             "WHERE record_state='validation_error'").rowcount
                for t in db.TABLE_FOR.values())
        conn.commit()
        print({"revalidate": n, "validator": run_validator(conn)})
    elif a.cmd == "snapshot":
        print(export_snapshot(conn, a.out))
    elif a.cmd == "load-snapshot":
        print(load_snapshot(conn, a.file))
    elif a.cmd == "report":
        print(change_report(conn, a.days))
    return 0


if __name__ == "__main__":
    sys.exit(main())
