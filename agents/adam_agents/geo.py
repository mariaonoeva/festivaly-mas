"""Kontroly GPS: rozsah, Evropa, příslušnost k zemi (hrubý bounding box)."""
from __future__ import annotations

import math

EUROPE_BBOX = (34.0, 72.0, -25.0, 45.0)  # min_lat, max_lat, min_lon, max_lon

# Přibližné bounding boxy zemí (min_lat, max_lat, min_lon, max_lon).
# Pro zemi mimo tabulku se kontroluje jen Evropa.
COUNTRY_BBOX: dict[str, tuple[float, float, float, float]] = {
    "CZ": (48.55, 51.06, 12.09, 18.86),
    "SK": (47.73, 49.61, 16.83, 22.57),
    "PL": (49.00, 54.84, 14.12, 24.15),
    "AT": (46.37, 49.02, 9.53, 17.16),
    "DE": (47.27, 55.06, 5.87, 15.04),
    "HU": (45.74, 48.59, 16.11, 22.90),
    "SI": (45.42, 46.88, 13.38, 16.61),
    "HR": (42.39, 46.56, 13.49, 19.45),
    "RS": (42.23, 46.19, 18.82, 23.01),
    "BA": (42.56, 45.28, 15.73, 19.62),
    "ME": (41.85, 43.56, 18.43, 20.36),
    "MK": (40.85, 42.37, 20.45, 23.04),
    "AL": (39.64, 42.66, 19.26, 21.06),
    "NL": (50.75, 53.56, 3.36, 7.23),
    "BE": (49.50, 51.51, 2.54, 6.41),
    "FR": (41.33, 51.12, -5.14, 9.56),
    "IT": (35.49, 47.09, 6.63, 18.52),
    "ES": (35.95, 43.79, -9.39, 4.33),
    "GB": (49.86, 60.86, -8.65, 1.77),
    "DK": (54.56, 57.75, 8.07, 15.20),
    "CH": (45.82, 47.81, 5.96, 10.49),
}
MARGIN = 0.15  # stupně, tolerance na hranicích


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _in_box(lat, lon, box, margin=0.0) -> bool:
    return (box[0] - margin <= lat <= box[1] + margin) and (box[2] - margin <= lon <= box[3] + margin)


def check_gps(lat, lon, country: str | None) -> tuple[list[str], list[str]]:
    """Vrátí (chyby, varování)."""
    errors, warnings = [], []
    if lat is None or lon is None:
        warnings.append("gps_missing")
        return errors, warnings
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return ["gps_not_numeric"], warnings
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return ["gps_out_of_range"], warnings
    if abs(lat) < 0.01 and abs(lon) < 0.01:
        return ["gps_null_island"], warnings
    if not _in_box(lat, lon, EUROPE_BBOX):
        # častá chyba geokódování: prohozené lat/lon
        if _in_box(lon, lat, EUROPE_BBOX):
            return ["gps_swapped_lat_lon"], warnings
        return ["gps_outside_europe"], warnings
    box = COUNTRY_BBOX.get((country or "").upper())
    if box and not _in_box(lat, lon, box, MARGIN):
        errors.append("gps_not_in_country")
    return errors, warnings
