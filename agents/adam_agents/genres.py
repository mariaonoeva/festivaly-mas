"""Normalizovaný číselník žánrů. Kódy odpovídají datasetu od Extraktoru
(15 kódů). Validátor převádí synonyma a hlásí žánry, které nezná."""
from __future__ import annotations

import unicodedata

# kód -> synonyma (malými písmeny, bez diakritiky)
GENRES: dict[str, list[str]] = {
    "rock": ["rock", "hard rock", "classic rock", "rock'n'roll", "rock and roll", "stoner",
             "bigbit", "big beat"],
    "metal": ["metal", "heavy metal", "black metal", "death metal", "thrash", "doom", "metalcore",
              "grindcore"],
    "punk-hardcore": ["punk", "hardcore", "post-punk", "post punk", "ska punk", "oi", "crust",
                      "punk hardcore"],
    "indie-alternative": ["indie", "alternative", "alternativa", "alt", "indie rock", "indie pop",
                          "shoegaze", "post-rock", "post rock", "garage", "indie alternative"],
    "pop": ["pop", "pop music", "schlager", "dance pop", "synthpop", "synth-pop"],
    "electronic": ["electronic", "electronica", "elektronika", "edm", "dance", "bass music",
                   "dubstep", "trance", "psytrance", "ambient", "downtempo", "drum and bass",
                   "drum & bass", "drum'n'bass", "dnb", "jungle"],
    "techno-house": ["techno", "house", "tech house", "deep house", "minimal", "hard techno",
                     "melodic house", "disco", "techno house"],
    "hip-hop": ["hip-hop", "hip hop", "hiphop", "rap", "trap", "grime"],
    "jazz-blues": ["jazz", "blues", "free jazz", "swing", "fusion", "soul", "funk", "r&b", "rnb",
                   "gospel", "jazz blues"],
    "classical": ["classical", "klasika", "klasicka hudba", "opera", "baroque", "early music",
                  "chamber", "choral", "contemporary classical", "stara hudba"],
    "folk-acoustic": ["folk", "acoustic", "country", "bluegrass", "singer-songwriter", "songwriter",
                      "chanson", "folklore", "folklor", "traditional", "trampska", "folk acoustic"],
    "world": ["world", "world music", "ethno", "etno", "balkan", "celtic", "latin", "brass",
              "tamburica", "klapa"],
    "reggae-ska": ["reggae", "ska", "dub", "dancehall", "reggae ska"],
    "experimental": ["experimental", "noise", "improv", "improvisation", "avant-garde",
                     "contemporary", "sound art"],
    "multi-genre": ["multi-genre", "multigenre", "multi genre", "various", "mixed", "vicezanrovy"],
}

_LOOKUP: dict[str, str] = {}
for code, syns in GENRES.items():
    _LOOKUP[code] = code
    _LOOKUP[code.replace("-", " ")] = code
    for s in syns:
        _LOOKUP[s] = code


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.lower().replace("_", " ").split())


def normalize_genres(raw: list[str] | str | None) -> tuple[list[str], list[str]]:
    """Vrátí (normalizované kódy, neznámé vstupy)."""
    if raw is None:
        return [], []
    if isinstance(raw, str):
        raw = [p for p in raw.replace(";", ",").replace("/", ",").split(",")]
    codes: list[str] = []
    unknown: list[str] = []
    for item in raw:
        p = _plain(str(item))
        if not p:
            continue
        code = _LOOKUP.get(p) or _LOOKUP.get(p.replace("-", " "))
        if not code:
            # nejdelší známé synonymum obsažené v textu ("melodic death metal" -> metal)
            hits = [s for s in _LOOKUP if len(s) > 2 and f" {s} " in f" {p} "]
            if hits:
                code = _LOOKUP[max(hits, key=len)]
        if code:
            if code not in codes:
                codes.append(code)
        else:
            unknown.append(str(item))
    return codes, unknown
