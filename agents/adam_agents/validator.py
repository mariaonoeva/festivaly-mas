"""Agent 3 – Validátor / Kritik.

Bere záznamy ve stavu `pending_validation`, kontroluje je pravidly (bez LLM) a:
  * schválí je (`validated`) s mírou jistoty a rozpisem skóre,
  * vrátí je Extraktorovi (`needs_rework`, max. 1×) s důvodem ve frontě úkolů,
  * zamítne je (`rejected`), nebo je sloučí s existujícím záznamem (`duplicate`).
"""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date, datetime
from difflib import SequenceMatcher
from urllib.parse import urlparse

from . import db
from .freshness import compute_next_check, detect_changes, tracked_snapshot
from .genres import normalize_genres
from .geo import check_gps, haversine_km

MAX_REWORK = 1
MAX_FESTIVAL_DAYS = 120   # delší "festival" je spíš sezóna nebo chyba v datech

FESTIVAL_STATUSES = {"confirmed", "announced", "cancelled"}
CAPACITY_CATS = {"<5k", "5k-25k", "25k-50k", ">50k"}
VENUE_TYPES = {"club", "bar", "cultural_centre", "open_stage", "showcase", "local_event"}
BAND_SIZES = {"local", "emerging", "mid", "established"}

# Tyto chyby nelze po vyčerpání reworku obejít -> zamítnutí.
FATAL = {"missing_name", "missing_country", "invalid_country", "no_sources",
         "invalid_date_format", "date_order", "festival_too_long", "unrealistic_year",
         "suspicious_content", "unsafe_source_url"}

log = logging.getLogger("validator")

# Pokyny schované v obsahu webu (prompt injection proti Extraktoru). Validátor je
# deterministický, takže ho neovlivní, ale záznam s takovým textem nesmí projít.
SUSPICIOUS = re.compile(
    r"(ignore\s+(all\s+|any\s+)?(previous|prior|above|the)\s+instructions"
    r"|ignoruj(te)?\s+(v[sš]echny\s+|p[rř]edchoz[ií]\s+)?(instrukce|pokyny)"
    r"|system\s+prompt|you\s+are\s+now|mark\s+(this\s+)?as\s+(confirmed|verified|validated)"
    r"|ozna[cč]\s+(to\s+|jako\s+)+(potvrzen|ov[eě][rř]en)|<\s*script|javascript\s*:|\bon[a-z]+\s*=\s*[\"'])",
    re.IGNORECASE)
TEXT_FIELDS = ("name", "city", "region", "booking_contact")
MAX_TEXT = 200
SCANNED_FIELDS = ("name", "city", "region", "url", "genres", "lineup", "open_call",
                  "call_for_bands", "booking_contact", "status", "type", "sources")
EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")

NON_OFFICIAL_DOMAINS = (
    "facebook.com", "instagram.com", "tiktok.com", "x.com", "twitter.com", "ticketmaster.",
    "eventim.", "goout.net", "entrio.", "ra.co", "tickettailor.com", "songkick.com",
    "bandsintown.com", "eventbrite.", "festicket.com", "wikipedia.org", "setlist.fm",
)

COUNTRY_NAMES = {
    "czechia": "CZ", "czech republic": "CZ", "cesko": "CZ", "ceska republika": "CZ",
    "slovakia": "SK", "slovensko": "SK", "poland": "PL", "polsko": "PL", "austria": "AT",
    "rakousko": "AT", "germany": "DE", "nemecko": "DE", "hungary": "HU", "madarsko": "HU",
    "slovenia": "SI", "croatia": "HR", "chorvatsko": "HR", "serbia": "RS", "srbsko": "RS",
    "bosnia and herzegovina": "BA", "montenegro": "ME", "cerna hora": "ME",
    "north macedonia": "MK", "severni makedonie": "MK", "albania": "AL", "albanie": "AL",
    "slovak republic": "SK", "deutschland": "DE", "osterreich": "AT", "polska": "PL",
}

GENERIC_MAILBOXES = {
    "booking", "bookings", "info", "office", "kontakt", "contact", "events", "event",
    "program", "programme", "hello", "ahoj", "management", "bands", "music", "koncerty",
    "akce", "rezervace", "press", "media", "tickets", "mail", "team", "klub", "club",
    "dramaturgie", "produkce", "production", "festival", "openstage", "open-call",
}

TRACKED_SCALARS = ("date_from", "date_to", "status", "city", "country", "capacity_cat", "edition")


# ----------------------------------------------------------------- pomocné funkce
def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).lower().strip()


def norm_name(name: str) -> str:
    t = _plain(name)
    t = re.sub(r"\b(19|20)\d{2}\b", " ", t)
    t = re.sub(r"\b(the|festival|fest|festivalu|open ?air|edition|hudebni|music)\b", " ", t)
    return re.sub(r"[^a-z0-9]", "", t)


def norm_url(url: str | None) -> str:
    if not url:
        return ""
    p = urlparse(url if "://" in url else "https://" + url)
    host = p.netloc.lower().removeprefix("www.")
    return host + p.path.rstrip("/").lower()


def domain(url: str | None) -> str:
    if not url:
        return ""
    p = urlparse(url if "://" in url else "https://" + url)
    return p.netloc.lower().removeprefix("www.")


def base_domain(url: str | None) -> str:
    """Registrovaná doména: brno.majales.cz a vstupenky2027.majales.cz -> majales.cz."""
    host = domain(url).split(":")[0]
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net", "gov", "ac"):
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def parse_date(value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _strings(v)


def clean_text(text: str) -> str:
    """Odstraní HTML značky a řídicí znaky, zkrátí. Escapování dělá i frontend,
    tohle je druhá vrstva (defense in depth)."""
    t = re.sub(r"<[^>]*>", " ", text)
    t = "".join(c for c in t if c.isprintable())
    return " ".join(t.split())[:MAX_TEXT]


def safe_http_url(url) -> bool:
    if not isinstance(url, str):
        return False
    p = urlparse(url.strip())
    return p.scheme in ("http", "https") and "." in p.netloc


def _is_generic_mailbox(local: str) -> bool:
    return local.lower() in GENERIC_MAILBOXES


# ----------------------------------------------------------------- kontroly polí
def _check_common(rec: dict, errors: list, warnings: list, fixes: dict) -> None:
    if any(SUSPICIOUS.search(t) for f in SCANNED_FIELDS for t in _strings(rec.get(f))):
        errors.append("suspicious_content")
    for f in TEXT_FIELDS:
        v = rec.get(f)
        if isinstance(v, str) and v and clean_text(v) != v.strip():
            fixes[f] = clean_text(v)
            if "text_sanitized" not in warnings:
                warnings.append("text_sanitized")
    rec = {**rec, **fixes}

    name = (rec.get("name") or "").strip()
    if not name:
        errors.append("missing_name")
    elif name != rec.get("name"):
        fixes["name"] = name

    country = (rec.get("country") or "").strip()
    if not country:
        errors.append("missing_country")
    else:
        code = country.upper() if len(country) == 2 else COUNTRY_NAMES.get(_plain(country))
        if not code or not code.isalpha():
            errors.append("invalid_country")
        elif code != rec.get("country"):
            fixes["country"] = code

    url = rec.get("url")
    if not url:
        warnings.append("url_missing")
    else:
        p = urlparse(url)
        if p.scheme not in ("http", "https") or "." not in p.netloc:
            errors.append("invalid_url")
        elif any(d in p.netloc.lower() for d in NON_OFFICIAL_DOMAINS):
            warnings.append("url_not_official_site")

    sources = rec.get("sources") or []
    if not [s for s in sources if isinstance(s, dict) and s.get("url")]:
        errors.append("no_sources")
    elif any(isinstance(s, dict) and s.get("url") and not safe_http_url(s["url"]) for s in sources):
        errors.append("unsafe_source_url")
    redacted, changed = [], False
    for s in sources:
        if isinstance(s, dict) and isinstance(s.get("value"), str):
            m = EMAIL_RE.search(s["value"])
            if m and not _is_generic_mailbox(m.group(1)):
                s, changed = {**s, "value": "[odstraněno: osobní údaj]"}, True
        redacted.append(s)
    if changed:
        fixes["sources"] = redacted
        warnings.append("personal_data_redacted_in_sources")
    elif any(not db.parse_dt(s.get("fetched_at")) for s in sources if isinstance(s, dict)):
        warnings.append("source_without_fetch_date")

    codes, unknown = normalize_genres(rec.get("genres"))
    if codes != rec.get("genres"):
        fixes["genres"] = codes
    if unknown:
        safe = [re.sub(r"[^\w \-&]", "", u)[:30] for u in unknown[:5]]
        warnings.append("genre_unknown:" + "|".join(safe))
    if not codes:
        warnings.append("genres_missing")

    gps_err, gps_warn = check_gps(rec.get("lat"), rec.get("lon"), fixes.get("country") or country)
    errors.extend(gps_err)
    warnings.extend(gps_warn)


def _check_call(call: dict | None, event_start: date | None, warnings: list, prefix: str,
                fixes: dict | None = None, field: str | None = None) -> None:
    if not isinstance(call, dict) or not call:
        return
    if call.get("url") and not safe_http_url(call["url"]):
        warnings.append(f"{prefix}_unsafe_url_removed")
        call = {k: v for k, v in call.items() if k != "url"}
        if fixes is not None and field:
            fixes[field] = call
    if call.get("has") and not call.get("url"):
        warnings.append(f"{prefix}_without_url")
    dl = call.get("deadline")
    if dl:
        try:
            d = parse_date(dl)
        except ValueError:
            warnings.append(f"{prefix}_deadline_unparseable")
            return
        if event_start and d > event_start:
            warnings.append(f"{prefix}_deadline_after_event")


def check_festival(rec: dict, today: date) -> tuple[list, list, dict]:
    errors, warnings, fixes = [], [], {}
    _check_common(rec, errors, warnings, fixes)

    try:
        d_from, d_to = parse_date(rec.get("date_from")), parse_date(rec.get("date_to"))
    except ValueError:
        errors.append("invalid_date_format")
        d_from = d_to = None
    if d_from and not d_to:
        fixes["date_to"] = d_from.isoformat()
        warnings.append("date_to_missing_assumed_one_day")
        d_to = d_from
    if d_from and d_to:
        if d_to < d_from:
            errors.append("date_order")
        elif (d_to - d_from).days > MAX_FESTIVAL_DAYS:
            errors.append("festival_too_long")
        elif (d_to - d_from).days > 21:
            warnings.append("long_running_festival")  # klasika, jazzové cykly: týdny až měsíce
        if not (2024 <= d_from.year <= today.year + 2):
            errors.append("unrealistic_year")
        if d_to < today and rec.get("status") != "cancelled":
            warnings.append("event_in_past")
    elif not d_from:
        warnings.append("dates_missing")

    status = rec.get("status")
    if not status:
        warnings.append("status_missing")
        fixes["status"] = "announced"
    elif status not in FESTIVAL_STATUSES:
        errors.append("invalid_status")

    ed = rec.get("edition")
    try:
        if ed and d_from and int(ed) > 1900 and int(ed) != d_from.year:
            warnings.append("edition_year_mismatch")
    except (TypeError, ValueError):
        warnings.append("edition_not_numeric")

    cap = rec.get("capacity_cat")
    if cap and cap not in CAPACITY_CATS:
        warnings.append("capacity_cat_invalid")
        fixes["capacity_cat"] = None

    _check_call(rec.get("open_call"), d_from, warnings, "open_call", fixes, "open_call")

    # "potvrzeno" bez opory na oficiálním webu: stav necháme (zprávy z médií jsou legitimní
    # zdroj), ale snížíme jistotu. Podvržený pokyn ve stránce řeší SUSPICIOUS výše.
    if (fixes.get("status") or status) == "confirmed":
        official = base_domain(rec.get("url"))
        doms = {base_domain(s.get("url")) for s in rec.get("sources") or [] if isinstance(s, dict)}
        if not official or official not in doms or any(d in official for d in NON_OFFICIAL_DOMAINS):
            warnings.append("confirmed_from_secondary_source")
    return errors, warnings, fixes


def check_venue(rec: dict, today: date) -> tuple[list, list, dict]:
    errors, warnings, fixes = [], [], {}
    _check_common(rec, errors, warnings, fixes)

    if rec.get("type") not in VENUE_TYPES:
        warnings.append("venue_type_invalid")
        fixes["type"] = None
    if not rec.get("city"):
        errors.append("missing_city")  # gigy se hledají podle města
    cap = rec.get("capacity")
    if cap is not None:
        try:
            if not (10 <= int(cap) <= 100_000):
                warnings.append("capacity_unrealistic")
        except (TypeError, ValueError):
            warnings.append("capacity_not_numeric")
            fixes["capacity"] = None
    if rec.get("band_size") and rec["band_size"] not in BAND_SIZES:
        warnings.append("band_size_invalid")
        fixes["band_size"] = None

    # ochrana osobních údajů: jen obecný kontakt podniku
    contact = (fixes.get("booking_contact", rec.get("booking_contact")) or "").strip()
    if contact:
        m = EMAIL_RE.fullmatch(contact) or EMAIL_RE.fullmatch(contact.removeprefix("mailto:"))
        ok = (m and _is_generic_mailbox(m.group(1))) or (not m and safe_http_url(contact))
        if not ok:  # osobní e-mail, jméno, telefon na osobu... -> neukládat
            fixes["booking_contact"] = None
            warnings.append("personal_contact_removed")
            fixes["sources"] = [s for s in fixes.get("sources", rec.get("sources") or [])
                                if not (isinstance(s, dict) and s.get("field") == "booking_contact")]

    _check_call(rec.get("call_for_bands"), None, warnings, "call_for_bands", fixes, "call_for_bands")
    return errors, warnings, fixes


# ----------------------------------------------------------------- rozpory mezi zdroji
def resolve_conflicts(rec: dict) -> tuple[list[dict], dict]:
    """Najde pole, pro která různé domény uvádějí různé hodnoty.
    Pravidlo: vyhrává oficiální web festivalu/venue, jinak nejnovější stažení."""
    official = base_domain(rec.get("url"))
    by_field: dict[str, list[dict]] = {}
    for s in rec.get("sources") or []:
        if isinstance(s, dict) and s.get("field") and s.get("value") not in (None, ""):
            by_field.setdefault(s["field"], []).append(s)

    conflicts, fixes = [], {}
    for field, items in by_field.items():
        values = {_plain(str(i["value"])) for i in items}
        if len(values) < 2 or len({domain(i.get("url")) for i in items}) < 2:
            continue
        off = [i for i in items if official and base_domain(i.get("url")) == official]
        if off:
            chosen, rule = max(off, key=lambda i: i.get("fetched_at") or ""), "official_source"
        else:
            ranked = sorted(items, key=lambda i: i.get("fetched_at") or "", reverse=True)
            if len(ranked) > 1 and (ranked[0].get("fetched_at") or "") == (ranked[1].get("fetched_at") or ""):
                chosen, rule = None, "unresolved"
            else:
                chosen, rule = ranked[0], "newest_source"
        conflicts.append({
            "field": field,
            "values": sorted({str(i["value"]) for i in items}),
            "chosen": chosen["value"] if chosen else None,
            "rule": rule,
        })
        if chosen and field in TRACKED_SCALARS and str(rec.get(field)) != str(chosen["value"]):
            fixes[field] = chosen["value"]
    return conflicts, fixes


# ----------------------------------------------------------------- duplicity
def find_duplicate(conn, entity: str, rec: dict) -> dict | None:
    table = db.TABLE_FOR[entity]
    rows = conn.execute(
        f"SELECT * FROM {table} WHERE id != ? AND record_state IN "
        "('validated','pending_validation','needs_rework')", (rec["id"],)
    ).fetchall()
    n1, u1 = norm_name(rec.get("name") or ""), norm_url(rec.get("url"))
    ext = rec.get("external_id")
    for row in rows:
        other = db.row_to_dict(row)
        if ext and ext == other.get("external_id"):
            return other
        # Stejný web nebo jméno ve dvou různých městech = turné / série (Hrady CZ,
        # Bohemia JazzFest, Hip Hop Žije...), řetězec klubů apod. -> NENÍ duplicita.
        c1, c2 = _plain(rec.get("city") or ""), _plain(other.get("city") or "")
        same_place = (c1 == c2) if (c1 and c2) else True
        if not same_place:
            continue
        if u1 and u1 == norm_url(other.get("url")) and (entity == "venue" or _dates_overlap(rec, other)):
            return other
        sim = SequenceMatcher(None, n1, norm_name(other.get("name") or "")).ratio() if n1 else 0
        same_country = (rec.get("country") or "").upper() == (other.get("country") or "").upper()
        if sim >= 0.88 and same_country and (entity == "venue" or _dates_overlap(rec, other)):
            return other
        if None not in (rec.get("lat"), rec.get("lon"), other.get("lat"), other.get("lon")):
            km = haversine_km(rec["lat"], rec["lon"], other["lat"], other["lon"])
            if entity == "festival" and sim >= 0.6 and km <= 3 and _dates_overlap(rec, other):
                return other
            if entity == "venue" and sim >= 0.75 and km <= 0.3:
                return other
    return None


def _dates_overlap(a: dict, b: dict) -> bool:
    try:
        a1, a2 = parse_date(a.get("date_from")), parse_date(a.get("date_to") or a.get("date_from"))
        b1, b2 = parse_date(b.get("date_from")), parse_date(b.get("date_to") or b.get("date_from"))
    except ValueError:
        return False
    if not (a1 and b1):
        return True  # bez termínu rozhoduje jméno + místo
    return a1 <= b2 and b1 <= a2


def merge_into(conn, entity: str, keep: dict, drop: dict, now: datetime) -> None:
    """Sloučí `drop` do `keep`: spojí zdroje, doplní prázdná pole. `keep` jde znovu na validaci."""
    seen, merged = set(), []
    for s in (keep.get("sources") or []) + (drop.get("sources") or []):
        key = (s.get("field"), s.get("url"), str(s.get("value")))
        if key not in seen:
            seen.add(key)
            merged.append(s)
    fill = {}
    for k, v in drop.items():
        if k in ("id", "record_state", "created_at", "updated_at", "duplicate_of",
                 "validation_notes", "last_validated", "confidence", "confidence_label",
                 "rework_count", "next_check_at"):
            continue
        if keep.get(k) in (None, "", [], {}) and v not in (None, "", [], {}):
            fill[k] = v
    fill["sources"] = merged
    fill["record_state"] = "pending_validation"
    drop_update = {"record_state": "duplicate", "duplicate_of": keep["id"]}
    if "external_id" in fill:
        # external_id je unikátní: nejdřív ho uvolnit u duplicity, pak přesunout
        db.update_record(conn, entity, drop["id"], {"external_id": None})
        drop_update["external_id"] = None
    db.update_record(conn, entity, keep["id"], fill)
    db.update_record(conn, entity, drop["id"], drop_update)
    db.log_change(conn, entity=entity, entity_id=keep["id"], change_type="merged_duplicate",
                  old=drop["id"], new=keep["id"], source_url=drop.get("url"), at=now)


# ----------------------------------------------------------------- míra jistoty
KEY_FIELDS = {
    "festival": ("url", "city", "lat", "date_from", "genres", "status", "capacity_cat"),
    "venue": ("url", "city", "lat", "type", "genres", "capacity", "booking_contact"),
}


def score_confidence(entity: str, rec: dict, warnings: list, conflicts: list,
                     now: datetime, fallback_used: bool) -> tuple[float, str, dict]:
    b: dict[str, float] = {"base": 0.40}
    sources = [s for s in rec.get("sources") or [] if isinstance(s, dict) and s.get("url")]
    official = base_domain(rec.get("url"))
    doms = {base_domain(s["url"]) for s in sources}
    if official and official in doms and not any(d in official for d in NON_OFFICIAL_DOMAINS):
        b["official_source"] = 0.20
    extra = len(doms - {official}) if official in doms else max(len(doms) - 1, 0)
    if extra:
        b["independent_sources"] = round(min(0.10 * extra, 0.20), 2)
    filled = sum(1 for f in KEY_FIELDS[entity] if rec.get(f) not in (None, "", [], {}))
    b["completeness"] = round(0.20 * filled / len(KEY_FIELDS[entity]), 3)
    if warnings:
        b["warnings"] = -round(min(0.05 * len(warnings), 0.25), 2)
    unresolved = sum(1 for c in conflicts if c["rule"] == "unresolved")
    resolved = len(conflicts) - unresolved
    if unresolved or resolved:
        b["conflicts"] = -round(0.15 * unresolved + 0.05 * resolved, 2)
    newest = max((db.parse_dt(s.get("fetched_at")) for s in sources if db.parse_dt(s.get("fetched_at"))),
                  default=None)
    ttl = 7 if entity == "venue" else 30
    if newest is None or (now - newest).days > ttl:
        b["stale_sources"] = -0.10
    if fallback_used:
        b["after_rework_fallback"] = -0.10
    score = max(0.05, min(0.99, round(sum(b.values()), 2)))
    label = "high" if score >= 0.75 else "medium" if score >= 0.5 else "low"
    return score, label, b


# ----------------------------------------------------------------- hlavní smyčka
def validate_record(conn, entity: str, rec: dict, now: datetime | None = None) -> str:
    now = now or db.utcnow()
    today = now.date()

    dup = find_duplicate(conn, entity, rec)
    if dup:
        keep, drop = (dup, rec) if (dup["record_state"] == "validated" or dup["id"] < rec["id"]) else (rec, dup)
        merge_into(conn, entity, keep, drop, now)
        if keep["id"] != rec["id"]:
            return "duplicate"
        rec = db.row_to_dict(conn.execute(
            f"SELECT * FROM {db.TABLE_FOR[entity]} WHERE id = ?", (rec["id"],)).fetchone())

    conflicts, conflict_fixes = resolve_conflicts(rec)
    working = {**rec, **conflict_fixes}
    check = check_festival if entity == "festival" else check_venue
    errors, warnings, fixes = check(working, today)
    working.update(fixes)
    fixes.update(conflict_fixes)
    notes = {"errors": errors, "warnings": warnings, "conflicts": conflicts,
             "checked_at": db.iso(now)}

    fallback_used = False
    if errors:
        if (rec.get("rework_count") or 0) < MAX_REWORK:
            # bez oprav: Extraktor dostane původní stav i s důkazem, proč neprošel
            db.update_record(conn, entity, rec["id"], {
                "record_state": "needs_rework",
                "rework_count": (rec.get("rework_count") or 0) + 1,
                "validation_notes": notes,
            })
            db.enqueue_task(
                conn, type="extract", priority=20, created_by="validator", assigned_to="extractor",
                payload={"entity": entity, "id": rec["id"], "url": rec.get("url"),
                         "reason": "validation_failed", "errors": errors, "rework": True},
                dedupe_key=f"rework:{entity}:{rec['id']}",
            )
            return "needs_rework"
        fatal = [e for e in errors if e in FATAL]
        if fatal:
            db.update_record(conn, entity, rec["id"], {
                **fixes, "record_state": "rejected", "validation_notes": notes})
            db.log_change(conn, entity=entity, entity_id=rec["id"], change_type="rejected",
                          new=fatal, source_url=rec.get("url"), at=now)
            return "rejected"
        # neopravitelné, ale nefatální: odstraníme vadné pole a schválíme s nižší jistotou
        fallback_used = True
        for e in errors:
            if e.startswith("gps_"):
                fixes.update(lat=None, lon=None)
            elif e == "invalid_url":
                fixes["url"] = None
            elif e == "invalid_status":
                fixes["status"] = "announced"
            elif e == "missing_city":
                pass  # venue bez města nemá smysl -> viz FATAL níže
        if "missing_city" in errors:
            db.update_record(conn, entity, rec["id"], {
                **fixes, "record_state": "rejected", "validation_notes": notes})
            db.log_change(conn, entity=entity, entity_id=rec["id"], change_type="rejected",
                          new=["missing_city"], at=now)
            return "rejected"
        warnings.extend(f"dropped_after_rework:{e}" for e in errors)
        working.update(fixes)

    score, label, breakdown = score_confidence(entity, working, warnings, conflicts, now, fallback_used)
    notes["score_breakdown"] = breakdown

    new_snap = tracked_snapshot(entity, working)
    old_snap = rec.get("last_validated") if isinstance(rec.get("last_validated"), dict) else None
    for ch in detect_changes(entity, old_snap, new_snap):
        db.log_change(conn, entity=entity, entity_id=rec["id"], source_url=working.get("url"),
                      at=now, **ch)

    update = {
        **fixes,
        "record_state": "validated",
        "confidence": score,
        "confidence_label": label,
        "validation_notes": notes,
        "last_validated": new_snap,
        "last_checked": db.iso(now),
        "next_check_at": db.iso(compute_next_check(entity, {**working, "confidence": score}, now)),
    }
    if entity == "venue" and not rec.get("ttl_days"):
        update["ttl_days"] = 7
    db.update_record(conn, entity, rec["id"], update)
    return "validated"


def run_validator(conn, now: datetime | None = None) -> dict:
    """Zpracuje všechny záznamy čekající na validaci. Vrací souhrn pro log/runner."""
    summary: dict[str, int] = {}
    for entity, table in db.TABLE_FOR.items():
        ids = [r["id"] for r in conn.execute(
            f"SELECT id FROM {table} WHERE record_state = 'pending_validation' ORDER BY id")]
        for rid in ids:
            row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (rid,)).fetchone()
            if row is None or row["record_state"] != "pending_validation":
                continue  # mezitím sloučeno jako duplicita
            try:
                outcome = validate_record(conn, entity, db.row_to_dict(row), now)
            except Exception:  # fail closed: chybný běh nesmí nic zveřejnit
                conn.rollback()
                log.exception("validation crashed for %s id=%s", entity, rid)
                db.update_record(conn, entity, rid, {
                    "record_state": "validation_error",
                    "validation_notes": {"errors": ["internal_error"]}})
                outcome = "validation_error"
            summary[f"{entity}:{outcome}"] = summary.get(f"{entity}:{outcome}", 0) + 1
            conn.commit()
    # záznamy, které se při slučování vrátily na validaci
    again = sum(conn.execute(f"SELECT COUNT(*) FROM {t} WHERE record_state='pending_validation'")
                .fetchone()[0] for t in db.TABLE_FOR.values())
    if again:
        for k, v in run_validator(conn, now).items():
            summary[k] = summary.get(k, 0) + v
    return summary
