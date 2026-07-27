"""
gbif_client.py — ePOV
GBIF occurrence client for Brazilian plants.

Fetches records for target plant groups (Angiospermas, Gimnospermas,
Pteridófitas, Briófitas) in Brazil with aggressive curation filters.

Note: Records published by JBRJ (Herbário Virtual REFLORA) are fetched
separately by flora_funga.py and tagged as source='Flora_Funga'.
This module fetches all OTHER GBIF publishers, so the columns are additive
and not double-counted at the source level.

Curation filters applied at request level
------------------------------------------
  country          = BR
  hasCoordinate    = true
  hasGeospatialIssue = false
  occurrenceStatus = PRESENT
  basisOfRecord    = PRESERVED_SPECIMEN | HUMAN_OBSERVATION | MACHINE_OBSERVATION

Additional filters applied post-download
-----------------------------------------
  - Fatal GBIF issues (ZERO_COORDINATE, COUNTRY_COORDINATE_MISMATCH, etc.)
  - Cultivated / managed (establishmentMeans)
  - Coordinate outside Brazil bbox
  - Blacklisted institution centroids
  - Integer coordinates (centroid artifacts)
  - coordinateUncertaintyInMeters > 10,000 m (flagged, not discarded)
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Optional

from app.config import (
    GBIF_BASE, GBIF_CLASS_KEYS, GROUP_LABEL, CACHE_DIR,
    FATAL_GBIF_ISSUES,
)
from app.utils import get_json, coord_is_valid, is_cultivated, has_fatal_gbif_issue

log = logging.getLogger(__name__)

# JBRJ publisher key — exclude so records aren't double-counted with Flora_Funga
JBRJ_PUBLISHER_KEY = "4b3e4a58-5b60-4e20-bc04-fbb6c0b6a769"


# ── Main fetch ────────────────────────────────────────────────────────────────

def fetch_occurrences(species_names: list[str],
                      force: bool = False) -> list[dict]:
    """
    Fetch curated GBIF occurrence records for all target species in Brazil.

    Skips records from JBRJ publisher (those come via flora_funga.py).
    Returns list of normalised occurrence dicts.
    Cached to data/cache/gbif_occurrences.json.
    """
    cache = CACHE_DIR / "gbif_occurrences.json"
    if cache.exists() and not force:
        log.info("GBIF: loading occurrences from cache")
        return json.loads(cache.read_text(encoding="utf-8"))

    log.info("GBIF: fetching occurrences for %d species…", len(species_names))
    all_records = []

    for i, sp_name in enumerate(species_names):
        records = _fetch_species(sp_name)
        all_records.extend(records)

        if (i + 1) % 200 == 0:
            log.info("  GBIF: %d/%d species, %d records so far",
                     i + 1, len(species_names), len(all_records))
        time.sleep(0.15)

    log.info("GBIF: %d total records fetched", len(all_records))
    cache.write_text(json.dumps(all_records, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    return all_records


def fetch_occurrences_by_group(force: bool = False) -> list[dict]:
    """
    Alternative: fetch all plant occurrences in Brazil by class key
    (without a species name list). Faster for initial full download.
    Use this when building the index from scratch.
    Cached to data/cache/gbif_occurrences.json.
    """
    cache = CACHE_DIR / "gbif_occurrences.json"
    if cache.exists() and not force:
        log.info("GBIF: loading occurrences from cache")
        return json.loads(cache.read_text(encoding="utf-8"))

    log.info("GBIF: fetching all Brazilian plant occurrences by class…")
    all_records = []

    for class_name, class_key in GBIF_CLASS_KEYS.items():
        log.info("  Fetching %s (classKey=%d)…", class_name, class_key)
        records = _fetch_by_class(class_key, class_name)
        all_records.extend(records)
        log.info("  %s: %d records", class_name, len(records))
        time.sleep(0.5)

    log.info("GBIF: %d total records across all classes", len(all_records))
    cache.write_text(json.dumps(all_records, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    return all_records


# ── Per-species fetch ─────────────────────────────────────────────────────────

def _fetch_species(species_name: str, max_records: int = 1000) -> list[dict]:
    """Fetch GBIF records for one species, excluding JBRJ publisher."""
    results = []
    offset  = 0

    for basis in ("PRESERVED_SPECIMEN", "HUMAN_OBSERVATION", "MACHINE_OBSERVATION"):
        batch_offset = 0
        while len(results) < max_records:
            params = {
                "scientificName":     species_name,
                "country":            "BR",
                "basisOfRecord":      basis,
                "hasCoordinate":      "true",
                "hasGeospatialIssue": "false",
                "occurrenceStatus":   "PRESENT",
                "limit":              300,
                "offset":             batch_offset,
            }
            data = get_json(f"{GBIF_BASE}/occurrence/search", params=params)
            if not data:
                break

            for rec in data.get("results", []):
                # Skip JBRJ records (handled by flora_funga.py)
                if rec.get("publishingOrgKey") == JBRJ_PUBLISHER_KEY:
                    continue
                parsed = _parse_record(rec)
                if parsed:
                    results.append(parsed)

            if data.get("endOfRecords", True):
                break
            batch_offset += 300
            time.sleep(0.1)

    return results


# ── Per-class bulk fetch ──────────────────────────────────────────────────────

def _fetch_by_class(class_key: int, class_name: str,
                    max_per_class: int = 200_000) -> list[dict]:
    """Fetch all Brazilian occurrences for a GBIF class key."""
    results = []
    offset  = 0

    while len(results) < max_per_class:
        params = {
            "classKey":           class_key,
            "country":            "BR",
            "hasCoordinate":      "true",
            "hasGeospatialIssue": "false",
            "occurrenceStatus":   "PRESENT",
            "basisOfRecord":      "PRESERVED_SPECIMEN,HUMAN_OBSERVATION,MACHINE_OBSERVATION",
            "limit":              300,
            "offset":             offset,
        }
        data = get_json(f"{GBIF_BASE}/occurrence/search", params=params)
        if not data:
            break

        for rec in data.get("results", []):
            if rec.get("publishingOrgKey") == JBRJ_PUBLISHER_KEY:
                continue
            parsed = _parse_record(rec)
            if parsed:
                results.append(parsed)

        count = data.get("count", 0)
        if data.get("endOfRecords", True) or offset >= min(count, max_per_class):
            break
        offset += 300
        if offset % 30000 == 0:
            log.info("    %s: %d records so far (offset %d / %d)",
                     class_name, len(results), offset, count)
        time.sleep(0.2)

    return results


# ── Record parser ─────────────────────────────────────────────────────────────

def _parse_record(rec: dict) -> Optional[dict]:
    """Parse and validate a single GBIF occurrence record."""
    lat = rec.get("decimalLatitude")
    lon = rec.get("decimalLongitude")

    valid, reason = coord_is_valid(lat, lon)
    if not valid:
        return None

    if has_fatal_gbif_issue(rec.get("issues", [])):
        return None

    if is_cultivated(rec):
        return None

    sp_name = (rec.get("species") or
               rec.get("acceptedScientificName") or
               rec.get("scientificName") or "")
    if not sp_name:
        return None
    parts = str(sp_name).strip().split()
    if len(parts) < 2:
        return None
    binomial = f"{parts[0]} {parts[1]}"

    # Map GBIF class to ePOV group
    group = GROUP_LABEL.get(rec.get("class", ""), "")

    # Coordinate precision flag
    unc = rec.get("coordinateUncertaintyInMeters")
    try:
        unc_val = float(unc) if unc else None
    except (ValueError, TypeError):
        unc_val = None

    return {
        "record_id":             str(uuid.uuid4())[:16],
        "species_name":          binomial,
        "accepted_name":         binomial,   # resolved in taxonomy.py
        "name_status":           "Unresolved",
        "family":                rec.get("family", ""),
        "order":                 rec.get("order", ""),
        "group":                 group,
        "life_form":             "",
        "endemic_brazil":        None,
        "biome":                 rec.get("biome", ""),
        "state":                 rec.get("stateProvince", ""),
        "municipality":          rec.get("municipality", ""),
        "latitude":              float(lat),
        "longitude":             float(lon),
        "coordinate_precision_m":unc_val,
        "year":                  rec.get("year"),
        "collector":             rec.get("recordedBy", ""),
        "catalog_number":        rec.get("catalogNumber", ""),
        "institution_code":      rec.get("institutionCode", ""),
        "source_bank":           "GBIF",
        "basis_of_record":       rec.get("basisOfRecord", ""),
        "is_native":             _parse_native(rec),
        "is_duplicate":          False,
        "duplicate_of":          None,
        "gbif_n":                0,
        "flora_funga_n":         0,
        "specieslink_n":         0,
        "total_unique_points":   0,
    }


def _parse_native(rec: dict) -> str:
    em = rec.get("establishmentMeans", "")
    if not em:
        return "unknown"
    em_l = em.lower()
    if "native" in em_l:
        return "native"
    if "naturali" in em_l:
        return "naturalized"
    if "introduc" in em_l:
        return "introduced"
    if "cultivat" in em_l:
        return "cultivated"
    return em
