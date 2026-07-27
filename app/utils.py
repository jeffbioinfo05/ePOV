"""
utils.py — ePOV
Shared utilities: HTTP with retry, haversine distance,
coordinate validation, deduplication logic.
"""
from __future__ import annotations

import hashlib
import logging
import math
import time
from typing import Optional

import requests

from app.config import (
    BRAZIL_BBOX, COORD_BLACKLIST, BLACKLIST_RADIUS_M,
    DEDUP_RADIUS_M, DEDUP_SAME_YEAR, FATAL_GBIF_ISSUES,
    CULTIVATED_VALUES,
)

log = logging.getLogger(__name__)


# ── HTTP ──────────────────────────────────────────────────────────────────────

def get_json(url: str, params: dict = None, headers: dict = None,
             retries: int = 4, backoff: float = 2.0,
             timeout: int = 30) -> Optional[dict | list]:
    """Resilient GET with exponential backoff."""
    h = {"User-Agent": "ePOV/1.0 (epov-plant-occurrence@github)"}
    if headers:
        h.update(headers)
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=h, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                wait = backoff * (2 ** attempt)
                log.debug("Rate limited — waiting %.0f s", wait)
                time.sleep(wait)
            elif r.status_code == 404:
                return None
            elif r.status_code == 403:
                log.warning("403 Forbidden for %s — check credentials/token", url[:80])
                return None
            else:
                log.debug("HTTP %d for %s", r.status_code, url[:80])
                time.sleep(backoff)
        except requests.exceptions.Timeout:
            log.debug("Timeout on attempt %d for %s", attempt + 1, url[:60])
            time.sleep(backoff * (attempt + 1))
        except Exception as e:
            log.debug("Request error: %s", e)
            time.sleep(backoff)
    log.warning("All %d attempts failed for %s", retries, url[:80])
    return None


def post_json(url: str, payload: dict, headers: dict = None,
              retries: int = 3, backoff: float = 2.0,
              timeout: int = 30) -> Optional[dict | list]:
    """Resilient POST."""
    h = {"User-Agent": "ePOV/1.0", "Content-Type": "application/json"}
    if headers:
        h.update(headers)
    for attempt in range(retries):
        try:
            r = requests.post(url, json=payload, headers=h, timeout=timeout)
            if r.status_code in (200, 201):
                return r.json()
            if r.status_code == 429:
                time.sleep(backoff * (2 ** attempt))
            else:
                time.sleep(backoff)
        except Exception as e:
            log.debug("POST error: %s", e)
            time.sleep(backoff)
    return None


# ── Coordinate validation ─────────────────────────────────────────────────────

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in metres between two WGS-84 points."""
    R = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl   = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def in_brazil_bbox(lat: float, lon: float) -> bool:
    return (BRAZIL_BBOX["min_lat"] <= lat <= BRAZIL_BBOX["max_lat"] and
            BRAZIL_BBOX["min_lon"] <= lon <= BRAZIL_BBOX["max_lon"])


def is_blacklisted_coord(lat: float, lon: float) -> bool:
    for blon, blat in COORD_BLACKLIST:
        if haversine_m(lat, lon, blat, blon) <= BLACKLIST_RADIUS_M:
            return True
    return False


def is_integer_coord(lat: float, lon: float) -> bool:
    """Both lat and lon are whole-number values — likely a centroid artifact."""
    return (abs(lat - round(lat)) < 0.001 and
            abs(lon - round(lon)) < 0.001)


def coord_is_valid(lat: float, lon: float) -> tuple[bool, str]:
    """
    Full coordinate validity check.
    Returns (is_valid, reason_if_invalid).
    """
    if lat is None or lon is None:
        return False, "missing_coordinate"
    try:
        lat, lon = float(lat), float(lon)
    except (ValueError, TypeError):
        return False, "non_numeric_coordinate"
    if lat == 0.0 and lon == 0.0:
        return False, "zero_coordinate"
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return False, "out_of_range"
    if not in_brazil_bbox(lat, lon):
        return False, "outside_brazil_bbox"
    if is_blacklisted_coord(lat, lon):
        return False, "blacklisted_centroid"
    if is_integer_coord(lat, lon):
        return False, "integer_coord_artifact"
    return True, ""


# ── Record validation ─────────────────────────────────────────────────────────

def is_cultivated(record: dict) -> bool:
    """Return True if any field indicates the record is cultivated/not wild."""
    for field in ("establishmentMeans", "degreeOfEstablishment",
                  "occurrenceRemarks", "habitat"):
        val = str(record.get(field, "")).strip()
        if val in CULTIVATED_VALUES:
            return True
        if "cultivat" in val.lower() or "cultiva" in val.lower():
            return True
    return False


def has_fatal_gbif_issue(issues: list[str]) -> bool:
    return bool(set(issues) & FATAL_GBIF_ISSUES)


# ── Deduplication ─────────────────────────────────────────────────────────────

def make_point_key(accepted_name: str, lat: float, lon: float,
                   year: Optional[int]) -> str:
    """
    Deterministic key for deduplication.
    Rounds coordinates to ~10 m precision (4 decimal places ≈ 11 m).
    """
    lat_r = round(float(lat), 4)
    lon_r = round(float(lon), 4)
    yr    = str(year) if year else "unknown"
    raw   = f"{accepted_name}|{lat_r}|{lon_r}|{yr}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def deduplicate_records(records: list[dict]) -> list[dict]:
    """
    Mark duplicates across records from different source banks.

    Two records are duplicates if:
      - Same accepted_name (normalised, lowercase)
      - Distance between coordinates ≤ DEDUP_RADIUS_M (100 m)
      - Same year of collection (or both missing year)

    Strategy:
      - Sort by source priority: Flora_Funga > SpeciesLink > GBIF
        (most curated first)
      - First occurrence of a point is the canonical record
        (is_duplicate=False)
      - Subsequent occurrences at the same point are marked as duplicates
        and reference the canonical record_id

    Returns the same list with 'is_duplicate' and 'duplicate_of' fields set.
    """
    SOURCE_PRIORITY = {"Flora_Funga": 0, "SpeciesLink": 1, "GBIF": 2}

    # Sort: most curated source first, then oldest year (original collection)
    records.sort(key=lambda r: (
        SOURCE_PRIORITY.get(r.get("source_bank", "GBIF"), 9),
        r.get("year") or 9999,
    ))

    # Spatial index: accepted_name → list of (lat, lon, year, record_id)
    seen: dict[str, list[tuple]] = {}
    canonical: dict[str, str] = {}  # point_key → canonical record_id

    for rec in records:
        aname = (rec.get("accepted_name") or rec.get("species_name", "")).lower().strip()
        lat   = rec.get("latitude")
        lon   = rec.get("longitude")
        year  = rec.get("year")
        rid   = rec["record_id"]

        rec["is_duplicate"]  = False
        rec["duplicate_of"]  = None

        if lat is None or lon is None:
            continue

        lat, lon = float(lat), float(lon)
        found_dup = False

        for prev_lat, prev_lon, prev_year, prev_rid in seen.get(aname, []):
            dist = haversine_m(lat, lon, prev_lat, prev_lon)
            year_match = (not DEDUP_SAME_YEAR or
                          year is None or prev_year is None or
                          year == prev_year)
            if dist <= DEDUP_RADIUS_M and year_match:
                rec["is_duplicate"] = True
                rec["duplicate_of"] = prev_rid
                found_dup = True
                break

        if not found_dup:
            if aname not in seen:
                seen[aname] = []
            seen[aname].append((lat, lon, year, rid))

    return records


def compute_species_counts(records: list[dict]) -> dict[str, dict]:
    """
    Per accepted_name: count unique (non-duplicate) records per source bank.
    Returns dict: accepted_name → {flora_funga_n, specieslink_n, gbif_n,
                                    total_unique_points}
    """
    counts: dict[str, dict] = {}
    for rec in records:
        aname = (rec.get("accepted_name") or rec.get("species_name", "")).strip()
        if not aname:
            continue
        if aname not in counts:
            counts[aname] = {
                "flora_funga_n":    0,
                "specieslink_n":    0,
                "gbif_n":           0,
                "total_unique_points": 0,
            }
        if rec.get("is_duplicate"):
            continue
        src = rec.get("source_bank", "")
        if src == "Flora_Funga":
            counts[aname]["flora_funga_n"] += 1
        elif src == "SpeciesLink":
            counts[aname]["specieslink_n"] += 1
        elif src == "GBIF":
            counts[aname]["gbif_n"] += 1
        counts[aname]["total_unique_points"] += 1

    return counts
