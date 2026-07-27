"""
flora_funga.py — ePOV
Flora e Funga do Brasil API client.

What this module provides
--------------------------
1. fetch_species_checklist()
   Downloads the complete list of accepted species + synonyms for the
   target plant groups (Angiospermas, Gimnospermas, Pteridófitas, Briófitas).
   Uses GET /flora/families → GET /flora/species/{family} per family.
   Cached to data/cache/flora_checklist.json.

2. enrich_species(taxon_name)
   Fetches full profile for one taxon:
   GET /flora/taxon/{taxonName}
   Returns: life_form, substrate, vegetation, biome distribution,
            state distribution, endemic status, name_status.

3. fetch_herbarium_occurrences(species_list)
   The Flora e Funga API itself doesn't serve point occurrence data —
   occurrence records from Herbário Virtual REFLORA are published to GBIF
   under publishingOrgKey = '4b3e4a58-5b60-4e20-bc04-fbb6c0b6a769' (JBRJ).
   This module fetches those records via the GBIF occurrence API with
   the JBRJ publisher filter, so they appear in the CSV as source='Flora_Funga'.

API base: https://servicos.jbrj.gov.br/v2
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Optional

from app.config import (
    FLORA_FUNGA_BASE, GBIF_BASE, FLORA_FUNGA_TOKEN,
    TARGET_GROUPS, GROUP_LABEL, CACHE_DIR, BRAZIL_BBOX,
)
from app.utils import get_json, coord_is_valid, is_cultivated, has_fatal_gbif_issue

log = logging.getLogger(__name__)

# JBRJ / Herbário Virtual REFLORA publisher key on GBIF
JBRJ_PUBLISHER_KEY = "4b3e4a58-5b60-4e20-bc04-fbb6c0b6a769"

# Flora e Funga base headers
def _ff_headers() -> dict:
    h = {"Accept": "application/json",
         "User-Agent": "ePOV/1.0 (epov-plant-occurrence@github)"}
    if FLORA_FUNGA_TOKEN:
        h["Authorization"] = f"Bearer {FLORA_FUNGA_TOKEN}"
    return h


# ── Species checklist ─────────────────────────────────────────────────────────

def fetch_species_checklist(force: bool = False) -> list[dict]:
    """
    Download complete species list from Flora e Funga for target groups.

    Returns list of dicts with:
        species_name, accepted_name, name_status, family, order, group,
        life_form, endemic_brazil, biomes, states, source_bank='Flora_Funga'
    Cached to data/cache/flora_checklist.json
    """
    cache = CACHE_DIR / "flora_checklist.json"
    if cache.exists() and not force:
        log.info("Flora e Funga: loading checklist from cache")
        return json.loads(cache.read_text(encoding="utf-8"))

    log.info("Flora e Funga: downloading species checklist…")

    # Step 1: get all families
    families_data = get_json(
        f"{FLORA_FUNGA_BASE}/flora/families",
        headers=_ff_headers()
    )
    if not families_data:
        log.error("Flora e Funga: could not fetch family list")
        return []

    families = families_data if isinstance(families_data, list) else \
               families_data.get("result", families_data.get("data", []))

    log.info("Flora e Funga: %d families found", len(families))

    all_species = []
    for fam_entry in families:
        fam_name = (fam_entry if isinstance(fam_entry, str)
                    else fam_entry.get("family", fam_entry.get("nome", "")))
        if not fam_name:
            continue

        data = get_json(
            f"{FLORA_FUNGA_BASE}/flora/species/{fam_name}",
            headers=_ff_headers()
        )
        if not data:
            continue

        species_list = data if isinstance(data, list) else \
                       data.get("result", data.get("data", []))

        for sp in species_list:
            group_raw = sp.get("group", sp.get("grupo", ""))
            if group_raw not in TARGET_GROUPS:
                continue

            # Skip cultivated-only taxa
            origin = sp.get("origin", sp.get("origem", "")).lower()
            if "cultivad" in origin or "exótica" in origin.lower():
                continue

            name_status = sp.get("nameStatus", sp.get("statusNome", ""))

            record = {
                "species_name":    sp.get("taxonName", sp.get("nomeTaxon", "")),
                "accepted_name":   sp.get("acceptedName", sp.get("nomeAceito",
                                    sp.get("taxonName", ""))),
                "name_status":     name_status,
                "family":          fam_name,
                "order":           sp.get("order", sp.get("ordem", "")),
                "group":           GROUP_LABEL.get(group_raw, group_raw),
                "life_form":       sp.get("lifeForm", sp.get("formaVida", "")),
                "endemic_brazil":  _parse_endemic(sp),
                "biomes":          _parse_biomes(sp),
                "states":          _parse_states(sp),
                "source_bank":     "Flora_Funga",
            }
            all_species.append(record)
        time.sleep(0.15)

    log.info("Flora e Funga checklist: %d taxa", len(all_species))
    cache.write_text(json.dumps(all_species, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    return all_species


def _parse_endemic(sp: dict) -> bool:
    val = sp.get("endemism", sp.get("endemismo", sp.get("endemic", "")))
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ("yes", "sim", "true", "1", "endêmica")


def _parse_biomes(sp: dict) -> str:
    val = sp.get("biome", sp.get("bioma", sp.get("phytogeographicDomain", "")))
    if isinstance(val, list):
        return "; ".join(val)
    return str(val) if val else ""


def _parse_states(sp: dict) -> str:
    val = sp.get("states", sp.get("estados", sp.get("occurrence", "")))
    if isinstance(val, list):
        return "; ".join(val)
    return str(val) if val else ""


# ── Taxon enrichment ──────────────────────────────────────────────────────────

def enrich_taxon(taxon_name: str) -> dict:
    """
    Fetch full profile for one taxon from Flora e Funga.
    Returns enrichment dict (merges into species record).
    Cached per taxon.
    """
    safe = taxon_name.replace(" ", "_").replace("/", "_")
    cache = CACHE_DIR / f"ff_taxon_{safe[:80]}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))

    data = get_json(
        f"{FLORA_FUNGA_BASE}/flora/taxon/{taxon_name}",
        headers=_ff_headers()
    )
    result = {}
    if data:
        rec = data[0] if isinstance(data, list) and data else data
        if isinstance(rec, dict):
            result = {
                "life_form":     rec.get("lifeForm", rec.get("formaVida", "")),
                "substrate":     rec.get("substrate", rec.get("substrato", "")),
                "vegetation":    rec.get("vegetationType",
                                         rec.get("tipoVegetacao", "")),
                "endemic_brazil":_parse_endemic(rec),
                "biomes":        _parse_biomes(rec),
                "states":        _parse_states(rec),
            }
    cache.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    time.sleep(0.1)
    return result


# ── Occurrence records via GBIF (JBRJ/Herbário Virtual publisher) ─────────────

def fetch_herbarium_occurrences(species_names: list[str],
                                 force: bool = False) -> list[dict]:
    """
    Fetch point occurrence records published by JBRJ (Herbário Virtual REFLORA)
    via GBIF. These are returned as source_bank='Flora_Funga'.

    Uses GBIF occurrence search filtered by:
      publishingOrgKey = JBRJ_PUBLISHER_KEY
      country = BR
      hasCoordinate = true
      hasGeospatialIssue = false
    """
    cache = CACHE_DIR / "flora_occurrences.json"
    if cache.exists() and not force:
        log.info("Flora e Funga occurrences: loading from cache")
        return json.loads(cache.read_text(encoding="utf-8"))

    log.info("Flora e Funga: fetching herbarium occurrences from GBIF (JBRJ publisher)…")
    records = []

    # Fetch by species name to stay within memory limits
    for i, sp_name in enumerate(species_names):
        sp_records = _fetch_gbif_for_species(sp_name, publisher=JBRJ_PUBLISHER_KEY)
        records.extend(sp_records)

        if (i + 1) % 100 == 0:
            log.info("  Flora_Funga occurrences: %d/%d species, %d records",
                     i + 1, len(species_names), len(records))
        time.sleep(0.2)

    log.info("Flora e Funga: %d occurrence records fetched", len(records))
    cache.write_text(json.dumps(records, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    return records


def _fetch_gbif_for_species(species_name: str,
                             publisher: str = None,
                             max_records: int = 1000) -> list[dict]:
    """Fetch GBIF occurrences for one species, optionally filtered by publisher."""
    results = []
    offset  = 0

    while len(results) < max_records:
        params = {
            "scientificName":    species_name,
            "country":           "BR",
            "hasCoordinate":     "true",
            "hasGeospatialIssue":"false",
            "occurrenceStatus":  "PRESENT",
            "limit":             300,
            "offset":            offset,
        }
        if publisher:
            params["publishingOrgKey"] = publisher

        data = get_json(f"{GBIF_BASE}/occurrence/search", params=params)
        if not data:
            break

        for rec in data.get("results", []):
            parsed = _parse_gbif_record(rec, source="Flora_Funga")
            if parsed:
                results.append(parsed)

        if data.get("endOfRecords", True):
            break
        offset += 300
        time.sleep(0.15)

    return results


def _parse_gbif_record(rec: dict, source: str) -> Optional[dict]:
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
    if not sp_name or " " not in sp_name:
        return None

    parts = sp_name.strip().split()
    binomial = f"{parts[0]} {parts[1]}" if len(parts) >= 2 else sp_name

    return {
        "record_id":             str(uuid.uuid4())[:16],
        "species_name":          binomial,
        "accepted_name":         binomial,   # will be resolved later
        "name_status":           "Unresolved",
        "family":                rec.get("family", ""),
        "order":                 rec.get("order", ""),
        "group":                 GROUP_LABEL.get(rec.get("class", ""), ""),
        "life_form":             "",
        "endemic_brazil":        None,
        "biome":                 rec.get("biome", ""),
        "state":                 rec.get("stateProvince", ""),
        "municipality":          rec.get("municipality", ""),
        "latitude":              float(lat),
        "longitude":             float(lon),
        "coordinate_precision_m":rec.get("coordinateUncertaintyInMeters"),
        "year":                  rec.get("year"),
        "collector":             rec.get("recordedBy", ""),
        "catalog_number":        rec.get("catalogNumber", ""),
        "institution_code":      rec.get("institutionCode", ""),
        "source_bank":           source,
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
    if "native" in em_l or "nativa" in em_l:
        return "native"
    if "naturali" in em_l:
        return "naturalized"
    if "introduc" in em_l or "introduzi" in em_l:
        return "introduced"
    if "cultivat" in em_l or "cultiva" in em_l:
        return "cultivated"
    return em
