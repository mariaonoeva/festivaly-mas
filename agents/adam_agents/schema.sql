-- Návrh sdíleného schématu (k odsouhlasení D1). Sloupce, které používá
-- Validátor a Správce aktuálnosti, jsou označené [A].
-- JSON sloupce jsou TEXT s JSON obsahem.

CREATE TABLE IF NOT EXISTS festivals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id     TEXT UNIQUE,        -- stabilní ID od Extraktoru, např. "cz-colours-of-ostrava-ostrava"
    event_type      TEXT,               -- festival | showcase | one-off
    name            TEXT NOT NULL,
    url             TEXT,
    country         TEXT,               -- ISO 3166-1 alpha-2 (CZ, SK, PL ...)
    city            TEXT,
    lat             REAL,
    lon             REAL,
    date_from       TEXT,               -- YYYY-MM-DD
    date_to         TEXT,               -- YYYY-MM-DD
    edition         INTEGER,            -- ročník (rok nebo pořadové číslo)
    genres          TEXT DEFAULT '[]',  -- JSON pole, po validaci normalizované kódy
    capacity_cat    TEXT,               -- '<5k' | '5k-25k' | '25k-50k' | '>50k'
    lineup          TEXT DEFAULT '[]',  -- JSON [{"year":2025,"artists":[...],"labels":[...]}]
    open_call       TEXT DEFAULT '{}',  -- JSON {"has":true,"url":"...","deadline":"YYYY-MM-DD"}
    status          TEXT,               -- 'confirmed' | 'announced' | 'cancelled'
    sources         TEXT DEFAULT '[]',  -- JSON [{"field","value","url","fetched_at"}]
    last_checked    TEXT,               -- ISO datetime UTC
    -- [A] stav zpracování a výstupy validace
    record_state    TEXT DEFAULT 'pending_validation',
                    -- pending_validation | needs_rework | validated | rejected | duplicate | validation_error
                    -- Veřejně (mapa, chatbot, snímek) se zobrazuje JEN 'validated'.
    rework_count    INTEGER DEFAULT 0,
    confidence      REAL,               -- 0..1
    confidence_label TEXT,              -- high | medium | low
    validation_notes TEXT DEFAULT '{}', -- JSON {errors, warnings, conflicts, score_breakdown}
    duplicate_of    INTEGER,
    last_validated  TEXT,               -- JSON snímek sledovaných polí (detekce změn)
    next_check_at   TEXT,               -- ISO datetime UTC, plánuje Správce
    created_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS venues (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    type            TEXT,               -- club | bar | cultural_centre | open_stage | showcase | local_event
    url             TEXT,
    country         TEXT,
    region          TEXT,               -- NUTS 2/3 kód nebo název kraje
    city            TEXT,
    lat             REAL,
    lon             REAL,
    capacity        INTEGER,
    genres          TEXT DEFAULT '[]',
    band_size       TEXT,               -- 'local' | 'emerging' | 'mid' | 'established'
    call_for_bands  TEXT DEFAULT '{}',  -- JSON {"has":true,"url":"...","deadline":"YYYY-MM-DD"}
    booking_contact TEXT,               -- jen obecný kontakt podniku (formulář / booking@...)
    sources         TEXT DEFAULT '[]',
    last_checked    TEXT,
    ttl_days        INTEGER,            -- [A] platnost záznamu
    record_state    TEXT DEFAULT 'pending_validation',
    rework_count    INTEGER DEFAULT 0,
    confidence      REAL,
    confidence_label TEXT,
    validation_notes TEXT DEFAULT '{}',
    duplicate_of    INTEGER,
    last_validated  TEXT,
    next_check_at   TEXT,
    created_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS tasks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    type         TEXT NOT NULL,          -- search | extract | recheck | validate
    payload      TEXT DEFAULT '{}',      -- JSON
    priority     INTEGER DEFAULT 50,     -- 0 = nejvyšší, 100 = nejnižší
    status       TEXT DEFAULT 'queued',  -- queued | in_progress | done | failed
    created_by   TEXT,                   -- explorer | extractor | validator | freshness | chatbot
    assigned_to  TEXT,                   -- explorer | extractor | ...
    dedupe_key   TEXT,                   -- brání duplicitním úkolům ve frontě
    attempts     INTEGER DEFAULT 0,
    result       TEXT,
    created_at   TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at   TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_tasks_queue ON tasks(status, assigned_to, priority);
CREATE INDEX IF NOT EXISTS idx_tasks_dedupe ON tasks(dedupe_key, status);

-- [A] log změn = odpověď na KIQ 5
CREATE TABLE IF NOT EXISTS change_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    entity       TEXT NOT NULL,          -- festival | venue
    entity_id    INTEGER NOT NULL,
    change_type  TEXT NOT NULL,          -- new | date_shift | cancelled | reinstated | new_edition |
                                         -- new_open_call | open_call_changed | lineup_changed |
                                         -- genres_changed | url_changed | capacity_changed |
                                         -- stale | merged_duplicate | rejected
    field        TEXT,
    old_value    TEXT,
    new_value    TEXT,
    source_url   TEXT,
    detected_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_changes ON change_log(entity, entity_id);
