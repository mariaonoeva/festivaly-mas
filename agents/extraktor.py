#!/usr/bin/env python3
"""
Agent 2 · EXTRAKTOR  –  jeden soubor, zdarma, bez instalace (jen Python 3.10+)
===========================================================================

Co dělá:  pro URL festivalu nebo klubu stáhne stránku, vytáhne údaje podle schématu,
          namapuje žánry na číselník, doplní GPS (Nominatim), ke každému poli uloží zdroj
          a uloží záznam do SQLite databáze se stavem 'pending_validation'.

Spuštění (v terminálu ve složce se souborem):
    python extraktor.py https://www.colours.cz                 # jeden festival
    python extraktor.py https://www.klub.cz --venue            # klub / venue
    python extraktor.py --soubor urls.txt                      # víc URL (jedna na řádek)
    python extraktor.py --fronta                               # zpracuje úkoly 'extract' z fronty
    python extraktor.py --export festivaly.json                # export (plný formát, pro Validátora)
    python extraktor.py --export-web festivals.json            # export ve formátu webu festivaly-mas
    python extraktor.py --export-web nove.json --zlucit-s ../data/festivals.json   # doplní existující dataset webu
    python extraktor.py --zanry                                # číselník žánrů (markdown)

Na Windows místo `python` případně `py`.
"""

# ============================================================================
#  NASTAVENÍ – doplň svůj (školní) e-mail. Nominatim (GPS) ho vyžaduje.
# ============================================================================
import os

KONTAKT_EMAIL = os.getenv("NOMINATIM_CONTACT_EMAIL", "")
DATABAZE = "mas.sqlite"          # sdílená databáze (festivals, venues, tasks)
GEO_CACHE = "geocache.sqlite"    # cache GPS, ať se Nominatim neptáme dvakrát
MAX_STRANEK_NA_BEH = 50          # pojistka proti přetížení webů
POVOLENE_ZEME = {"CZ", "SK"}     # jen tyto země se ukládají (prázdná množina = všechny)
TTL_VENUE_DNI = 7
# ============================================================================

import argparse
import json
import re
import sqlite3
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from urllib import robotparser
from urllib.parse import urlencode, urljoin, urlparse, urlunparse

USER_AGENT_WEB = "MAS-festivaly-bot/0.1 (skolni projekt)"
USER_AGENT_GEO = f"MAS-festivaly-skolni-projekt/0.1 (kontakt: {KONTAKT_EMAIL})"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


def ted() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ============================================================================
#  1. ČÍSELNÍK ŽÁNRŮ
# ============================================================================
ZANRY: dict[str, tuple[str, list[str]]] = {
    "rock": ("Rock", ["rock", "hard rock", "classic rock", "stoner", "garage", "rock n roll", "rockabilly",
                      "psychedelic rock", "prog rock", "progressive rock", "blues rock"]),
    "metal": ("Metal", ["metal", "heavy metal", "death metal", "black metal", "doom", "thrash", "metalcore",
                        "deathcore", "nu metal", "power metal", "sludge", "grindcore"]),
    "punk": ("Punk / hardcore", ["punk", "hardcore", "post-hardcore", "pop punk", "pop-punk", "oi", "crust",
                                 "emo", "skate punk", "hc"]),
    "indie": ("Indie", ["indie", "indie rock", "indie pop", "lo-fi", "lofi", "dream pop", "shoegaze",
                        "post-punk", "new wave", "britpop"]),
    "alternative": ("Alternativa", ["alternative", "alternativa", "alternativni", "alt rock", "grunge",
                                    "post-rock", "math rock", "noise rock"]),
    "pop": ("Pop", ["pop", "synthpop", "synth-pop", "electropop", "k-pop", "dance pop"]),
    "electronic": ("Elektronika", ["electronic", "elektronika", "elektronicka hudba", "techno", "house",
                                   "trance", "drum and bass", "drum & bass", "dnb", "d&b", "dubstep", "edm",
                                   "ambient", "idm", "breakbeat", "hardstyle", "psytrance", "electro", "rave"]),
    "hiphop": ("Hip hop / rap", ["hip hop", "hip-hop", "hiphop", "rap", "trap", "grime", "drill"]),
    "rnb_soul": ("R&B / soul / funk", ["r&b", "rnb", "soul", "funk", "neo soul", "disco", "gospel"]),
    "jazz": ("Jazz", ["jazz", "swing", "bebop", "fusion", "big band", "acid jazz", "nu jazz"]),
    "blues": ("Blues", ["blues", "delta blues", "rhythm and blues"]),
    "folk": ("Folk / akustická", ["folk", "folk rock", "bluegrass", "americana", "acoustic", "akusticka",
                                  "trampska", "country folk", "celtic", "keltska"]),
    "singer_songwriter": ("Písničkáři", ["singer-songwriter", "singer songwriter", "pisnickar", "pisnickari",
                                        "piosenka autorska", "liedermacher"]),
    "world": ("World music", ["world", "world music", "etno", "ethno", "balkan", "latin", "afrobeat",
                              "flamenco", "klezmer", "gypsy", "romska"]),
    "reggae_ska": ("Reggae / ska", ["reggae", "ska", "dub", "dancehall", "rocksteady"]),
    "classical": ("Klasická / opera", ["classical", "klasicka", "vazna hudba", "opera", "orchestral",
                                       "chamber", "komorni", "baroque", "contemporary classical"]),
    "experimental": ("Experimentální", ["experimental", "experimentalni", "avant-garde", "avantgarde", "noise",
                                        "drone", "improv", "improvizace"]),
    "country": ("Country", ["country", "western", "alt-country"]),
    "multi": ("Multižánrový", ["multigenre", "multi-genre", "multizanr", "multizanrovy", "various", "mixed",
                               "vsechny zanry", "eclectic", "eklekticky"]),
}

# Slova, která v běžném textu znamenají i něco jiného – při hledání v textu stránky se ignorují.
DVOJZNACNA = {"house", "world", "western", "drone", "noise", "soul", "swing", "fusion", "dub", "ska", "oi",
              "hc", "emo", "rap", "trap", "drill", "doom", "garage", "chamber", "latin", "celtic", "acoustic",
              "akusticka", "improv", "mixed", "various", "music", "opera", "country", "classical",
              "experimental", "alternative", "funk", "disco", "grime", "electro", "rave", "dance pop", "pop",
              "big band", "eclectic"}


def bez_diakritiky(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text.lower()).strip()


_INDEX = sorted(((bez_diakritiky(s), kod) for kod, (_, syn) in ZANRY.items() for s in syn),
                key=lambda x: -len(x[0]))


def _vzor(slovo: str) -> str:
    return r"(?<![a-z0-9])" + re.escape(slovo) + r"(?![a-z0-9])"


def namapuj_zanry(tagy) -> tuple[list[str], list[str]]:
    """Volné tagy -> (kódy z číselníku, nenamapované tagy)."""
    kody, nenamapovane = set(), []
    for tag in tagy or []:
        if not isinstance(tag, str):
            continue
        zbytek, nalezeno = bez_diakritiky(tag), set()
        for syn, kod in _INDEX:
            if re.search(_vzor(syn), zbytek):
                nalezeno.add(kod)
                zbytek = re.sub(_vzor(syn), " ", zbytek)
        if nalezeno:
            kody |= nalezeno
        elif tag.strip():
            nenamapovane.append(tag.strip()[:60])
    return sorted(kody), nenamapovane


def zanry_z_textu(text: str, min_vyskytu: int = 2) -> list[str]:
    """Bez LLM: žánrová slova, která jsou na stránce aspoň 2×."""
    t = bez_diakritiky(text)
    pocty = {}
    for syn, _ in _INDEX:
        if len(syn) < 4 or syn in DVOJZNACNA:
            continue
        n = len(re.findall(_vzor(syn), t))
        if n >= min_vyskytu:
            pocty[syn] = n
    return [s for s, _ in sorted(pocty.items(), key=lambda x: -x[1])][:10]


# ============================================================================
#  2. ČIŠTĚNÍ DAT (vše z webu je nedůvěryhodné – ochrana proti XSS a nesmyslům)
# ============================================================================
def cisty_text(v, max_delka=200):
    if not isinstance(v, str):
        return None
    v = re.sub(r"<[^>]*>", "", v)
    v = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f<>]", "", v)
    v = re.sub(r"\s+", " ", v).strip()
    return v[:max_delka] or None


def cista_url(v, zaklad=None):
    if not isinstance(v, str) or not v.strip():
        return None
    v = urljoin(zaklad, v.strip()) if zaklad else v.strip()
    p = urlparse(v)
    if p.scheme not in ("http", "https") or not p.netloc:
        return None
    return urlunparse((p.scheme, p.netloc.lower(), p.path or "/", "", p.query, ""))[:500]


def klic_url(url: str) -> str:
    p = urlparse(url)
    return p.netloc.lower().removeprefix("www.") + p.path.rstrip("/")


def ciste_datum(v):
    if not isinstance(v, str):
        return None
    try:
        d = date.fromisoformat(v.strip()[:10])
    except ValueError:
        return None
    return d.isoformat() if 2000 <= d.year <= 2035 else None


def cista_zeme(v):
    if not isinstance(v, str):
        return None
    v = v.strip().upper()
    v = "GB" if v == "UK" else v
    return v if re.fullmatch(r"[A-Z]{2}", v) else None


def cele_cislo(v, lo=0, hi=10_000_000):
    if isinstance(v, bool):
        return None
    if isinstance(v, str) and v.strip().isdigit():
        v = int(v.strip())
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return v if isinstance(v, int) and lo <= v <= hi else None


def kategorie_kapacity(n):
    if not n or n <= 0:
        return None
    if n < 5_000:
        return "do 5 000"
    if n < 25_000:
        return "5 000–25 000"
    if n <= 50_000:
        return "25 000–50 000"
    return "nad 50 000"


# --- krajina podle domény (jen když ji stránka neuvádí) -------------------------
TLD_ZEME = {"cz": "CZ", "sk": "SK", "pl": "PL", "at": "AT", "de": "DE", "hu": "HU", "si": "SI", "hr": "HR",
            "ch": "CH", "nl": "NL", "be": "BE", "dk": "DK", "fr": "FR", "it": "IT", "es": "ES", "pt": "PT",
            "lt": "LT", "lv": "LV", "ee": "EE", "ro": "RO", "rs": "RS", "fi": "FI", "se": "SE", "no": "NO"}


def zeme_z_domeny(url: str):
    return TLD_ZEME.get(urlparse(url).netloc.lower().rsplit(".", 1)[-1])


# --- data konání z textu stránky ------------------------------------------------
MESICE = {}
for _cislo, _tvary in enumerate([
        ["leden", "ledna", "januar", "januara", "styczen", "stycznia", "january", "jan", "janner", "jänner"],
        ["unor", "unora", "februar", "februara", "luty", "lutego", "february", "feb"],
        ["brezen", "brezna", "marec", "marca", "marzec", "marca", "march", "marz", "mar"],
        ["duben", "dubna", "april", "aprila", "kwiecien", "kwietnia", "apr"],
        ["kveten", "kvetna", "maj", "maja", "may", "mai"],
        ["cerven", "cervna", "jun", "juna", "czerwiec", "czerwca", "june", "juni"],
        ["cervenec", "cervence", "jul", "jula", "lipiec", "lipca", "july", "juli"],
        ["srpen", "srpna", "august", "augusta", "sierpien", "sierpnia", "aug"],
        ["zari", "september", "septembra", "wrzesien", "wrzesnia", "sep", "sept"],
        ["rijen", "rijna", "oktober", "oktobra", "pazdziernik", "pazdziernika", "october", "oct", "okt"],
        ["listopad", "listopadu", "november", "novembra", "listopada", "nov"],
        ["prosinec", "prosince", "december", "decembra", "grudzien", "grudnia", "dez", "dec", "dezember"]], 1):
    for _t in _tvary:
        MESICE[_t] = _cislo
_MES = "|".join(sorted(MESICE, key=len, reverse=True))
_POMLCKA = r"\s*(?:[-–—]|az|do|to|bis)\s*"
_ROK = r"(20[2-3]\d)"
VZORY_DAT = [
    # 30 June – 3 July 2027  /  30. června – 3. července 2027
    (re.compile(r"(\d{1,2})\.?\s*(" + _MES + r")\.?" + _POMLCKA + r"(\d{1,2})\.?\s*(" + _MES + r")\.?\s*" + _ROK),
     lambda m: ((m[1], m[2], m[5]), (m[3], m[4], m[5]))),
    # June 30 – July 3, 2027
    (re.compile(r"(" + _MES + r")\.?\s*(\d{1,2})" + _POMLCKA + r"(" + _MES + r")\.?\s*(\d{1,2}),?\s*" + _ROK),
     lambda m: ((m[2], m[1], m[5]), (m[4], m[3], m[5]))),
    # 2.–5. 6. 2027  /  2.6.–5.6.2027  /  02.06.2027 - 05.06.2027
    (re.compile(r"(\d{1,2})\.\s*(?:(\d{1,2})\.\s*(?:" + _ROK + r")?)?" + _POMLCKA + r"(\d{1,2})\.\s*(\d{1,2})\.\s*" + _ROK),
     lambda m: ((m[1], m[2] or m[5], m[3] or m[6]), (m[4], m[5], m[6]))),
    # 2.–5. června 2027  /  8 - 10 July 2027
    (re.compile(r"(\d{1,2})\.?" + _POMLCKA + r"(\d{1,2})\.?\s*(" + _MES + r")\.?\s*" + _ROK),
     lambda m: ((m[1], m[3], m[4]), (m[2], m[3], m[4]))),
    # June 2–5, 2027
    (re.compile(r"(" + _MES + r")\.?\s*(\d{1,2})" + _POMLCKA + r"(\d{1,2}),?\s*" + _ROK),
     lambda m: ((m[2], m[1], m[4]), (m[3], m[1], m[4]))),
    # 2027-06-02 (ISO)
    (re.compile(_ROK + r"-(\d{2})-(\d{2})"), lambda m: ((m[3], m[2], m[1]), None)),
    # 8. července 2027 / 8 July 2027
    (re.compile(r"(\d{1,2})\.?\s*(" + _MES + r")\.?\s*" + _ROK), lambda m: ((m[1], m[2], m[3]), None)),
    # 8. 7. 2027
    (re.compile(r"(\d{1,2})\.\s*(\d{1,2})\.\s*" + _ROK), lambda m: ((m[1], m[2], m[3]), None)),
]


def _na_datum(d, m, r):
    try:
        mesic = int(m) if str(m).isdigit() else MESICE[bez_diakritiky(str(m)).rstrip(".")]
        return date(int(r), mesic, int(d))
    except (ValueError, KeyError, TypeError):
        return None


def data_z_textu(text: str):
    """Najde první budoucí termín (od–do) v textu. Vrací (od, do) jako ISO texty, nebo (None, None)."""
    t = bez_diakritiky(text)
    dnes = date.today()
    nalezene = []
    for vzor, prevod in VZORY_DAT:
        for m in vzor.finditer(t):
            a, b = prevod(m)
            od = _na_datum(*a)
            do = _na_datum(*b) if b else od
            if od and do and od <= do and (do - od).days <= 14 and do >= dnes:
                nalezene.append((m.start(), od, do))
        if nalezene and any(od != do for _, od, do in nalezene):
            break  # přesnější vzory (rozsahy) mají přednost
    if not nalezene:
        return None, None
    _, od, do = min(nalezene)
    return od.isoformat(), do.isoformat()


OBECNE_NAZVY = re.compile(
    r"(home|homepage|home page|uvod|uvodni strana|uvodna stranka|domu|domov|hlavna stranka|hlavni strana|"
    r"start|startseite|strona glowna|welcome|vitejte|vitajte|index|news|novinky|aktuality|aktualnosti|"
    r"official website|official site|oficialni web|oficialna stranka|oficialni stranky|"
    r"vstupenky|listky|tickets|bilety|karten|tickety|program|line-?up|en|cz|sk|pl|de|"
    r"\d{4}|festival|music festival|hudebni festival|hudobny festival)"
)

OBECNE_SCHRANKY = {"info", "booking", "bookings", "office", "kontakt", "contact", "hello", "ahoj", "program",
                   "programme", "events", "event", "akce", "kancelar", "management", "press", "festival",
                   "koncerty", "concerts", "music", "hudba", "biuro", "mail", "team", "shows"}


def obecny_kontakt(v):
    """Jen obecný kontakt podniku (booking@, info@, URL formuláře). Osobní kontakty se zahodí."""
    if not isinstance(v, str):
        return None
    v = v.strip().removeprefix("mailto:")
    if re.match(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$", v):
        lokal = v.split("@")[0].lower()
        if lokal in OBECNE_SCHRANKY or re.split(r"[._-]", lokal)[0] in OBECNE_SCHRANKY:
            return v.lower()
        return None
    return cista_url(v)


# ============================================================================
#  3. STAŽENÍ STRÁNKY
# ============================================================================
_robots_cache: dict[str, robotparser.RobotFileParser] = {}


def http_get(url: str, user_agent: str, timeout: int = 30) -> tuple[int, str, str]:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept-Language": "cs,sk,en;q=0.8"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read(3_000_000)
            charset = r.headers.get_content_charset() or "utf-8"
            return r.status, r.headers.get("Content-Type", ""), data.decode(charset, errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, "", ""


def smi_stahnout(url: str) -> bool:
    p = urlparse(url)
    zaklad = f"{p.scheme}://{p.netloc}"
    if zaklad not in _robots_cache:
        rp = robotparser.RobotFileParser()
        try:
            status, _, text = http_get(zaklad + "/robots.txt", USER_AGENT_WEB, timeout=10)
            rp.parse(text.splitlines() if status == 200 else [])
        except Exception:
            rp.parse([])
        _robots_cache[zaklad] = rp
    return _robots_cache[zaklad].can_fetch(USER_AGENT_WEB, url)


class Stranka(HTMLParser):
    """Z HTML vytáhne text, odkazy, titulek, meta tagy a bloky schema.org (JSON-LD)."""
    PRESKOCIT = {"script", "style", "noscript", "svg", "template"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text, self.odkazy, self.jsonld, self.titulek = [], [], [], []
        self.nadpisy: list[str] = []
        self._v_h1 = False
        self._h1 = []
        self.odkazy_text: list[tuple[str, str, list[str]]] = []   # (href, text, kusy textu) – pro line-up
        self._a_href, self._a_text = None, []
        self.meta = {}
        self._skip, self._v_ld, self._v_title, self._ld = 0, False, False, []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script" and (a.get("type") or "").lower() == "application/ld+json":
            self._v_ld, self._ld = True, []
        elif tag in self.PRESKOCIT:
            self._skip += 1
        elif tag == "title":
            self._v_title = True
        elif tag == "h1":
            self._v_h1, self._h1 = True, []
        elif tag == "img" and (self._v_h1 or self._a_href) and a.get("alt"):
            if self._v_h1:
                self._h1.append(" " + a["alt"] + " ")
            if self._a_href:
                self._a_text.append(" " + a["alt"] + " ")
        elif tag == "meta":
            k = (a.get("property") or a.get("name") or "").lower()
            if k in ("og:site_name", "og:title", "description", "og:description", "keywords") and a.get("content"):
                self.meta.setdefault(k, a["content"])
        elif tag == "a" and a.get("href"):
            self.odkazy.append(a["href"])
            self._a_href, self._a_text = a["href"], []
        if tag in ("p", "br", "li", "h1", "h2", "h3", "tr", "div"):
            self.text.append("\n")

    def handle_endtag(self, tag):
        if tag == "script" and self._v_ld:
            self._v_ld = False
            self.jsonld.append("".join(self._ld))
        elif tag in self.PRESKOCIT and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._v_title = False
        elif tag == "h1" and self._v_h1:
            self._v_h1 = False
            self.nadpisy.append("".join(self._h1))
        if tag == "a" and self._a_href:
            kusy = [re.sub(r"\s+", " ", k).strip() for k in self._a_text]
            self.odkazy_text.append((self._a_href, re.sub(r"\s+", " ", "".join(self._a_text)).strip(),
                                     [k for k in kusy if k]))
            self._a_href, self._a_text = None, []

    def handle_data(self, data):
        if self._v_ld:
            self._ld.append(data)
        elif self._v_title:
            self.titulek.append(data)
        elif self._v_h1 and not self._skip:
            self._h1.append(data)
            self.text.append(data)
        elif not self._skip:
            self.text.append(data)
        if self._a_href and not self._skip and not self._v_ld:
            self._a_text.append(data)

    def cely_text(self) -> str:
        t = " ".join(filter(None, [self.meta.get("keywords"), self.meta.get("description"),
                                   self.meta.get("og:description")])) + "\n" + "".join(self.text)
        t = re.sub(r"[ \t]+", " ", t)
        return re.sub(r"\n\s*\n+", "\n", t).strip()[:20_000]

    def nazev_z_titulku(self, url: str = ""):
        """Název bez schema.org: z og:site_name, og:title, <title> a <h1>.

        Titulky rozdělí podle oddělovačů (| / – -), zahodí obecné části („Home“, „Úvod“, „Vstupenky“…)
        a vybere tu část, která se nejvíc podobá doméně webu (brutalassault.cz → „Brutal Assault“).
        """
        kandidati = [self.meta.get("og:site_name"), self.meta.get("og:title"), "".join(self.titulek)] + self.nadpisy[:2]
        domena = bez_diakritiky(urlparse(url).netloc.removeprefix("www.").split(".")[0]) if url else ""
        domena = re.sub(r"[^a-z0-9]", "", domena)
        cesta = re.sub(r"[^a-z0-9]", "", bez_diakritiky(urlparse(url).path)) if url else ""
        nejlepsi, skore_max = None, -1
        for poradi, kandidat in enumerate(kandidati):
            if not kandidat:
                continue
            for cast in re.split(r"\s*[|/–—·:»«]\s*|\s+-\s+", kandidat):
                cast = re.sub(r"\s+", " ", cast).strip(" -–")
                cast = re.sub(r"\s*\b(logo|logotyp|logotype)\b\s*$", "", cast, flags=re.I).strip()
                norm = bez_diakritiky(cast)
                if not (2 <= len(cast) <= 80) or OBECNE_NAZVY.fullmatch(norm):
                    continue
                kompakt = re.sub(r"[^a-z0-9]", "", norm)
                if not kompakt:
                    continue
                skore = 10 - poradi  # dřívější zdroj (og:site_name) mírně preferovaný
                if domena and (kompakt in domena or domena in kompakt):
                    skore += 50
                elif domena and len(domena) >= 4 and domena[:4] in kompakt:
                    skore += 20
                if len(kompakt) >= 5 and kompakt in cesta:
                    skore += 60  # katalogová stránka: název akce je v adrese (…/rock-for-people-2027/)
                if skore > skore_max:
                    nejlepsi, skore_max = cast, skore
        if nejlepsi:
            if nejlepsi.isupper() and len(nejlepsi) > 4:
                nejlepsi = nejlepsi.title()  # POHODA FESTIVAL → Pohoda Festival
            return nejlepsi
        return domena.capitalize() if domena else None


def stahni(url: str) -> Stranka:
    if not smi_stahnout(url):
        raise PermissionError("robots.txt zakazuje stažení této stránky")
    status, typ, html = http_get(url, USER_AGENT_WEB)
    if status >= 400:
        raise RuntimeError(f"web vrátil chybu {status}")
    if typ and "html" not in typ:
        raise RuntimeError("stránka není HTML")
    s = Stranka()
    s.feed(html)
    return s


# ============================================================================
#  4. SCHEMA.ORG (strukturovaná data, která má na stránce hodně festivalů a prodejců)
# ============================================================================
def _uzly(obj):
    if isinstance(obj, list):
        for x in obj:
            yield from _uzly(x)
    elif isinstance(obj, dict):
        yield obj
        for k in ("@graph", "subEvent", "event"):
            if k in obj:
                yield from _uzly(obj[k])


def _typy(uzel) -> set:
    t = uzel.get("@type", [])
    return {x.lower() for x in (t if isinstance(t, list) else [t]) if isinstance(x, str)}


def _prvni(v):
    return v[0] if isinstance(v, list) and v else v


def _misto(loc) -> dict:
    loc = _prvni(loc) or {}
    if not isinstance(loc, dict):
        return {"misto_nazev": loc if isinstance(loc, str) else None}
    adr = _prvni(loc.get("address")) or {}
    if isinstance(adr, str):
        adr = {"streetAddress": adr}
    zeme = adr.get("addressCountry")
    if isinstance(zeme, dict):
        zeme = zeme.get("identifier") or zeme.get("name")
    out = {
        "misto_nazev": loc.get("name"),
        "mesto": adr.get("addressLocality"),
        "adresa": ", ".join(x for x in [adr.get("streetAddress"), adr.get("postalCode")] if isinstance(x, str)) or None,
        "zeme": zeme if isinstance(zeme, str) and len(zeme.strip()) == 2 else None,
    }
    geo = loc.get("geo") or {}
    try:
        out["gps"] = (float(geo["latitude"]), float(geo["longitude"]))
    except (KeyError, TypeError, ValueError):
        pass
    return out


def _nacti_jsonld(stranka):
    for blok in stranka.jsonld:
        try:
            yield from _uzly(json.loads(blok))
        except ValueError:
            continue


STAV_AKCE = {"eventscheduled": "potvrzeno", "eventmovedonline": "potvrzeno", "eventrescheduled": "ohlášeno",
             "eventpostponed": "ohlášeno", "eventcancelled": "zrušeno"}


def schema_festival(stranka) -> dict:
    udalosti = [n for n in _nacti_jsonld(stranka) if _typy(n) & {"musicevent", "festival", "event", "musicfestival"}]
    if not udalosti:
        return {}
    udalosti.sort(key=lambda n: 0 if _typy(n) & {"festival", "musicfestival"} else 1)
    ev = udalosti[0]
    start = ev.get("startDate") if isinstance(ev.get("startDate"), str) else None
    interpreti = []
    for e in udalosti:
        perf = e.get("performer")
        for p in perf if isinstance(perf, list) else [perf]:
            jmeno = p.get("name") if isinstance(p, dict) else p
            if isinstance(jmeno, str):
                interpreti.append(jmeno)
    zanry = []
    for e in udalosti:
        g = e.get("genre")
        zanry += g if isinstance(g, list) else [g] if isinstance(g, str) else []
    out = {
        "nazev": ev.get("name"),
        "od": start[:10] if start else None,
        "do": ev["endDate"][:10] if isinstance(ev.get("endDate"), str) else None,
        "kapacita": ev.get("maximumAttendeeCapacity"),
        "stav": STAV_AKCE.get(str(ev.get("eventStatus") or "").rsplit("/", 1)[-1].lower()),
        "interpreti": interpreti,
        "zanry": zanry,
        **_misto(ev.get("location")),
    }
    return {k: v for k, v in out.items() if v not in (None, [], "")}


def schema_venue(stranka) -> dict:
    typy_venue = {"musicvenue", "nightclub", "barorpub", "place", "localbusiness", "eventvenue",
                  "performingartstheater", "civicstructure"}
    for n in _nacti_jsonld(stranka):
        t = _typy(n)
        if t & typy_venue:
            out = {"nazev": n.get("name"), "kapacita": n.get("maximumAttendeeCapacity"), "kontakt": n.get("email"),
                   "typ": "klub" if "nightclub" in t else "bar" if "barorpub" in t else None, **_misto(n)}
            out.pop("misto_nazev", None)
            return {k: v for k, v in out.items() if v not in (None, [], "")}
    return {}


# ============================================================================
#  5. GPS přes Nominatim (zdarma; max 1 dotaz/s, vlastní User-Agent, cache)
# ============================================================================
_posledni_geo = 0.0


def geokoduj(adresa=None, misto=None, mesto=None, zeme=None):
    global _posledni_geo
    db = sqlite3.connect(GEO_CACHE)
    db.execute("CREATE TABLE IF NOT EXISTS geocache (dotaz TEXT PRIMARY KEY, vysledek TEXT)")
    pokusy = []
    if adresa:
        pokusy.append(("adresa", ", ".join(x for x in [adresa, mesto] if x)))
    if misto and mesto:
        pokusy.append(("misto", f"{misto}, {mesto}"))
    if mesto:
        pokusy.append(("mesto", mesto))
    try:
        for presnost, q in pokusy:
            params = {"q": q, "format": "jsonv2", "limit": 1, "addressdetails": 1}
            if zeme:
                params["countrycodes"] = zeme.lower()
            url = NOMINATIM_URL + "?" + urlencode(params)
            radek = db.execute("SELECT vysledek FROM geocache WHERE dotaz=?", (url,)).fetchone()
            if radek:
                data = json.loads(radek[0])
            else:
                cekej = 1.1 - (time.monotonic() - _posledni_geo)
                if cekej > 0:
                    time.sleep(cekej)
                status, _, text = http_get(url, USER_AGENT_GEO, timeout=20)
                _posledni_geo = time.monotonic()
                if status != 200:
                    continue
                data = json.loads(text)
                db.execute("INSERT OR REPLACE INTO geocache VALUES (?,?)", (url, json.dumps(data)))
                db.commit()
            if data:
                hit, adr = data[0], data[0].get("address", {})
                return {"lat": round(float(hit["lat"]), 6), "lon": round(float(hit["lon"]), 6),
                        "zeme": (adr.get("country_code") or "").upper() or None,
                        "region": adr.get("state") or adr.get("region"),
                        "mesto": adr.get("city") or adr.get("town") or adr.get("village") or adr.get("municipality"),
                        "presnost": presnost, "zdroj": url}
    finally:
        db.close()
    return None


# ============================================================================
#  6. EXTRAKCE JEDNÉ URL  ->  záznam podle schématu (+ zdroj ke každému poli)
# ============================================================================
VZOR_LINEUP = re.compile(r"line-?up|program|artists|interpret|ucinkujic|kapely|bands|wykonawcy|kuenstler", re.I)
NE_LINEUP = re.compile(r"news|novinky|aktuality|aktualnosti|blog|kategorie|kategorien|archiv|archive|press|tickets|vstupenky", re.I)
SEGMENTY_INTERPRETU = {"artist", "artists", "artist-detail", "band", "bands", "interpret", "interpreti", "interpreter",
                       "umelec", "umelci", "ucinkujici", "ucinkujuci", "performer", "performers", "kapela", "kapely",
                       "wykonawca", "wykonawcy", "artysta", "artysci", "kuenstler", "kunstler", "act", "acts",
                       "lineup", "line-up", "program", "programme"}
NE_JMENA = re.compile(r"^(vice|viac|more|detail|detaily|info|vstupenky|tickets|listky|koupit|kupit|buy|zobrazit|"
                      r"show|all|vse|vsetko|line-?up|program|artists|interpreti|ucinkujici|back|zpet|spat|next|"
                      r"prev|dalsi|predchozi|read more|cist vice|citat viac|\d+)$")


def najdi_lineup_stranku(stranka, url: str, rok: int | None):
    """Najde na webu festivalu odkaz na podstránku s line-upem (stejná doména, ne staré ročníky, ne novinky)."""
    domena = urlparse(url).netloc.lower().removeprefix("www.")
    rok_min = rok or date.today().year
    nejlepsi, skore_max = None, 0
    for odkaz in stranka.odkazy:
        u = cista_url(odkaz, url)
        if not u or urlparse(u).netloc.lower().removeprefix("www.") != domena:
            continue
        cesta = urlparse(u).path.lower()
        if not VZOR_LINEUP.search(cesta) or NE_LINEUP.search(cesta) or u.rstrip("/") == url.rstrip("/"):
            continue
        roky = [int(r) for r in re.findall(r"20[2-3]\d", cesta)]
        if roky and max(roky) < rok_min:
            continue  # line-up starého ročníku
        skore = 10 - cesta.strip("/").count("/")  # kratší cesta = hlavní stránka line-upu
        if re.search(r"line-?up|ucinkujic|artists|interpreti|wykonawcy|kuenstler", cesta):
            skore += 5
        if roky:
            skore += 3
        if skore > skore_max:
            nejlepsi, skore_max = u, skore
    return nejlepsi


DNY = (r"pondeli|utery|streda|ctvrtek|patek|sobota|nedele|pondelok|utorok|stvrtok|piatok|nedela|"
       r"poniedzialek|wtorek|sroda|czwartek|piatek|niedziela|montag|dienstag|mittwoch|donnerstag|freitag|"
       r"samstag|sonntag|monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun")
DNY_ORIG = ("Pondělí|Úterý|Středa|Čtvrtek|Pátek|Sobota|Neděle|Pondelok|Utorok|Streda|Štvrtok|Piatok|Nedeľa|"
            "Poniedziałek|Wtorek|Środa|Czwartek|Piątek|Niedziela|Montag|Dienstag|Mittwoch|Donnerstag|Freitag|"
            "Samstag|Sonntag|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mon|Tue|Wed|Thu|Fri|Sat|Sun")
KATEGORIE_MENU = {"hudba", "divadlo", "tanec", "diskusie", "diskuse", "literatura", "workshopy", "workshops",
                  "film", "kino", "vizualne umenie", "vytvarne umeni", "sprievodny program", "doprovodny program",
                  "music", "theatre", "theater", "dance", "talks", "literature", "art", "kids", "deti", "family",
                  "all", "vse", "vsetko", "alle", "wszystko", "stages", "stage", "scena", "pódium", "podium"}


def _vycisti_jmeno(j: str) -> str:
    j = re.sub(r"\S+\.(jpe?g|png|webp|gif|svg)\b", " ", j, flags=re.I)            # názvy fotek
    j = re.sub(r"^(first time at \w+|special set|exclusive|new|novinka|nove|nove!|premiere)\s+", "", j, flags=re.I)
    j = re.sub(r"^(first time at \w+|special set)\s+", "", j, flags=re.I)
    j = re.sub(r"\s*(?:" + DNY_ORIG + r")\b[\s,]*\d{1,2}\.\s*\d{1,2}\.?(?:\s*20\d\d)?\s*$", "", j, flags=re.I)
    j = re.sub(r"\s*\b[A-Z]{2}(\s*/\s*[A-Z]{2})*\s*$", "", j)                       # „ US“, „ CA/US“
    j = re.sub(r"\s+20[2-3]\d$", "", j)                                              # „Massive Attack 2027“
    j = re.sub(r"\s*\blogo\b\s*$", "", j, flags=re.I)
    return re.sub(r"\s+", " ", j).strip(" -–|·,")


def _podobnost(a: str, b: str) -> float:
    import difflib
    a = re.sub(r"[^a-z0-9]", "", bez_diakritiky(a))
    b = re.sub(r"[^a-z0-9]", "", bez_diakritiky(b))
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return min(0.95, min(len(a), len(b)) / max(len(a), len(b)) + 0.3)
    return difflib.SequenceMatcher(None, a, b).ratio()


def jmena_z_odkazu(stranka, url: str) -> list[str]:
    """Bez LLM: jména interpretů z odkazů na jejich profily (…/artist/the-cure, …/interpret/kapela-x).

    Odkaz často obsahuje víc textu (země, den koncertu, žánr, štítky, popisek fotky). Jméno se vybere
    jako ta část textu, která se nejvíc podobá adrese profilu (…/artist/blink-182 → „blink-182“).
    """
    domena = urlparse(url).netloc.lower().removeprefix("www.")
    lineup_cesta = urlparse(url).path.rstrip("/")
    rodic = lineup_cesta.rsplit("/", 1)[0]
    rodic = rodic if len([c for c in rodic.split("/") if c]) >= 2 else None   # /sk/artists/2027 ano, /sk ne
    jmena, videno = [], set()
    for href, text, kusy in stranka.odkazy_text:
        u = cista_url(href, url)
        if not u or urlparse(u).netloc.lower().removeprefix("www.") != domena:
            continue
        cesta = urlparse(u).path.rstrip("/")
        if cesta == lineup_cesta or (rodic and cesta.startswith(rodic + "/")):
            continue  # sourozenecké stránky line-upu = menu kategorií (Hudba, Divadlo…)
        casti = [c for c in cesta.lower().split("/") if c]
        idx = next((i for i, c in enumerate(casti) if c in SEGMENTY_INTERPRETU), None)
        if idx is None or idx == len(casti) - 1:
            continue
        slug = casti[-1]
        if (re.fullmatch(r"\d+|page|strana|20[2-3]\d|[a-z]{2}", slug) or slug in SEGMENTY_INTERPRETU
                or bez_diakritiky(slug.replace("-", " ")) in KATEGORIE_MENU):
            continue
        slug_cisty = re.sub(r"^(\d+[-_])+", "", slug)                               # „74155-faith-no-more“
        slug_cisty = re.sub(r"[-_]+", " ", slug_cisty).strip()

        # 1) část textu nejpodobnější slugu
        kandidati = [_vycisti_jmeno(k) for k in kusy] + [_vycisti_jmeno(text)]
        kandidati = [k for k in kandidati if k and len(k) <= 80]
        jmeno, nejlepsi = None, 0.0
        slug_kompakt = re.sub(r"[^a-z0-9]", "", bez_diakritiky(slug_cisty))
        for k in list(kandidati):
            slova = k.split()
            for n in range(1, len(slova)):   # „CARCASS DEATH METAL“ + slug „carcass“ → „CARCASS“
                if re.sub(r"[^a-z0-9]", "", bez_diakritiky(" ".join(slova[:n]))) == slug_kompakt:
                    kandidati.append(" ".join(slova[:n]))
                    break
        for k in kandidati:
            p = _podobnost(k, slug_cisty)
            if p > nejlepsi:
                jmeno, nejlepsi = k, p
        if nejlepsi < 0.5:
            jmeno = _vycisti_jmeno(text) if text and len(text) <= 60 else None
        # 2) jinak jméno ze slugu
        if not jmeno:
            jmeno = _vycisti_jmeno(slug_cisty.title()) if slug_cisty else None  # „…-2027“ → bez roku
        if jmeno:
            slova = jmeno.split()
            pul = len(slova) // 2
            if len(slova) % 2 == 0 and pul and slova[:pul] == slova[pul:]:
                jmeno = " ".join(slova[:pul])
        if not jmeno or len(jmeno) < 2:
            continue
        klic = bez_diakritiky(jmeno)
        if NE_JMENA.match(klic) or klic in KATEGORIE_MENU or re.fullmatch(r"[a-z]{2}", klic):
            continue
        if klic not in videno:
            videno.add(klic)
            jmena.append(jmeno)
    return jmena[:300] if len(jmena) >= 5 else []  # méně než 5 = spíš navigace než line-up


def extrahuj(url: str, druh: str = "festival", napoveda: dict | None = None) -> dict:
    url = cista_url(url)
    if not url:
        raise ValueError("neplatná URL (povoleno jen http/https)")
    napoveda = napoveda or {}
    stazeno = ted()
    stranka = stahni(url)
    text = stranka.cely_text()
    s = schema_festival(stranka) if druh == "festival" else schema_venue(stranka)
    meta = {"schema_org": bool(s), "nenamapovane_zanry": []}

    # --- název
    nazev = cisty_text(s.get("nazev"), 150)
    if not nazev:
        nazev = cisty_text(stranka.nazev_z_titulku(url), 150)
        meta["nazev_z"] = "titulek_stranky"
    nazev = nazev or cisty_text(napoveda.get("name"), 150)

    # --- žánry: schema.org, jinak klíčová slova v textu
    tagy = s.get("zanry") or []
    if not tagy:
        tagy = zanry_z_textu(text)
        if tagy:
            meta["zanry_z"] = "klicova_slova"
    zanry, meta["nenamapovane_zanry"] = namapuj_zanry(tagy)

    zaznam = {
        "url": url, "url_key": klic_url(url), "name": nazev,
        "country": cista_zeme(s.get("zeme")) or cista_zeme(napoveda.get("country")),
        "city": cisty_text(s.get("mesto"), 100) or cisty_text(napoveda.get("city"), 100),
        "genres": zanry or None,
    }

    if druh == "festival":
        od, do = ciste_datum(s.get("od")), ciste_datum(s.get("do"))
        if od and do and do < od:
            od, do = do, od
        if not od:
            od, do = data_z_textu(text)
            if od:
                meta["datum_z"] = "text_stranky"
        interpreti = []
        for jmeno in s.get("interpreti", []):
            j = cisty_text(jmeno, 120)
            if j and j not in interpreti:
                interpreti.append(j)
        zaznam.update({
            "date_from": od, "date_to": do or od, "year": int(od[:4]) if od else None,
            "capacity": kategorie_kapacity(cele_cislo(s.get("kapacita"), 1, 2_000_000)),
            "event_status": s.get("stav"),
            "lineup": [{"year": int(od[:4]) if od else None, "artists": [{"name": j} for j in interpreti[:300]]}]
            if interpreti else None,
        })
        # line-up z podstránky – jen u oficiálních webů (u katalogů typu GoOut by šlo o cizí stránky)
        lineup_zdroj = None
        hloubka = len([c for c in urlparse(url).path.split("/") if c])
        if not interpreti and hloubka <= 1:
            sub = najdi_lineup_stranku(stranka, url, int(od[:4]) if od else None)
            if sub:
                meta["lineup_stranka"] = sub
                try:
                    lp = stahni(sub)
                    jmena = [cisty_text(j, 120) for j in schema_festival(lp).get("interpreti", [])]
                    jmena = [j for j in dict.fromkeys(jmena) if j] or jmena_z_odkazu(lp, sub)
                    if jmena:
                        zaznam["lineup"] = [{"year": int(od[:4]) if od else None,
                                             "artists": [{"name": j} for j in jmena[:300]]}]
                        lineup_zdroj = [{"url": sub, "fetched_at": ted()}]
                        meta["lineup_z"] = "podstranka"
                except Exception as e:
                    meta["lineup_chyba"] = str(e)[:200]
    else:
        zaznam.update({
            "venue_type": s.get("typ"),
            "capacity": cele_cislo(s.get("kapacita"), 1, 100_000),
            "booking_contact": obecny_kontakt(s.get("kontakt")),
            "ttl_days": TTL_VENUE_DNI,
        })

    # --- zdroj ke každému vyplněnému poli
    zdroje = {k: [{"url": url, "fetched_at": stazeno}] for k, v in zaznam.items()
              if v is not None and k not in ("url", "url_key", "ttl_days")}
    if druh == "festival" and lineup_zdroj:
        zdroje["lineup"] = lineup_zdroj

    # --- GPS: schema.org -> nápověda Průzkumníka (OSM) -> Nominatim
    gps = s.get("gps")
    if gps:
        zaznam["lat"], zaznam["lon"] = gps
        zdroje["gps"] = [{"url": url, "fetched_at": stazeno}]
        meta["gps_presnost"] = "schema_org"
    elif isinstance(napoveda.get("lat"), (int, float)) and isinstance(napoveda.get("lon"), (int, float)):
        zaznam["lat"], zaznam["lon"] = napoveda["lat"], napoveda["lon"]
        zdroje["gps"] = [{"url": cista_url(napoveda.get("source_url")) or url, "fetched_at": stazeno}]
        meta["gps_presnost"] = "napoveda"
    elif KONTAKT_EMAIL and (zaznam["city"] or s.get("adresa")):
        try:
            g = geokoduj(cisty_text(s.get("adresa")), cisty_text(s.get("misto_nazev")) or (nazev if druh == "venue" else None),
                         zaznam["city"], zaznam["country"])
        except Exception as e:
            g, meta["gps_chyba"] = None, str(e)[:200]
        if g:
            zaznam["lat"], zaznam["lon"], zaznam["region"] = g["lat"], g["lon"], cisty_text(g["region"], 100)
            zdroje["gps"] = [{"url": g["zdroj"], "fetched_at": ted()}]
            if not zaznam["city"] and g.get("mesto"):
                zaznam["city"] = cisty_text(g["mesto"], 100)
                zdroje["city"] = zdroje["gps"]
                meta["mesto_z"] = "geokoder"
            meta["gps_presnost"] = g["presnost"]
            if not zaznam["country"] and g["zeme"]:
                zaznam["country"] = g["zeme"]
                zdroje["country"] = zdroje["gps"]
            elif zaznam["country"] and g["zeme"] and g["zeme"] != zaznam["country"]:
                meta["rozpor_zeme"] = {"stranka": zaznam["country"], "geokoder": g["zeme"]}

    if not zaznam["country"]:
        z = zeme_z_domeny(url)
        if z:
            zaznam["country"] = z
            zdroje["country"] = [{"url": url, "fetched_at": stazeno}]
            meta["zeme_z"] = "domena"

    if POVOLENE_ZEME and zaznam["country"] and zaznam["country"] not in POVOLENE_ZEME:
        raise ValueError(f"festival je mimo povolené země ({zaznam['country']}) – neukládám")

    if not zaznam["name"]:
        raise ValueError("na stránce se nenašel název – asi to není stránka festivalu/venue")

    zaznam.update({"sources": zdroje, "extraction_meta": meta, "last_checked": ted(),
                   "record_status": "pending_validation", "confidence": None})
    return zaznam


# ============================================================================
#  7. DATABÁZE (návrh – finální schéma zamyká integrátor; měnit jen tuto část)
# ============================================================================
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL, priority INTEGER NOT NULL DEFAULT 1,
    params TEXT NOT NULL DEFAULT '{}', created_by TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0, result TEXT, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS festivals (
    id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT NOT NULL, url_key TEXT NOT NULL UNIQUE, name TEXT,
    country TEXT, city TEXT, region TEXT, lat REAL, lon REAL, date_from TEXT, date_to TEXT, edition INTEGER,
    year INTEGER, genres TEXT, capacity TEXT, lineup TEXT, open_call TEXT, event_status TEXT, sources TEXT,
    extraction_meta TEXT, last_checked TEXT, confidence REAL,
    record_status TEXT NOT NULL DEFAULT 'pending_validation', returned_count INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS venues (
    id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT NOT NULL, url_key TEXT NOT NULL UNIQUE, name TEXT,
    venue_type TEXT, country TEXT, region TEXT, nuts TEXT, city TEXT, lat REAL, lon REAL, capacity INTEGER,
    genres TEXT, band_size TEXT, call_for_bands TEXT, booking_contact TEXT, sources TEXT, extraction_meta TEXT,
    last_checked TEXT, ttl_days INTEGER, confidence REAL,
    record_status TEXT NOT NULL DEFAULT 'pending_validation', returned_count INTEGER NOT NULL DEFAULT 0);
"""
JSON_SLOUPCE = {"genres", "lineup", "open_call", "sources", "extraction_meta", "call_for_bands"}


def pripoj_db(cesta=DATABAZE):
    conn = sqlite3.connect(cesta, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(SCHEMA_SQL)
    # Tabulku tasks může založit i jiný agent (např. Průzkumník) s menším počtem sloupců → doplnit chybějící.
    sloupce = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
    for nazev, typ in (("priority", "INTEGER DEFAULT 1"), ("params", "TEXT DEFAULT '{}'"),
                       ("created_by", "TEXT"), ("status", "TEXT DEFAULT 'pending'"),
                       ("attempts", "INTEGER DEFAULT 0"), ("result", "TEXT"),
                       ("created_at", "TEXT"), ("updated_at", "TEXT")):
        if nazev not in sloupce:
            conn.execute(f"ALTER TABLE tasks ADD COLUMN {nazev} {typ}")
    return conn


def uloz(conn, zaznam: dict, druh: str, vraceno_validatorem=False, poznamka=None) -> int:
    tabulka = "festivals" if druh == "festival" else "venues"
    stary = conn.execute(f"SELECT * FROM {tabulka} WHERE url_key=?", (zaznam["url_key"],)).fetchone()
    if stary:
        stary = dict(stary)
        zdroje = json.loads(stary["sources"] or "{}")
        zdroje.update(zaznam["sources"])
        zaznam["sources"] = zdroje
        for k, v in list(zaznam.items()):          # prázdné nové hodnoty nepřepíšou staré
            if v is None and stary.get(k) is not None and k not in ("confidence",):
                zaznam[k] = json.loads(stary[k]) if k in JSON_SLOUPCE else stary[k]
        zaznam["returned_count"] = (stary["returned_count"] or 0) + (1 if vraceno_validatorem else 0)
    else:
        zaznam["returned_count"] = 1 if vraceno_validatorem else 0
    if poznamka:
        zaznam["extraction_meta"]["poznamka_validatora"] = cisty_text(poznamka, 500)
    sloupce = list(zaznam)
    hodnoty = [json.dumps(zaznam[c], ensure_ascii=False) if c in JSON_SLOUPCE and zaznam[c] is not None
               else zaznam[c] for c in sloupce]
    conn.execute(
        f"INSERT INTO {tabulka} ({','.join(sloupce)}) VALUES ({','.join('?' * len(sloupce))}) "
        f"ON CONFLICT(url_key) DO UPDATE SET {','.join(f'{c}=excluded.{c}' for c in sloupce if c != 'url_key')}",
        hodnoty)
    return conn.execute(f"SELECT id FROM {tabulka} WHERE url_key=?", (zaznam["url_key"],)).fetchone()[0]


def pridej_ukol(conn, typ, params, zadal, priorita=1):
    conn.execute("INSERT INTO tasks(type, priority, params, created_by, created_at) VALUES (?,?,?,?,?)",
                 (typ, priorita, json.dumps(params, ensure_ascii=False), zadal, ted()))


def vezmi_ukol(conn):
    conn.execute("BEGIN IMMEDIATE")
    try:
        u = conn.execute("SELECT * FROM tasks WHERE status='pending' AND type='extract' "
                         "ORDER BY COALESCE(priority, 1) DESC, COALESCE(created_at, ''), id LIMIT 1").fetchone()
        if u:
            conn.execute("UPDATE tasks SET status='in_progress', attempts=COALESCE(attempts, 0)+1, updated_at=? WHERE id=?",
                         (ted(), u["id"]))
        conn.execute("COMMIT")
        return u
    except Exception:
        conn.execute("ROLLBACK")
        raise


def dokonci_ukol(conn, id_, stav, vysledek):
    conn.execute("UPDATE tasks SET status=?, result=?, updated_at=? WHERE id=?",
                 (stav, json.dumps(vysledek, ensure_ascii=False), ted(), id_))


# ============================================================================
#  8. BĚH
# ============================================================================
def zpracuj_url(conn, url, druh="festival", napoveda=None, vraceno=False, poznamka=None, priorita=1):
    z = extrahuj(url, druh, napoveda)
    id_ = uloz(conn, z, druh, vraceno, poznamka)
    pridej_ukol(conn, "validate", {"table": "festivals" if druh == "festival" else "venues", "record_id": id_},
                "extraktor", priorita)
    vyplneno = [k for k in ("name", "country", "city", "lat", "date_from", "genres", "lineup", "event_status",
                            "capacity", "venue_type", "booking_contact") if z.get(k)]
    print(f"  ✔ {z['name']}  (id {id_}) – vyplněno: {', '.join(vyplneno)}")
    return z


def zpracuj_frontu(conn, limit=MAX_STRANEK_NA_BEH):
    hotovo = 0
    while hotovo < limit:
        u = vezmi_ukol(conn)
        if not u:
            break
        p = json.loads(u["params"] or "{}")
        try:
            zpracuj_url(conn, p.get("url", ""), p.get("kind", "festival"), p.get("hint"),
                        u["created_by"] == "validator", p.get("validator_note"), u["priority"] or 1)
            dokonci_ukol(conn, u["id"], "done", {"ok": True})
        except Exception as e:
            stav = "failed" if (u["attempts"] or 0) + 1 >= 2 else "pending"
            dokonci_ukol(conn, u["id"], stav, {"error": str(e)[:300]})
            print(f"  ✘ úkol #{u['id']} {p.get('url')}: {e}")
        hotovo += 1
    print(f"Zpracováno úkolů: {hotovo}")


def export_json(conn, soubor):
    radky = []
    for r in conn.execute("SELECT * FROM festivals"):
        d = dict(r)
        for k in JSON_SLOUPCE & d.keys():
            d[k] = json.loads(d[k]) if d[k] else None
        radky.append(d)
    with open(soubor, "w", encoding="utf-8") as f:
        json.dump(radky, f, ensure_ascii=False, indent=2)
    print(f"Exportováno {len(radky)} festivalů do {soubor}")


# ---- export ve formátu webu (repo festivaly-mas, data/festivals.json) ---------------
ZANRY_WEB = {"rock": "rock", "pop": "pop", "indie": "indie-alternative", "alternative": "indie-alternative",
             "metal": "metal", "punk": "punk-hardcore", "electronic": "electronic", "hiphop": "hip-hop",
             "jazz": "jazz-blues", "blues": "jazz-blues", "folk": "folk-acoustic", "singer_songwriter": "folk-acoustic",
             "country": "folk-acoustic", "world": "world", "classical": "classical", "reggae_ska": "reggae-ska",
             "experimental": "experimental", "multi": "multi-genre", "rnb_soul": "pop"}
ZEME_WEB = {"CZ": "Czech Republic", "SK": "Slovakia", "PL": "Poland", "AT": "Austria", "DE": "Germany",
            "HU": "Hungary", "SI": "Slovenia", "HR": "Croatia", "CH": "Switzerland"}
STAV_WEB = {"potvrzeno": "confirmed", "ohlášeno": "announced", "zrušeno": "cancelled"}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", bez_diakritiky(text or "")).strip("-")


def export_web(conn, soubor, zlucit_s=None, include_provenance=False):
    """Export pro web: stejný tvar jako data/festivals.json v repozitáři festivaly-mas (+ navíc lineup a GPS)."""
    dnes = date.today()
    rok_odhad = dnes.year + 1 if dnes.month >= 9 else dnes.year
    vystup, videno = [], set()
    for r in conn.execute("SELECT * FROM festivals ORDER BY name"):
        d = dict(r)
        if POVOLENE_ZEME and d["country"] and d["country"] not in POVOLENE_ZEME:
            continue
        for k in JSON_SLOUPCE & d.keys():
            d[k] = json.loads(d[k]) if d[k] else None
        zeme = ZEME_WEB.get(d["country"] or "", d["country"] or "")
        mesto = d["city"] or ""
        id_ = "-".join(x for x in [(d["country"] or "").lower(), _slug(d["name"]), _slug(mesto)] if x)
        while id_ in videno:
            id_ += "-" + str(d["id"])
        videno.add(id_)
        oc = d.get("open_call") or {}
        zdroj = ((d.get("sources") or {}).get("name") or [{}])[0].get("url") or d["url"]
        vystup.append({
            "id": id_,
            "name": d["name"],
            "type": "festival",
            "genres": sorted({ZANRY_WEB[g] for g in (d["genres"] or []) if g in ZANRY_WEB}),
            "country": zeme,
            "city": mesto,
            "edition_year": d["year"] or (int(d["date_from"][:4]) if d["date_from"] else rok_odhad),
            "date_from": d["date_from"],
            "date_to": d["date_to"],
            "status": STAV_WEB.get(d["event_status"] or "", "announced"),
            "open_call": bool(oc.get("otevreno")),
            "open_call_url": oc.get("url"),
            "website": d["url"],
            "source_url": zdroj,
            # navíc oproti současnému webu (web je zatím ignoruje):
            "lineup": [a["name"] for blok in (d["lineup"] or []) for a in blok.get("artists", [])],
            "lat": d["lat"], "lon": d["lon"],
            "record_status": d["record_status"],
        })
        if include_provenance:
            vystup[-1].update(
                source_entries=d.get("sources"),
                lineup_by_edition=d.get("lineup"),
                capacity_label=d.get("capacity"),
                checked_at=d.get("last_checked"),
                observed_edition=bool(d.get("year") or d.get("date_from")),
                observed_status=bool(d.get("event_status")),
                observed_open_call=bool(d.get("open_call")),
            )
    if zlucit_s:
        vystup = _zluc(zlucit_s, vystup)
    with open(soubor, "w", encoding="utf-8") as f:
        json.dump({"generated": dnes.isoformat(), "count": len(vystup), "festivals": vystup},
                  f, ensure_ascii=False, indent=2)
    print(f"Exportováno {len(vystup)} festivalů pro web do {soubor}")


def _zluc(puvodni_soubor, nove):
    """Zachová všechny záznamy z existujícího festivals.json. Shodné festivaly (stejné id nebo stejný web)
    jen doplní – existující hodnoty nepřepisuje. Nové festivaly přidá na konec."""
    with open(puvodni_soubor, encoding="utf-8") as f:
        puvodni = json.load(f)["festivals"]
    podle_id = {r["id"]: r for r in puvodni}
    od_nejnovejsiho = sorted(puvodni, key=lambda r: r.get("edition_year") or 0, reverse=True)
    def domena(u):
        return urlparse(u or "").netloc.lower().removeprefix("www.")

    def jmeno(t):
        t = re.sub(r"\b(20[2-3]\d|festival|fest|open air|music)\b", " ", bez_diakritiky(t or ""))
        return re.sub(r"[^a-z0-9]", "", t)

    KATALOGY = {"goout.net", "festivalhopper.de", "festivaly.eu", "park360.cz", "ticketmaster.cz", "ticketportal.cz"}
    podle_webu, podle_jmena = {}, {}
    for r in od_nejnovejsiho:   # u více ročníků téhož festivalu doplňujeme ten nejnovější
        if r.get("website") and domena(r["website"]) not in KATALOGY:
            podle_webu.setdefault(domena(r["website"]), r)
        podle_jmena.setdefault((jmeno(r["name"]), r.get("country")), r)
    doplneno = pridano = 0
    for n in nove:
        r = (podle_id.get(n["id"])
             or (podle_webu.get(domena(n["website"])) if domena(n["website"]) not in KATALOGY else None)
             or podle_jmena.get((jmeno(n["name"]), n.get("country"))))
        if r is None:
            puvodni.append(n)
            podle_id[n["id"]] = n
            podle_jmena.setdefault((jmeno(n["name"]), n.get("country")), n)
            pridano += 1
            continue
        for k, v in n.items():
            if k in ("id", "status", "edition_year", "type"):
                continue  # identitu a stav nechat podle původního datasetu
            if v not in (None, "", [], False) and r.get(k) in (None, "", [], False):
                r[k] = v
        doplneno += 1
    print(f"Sloučeno s {puvodni_soubor}: doplněno {doplneno}, přidáno {pridano}, celkem {len(puvodni)}")
    return puvodni


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Agent 2 · Extraktor (zdarma, bez instalace)")
    ap.add_argument("urls", nargs="*", help="URL festivalů / venues")
    ap.add_argument("--venue", action="store_true", help="URL jsou kluby / venues")
    ap.add_argument("--soubor", help="textový soubor s URL (jedna na řádek)")
    ap.add_argument("--fronta", action="store_true", help="zpracuj úkoly 'extract' z fronty v DB")
    ap.add_argument("--export", metavar="SOUBOR.json", help="export festivalů do JSON (pro mapu)")
    ap.add_argument("--export-web", metavar="SOUBOR.json", help="export ve formátu webu (data/festivals.json)")
    ap.add_argument("--zlucit-s", metavar="FESTIVALS.json", help="při --export-web zachovat a doplnit existující dataset webu")
    ap.add_argument("--zanry", action="store_true", help="vypiš číselník žánrů")
    ap.add_argument("--ukaz", action="store_true", help="vypiš celý extrahovaný záznam")
    a = ap.parse_args()

    if a.zanry:
        print("| Kód | Žánr | Typické tagy |\n|---|---|---|")
        for kod, (nazev, syn) in ZANRY.items():
            print(f"| `{kod}` | {nazev} | {', '.join(syn[:8])} |")
        return
    if "doplnit@" in KONTAKT_EMAIL:
        print("⚠  Doplň svůj e-mail do KONTAKT_EMAIL na začátku souboru (vyžaduje to Nominatim).\n")

    conn = pripoj_db()
    if a.fronta:
        zpracuj_frontu(conn)
    urls = list(a.urls)
    if a.soubor:
        with open(a.soubor, encoding="utf-8") as f:
            urls += [r.strip() for r in f if r.strip() and not r.startswith("#")]
    druh = "venue" if a.venue else "festival"
    for url in urls[:MAX_STRANEK_NA_BEH]:
        print(f"→ {url}")
        try:
            z = zpracuj_url(conn, url, druh)
            if a.ukaz:
                print(json.dumps(z, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"  ✘ {e}")
    if a.export:
        export_json(conn, a.export)
    if a.export_web:
        export_web(conn, a.export_web, a.zlucit_s)
    if not (urls or a.fronta or a.export or a.export_web):
        ap.print_help()


if __name__ == "__main__":
    main()
