import os
import sqlite3
import json
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse


DATABAZE = "mas.sqlite"          # stejný soubor jako Extraktor
POVOLENE_ZEME = {"Czech Republic", "Czechia", "Slovakia"}   # projekt je jen CZ a SK

# Stejné schéma tabulky tasks jako v Extraktoru (extraktor.py, SCHEMA_SQL) –
# díky tomu nezáleží na tom, který skript se spustí první.
SCHEMA_TASKS = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL, priority INTEGER NOT NULL DEFAULT 1,
    params TEXT NOT NULL DEFAULT '{}', created_by TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0, result TEXT, created_at TEXT, updated_at TEXT)
"""


def search_new_festivals(country, genre, year="2027", num_results=10, festival_name=None):
    """
    Searches for festivals using Exa AI.
    Accepts only strict variables (country, genre, year) to prevent prompt injection.
    """
    if country not in POVOLENE_ZEME:
        raise ValueError(f"Země '{country}' není v rozsahu projektu (jen CZ a SK).")
    api_key = os.getenv("EXA_API_KEY")
    if not api_key:
        raise RuntimeError("Chybí EXA_API_KEY v souboru .env")
    from exa_py import Exa

    exa = Exa(api_key=api_key)

    print(f"Searching for {genre} festivals in {country} for {year}...")
    # Exa je sémantické vyhledávání – popisujeme stránku, kterou chceme najít (OR se nevyhodnocuje).
    query = f"official website of a {genre} music festival in {country} in {year} with lineup and tickets"

    if festival_name:
        query = f"official website of {festival_name} music festival in {country} for {year}"
    response = exa.search(query, num_results=num_results)
    return response.results


def save_to_queue(results, genre, country=None, database=DATABAZE):
    """
    Saves the discovered URLs to the shared SQLite database queue.
    Skips URLs that are already in the queue (no duplicate tasks).
    """
    conn = sqlite3.connect(database)
    cursor = conn.cursor()
    cursor.execute(SCHEMA_TASKS)

    # URL, které už ve frontě jsou (jakýkoli stav) – neposílat znovu
    existujici = set()
    for (params,) in cursor.execute("SELECT params FROM tasks WHERE type = 'extract'"):
        try:
            existujici.add(json.loads(params or "{}").get("url", "").rstrip("/").lower())
        except ValueError:
            pass

    added_count = 0
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for res in results:
        url = res.url or ""
        if not url.startswith(("http://", "https://")) or not urlparse(url).netloc:
            continue
        if url.rstrip("/").lower() in existujici:
            continue
        params_json = json.dumps({"url": url, "kind": "festival", "hint": {"genre": genre, "country": country}}, ensure_ascii=False)
        cursor.execute("""
            INSERT INTO tasks (priority, type, status, created_by, params, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (1, 'extract', 'pending', 'pruzkumnik', params_json, now))
        existujici.add(url.rstrip("/").lower())
        added_count += 1

    conn.commit()
    conn.close()
    return added_count


# 2. Test search – spustí se jen při `python pruzkumnik_exa.py`, ne při importu z runneru / chatbota
if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    country = sys.argv[1] if len(sys.argv) > 1 else "Czech Republic"
    genre = sys.argv[2] if len(sys.argv) > 2 else "metal"

    found_sites = search_new_festivals(country, genre)
    saved_amount = save_to_queue(found_sites, genre)
    print(f"Success! Found {len(found_sites)} results, added {saved_amount} new links to the tasks queue.")
