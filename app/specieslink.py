"""
specieslink.py — ePOV
SpeciesLink new API client (api.splink.org.br).

Authentication: Bearer token in Authorization header.
Returns DarwinCore records.

SpeciesLink covers Brazilian herbaria and biological collections.
Many records overlap with GBIF (institutions publish to both), but
SpeciesLink often has more complete label data and finer institutional
metadata for Brazilian collections.

Deduplication between SpeciesLink and GBIF is handled in utils.py
(same species + coord within 100 m + same year = duplicate).
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Optional

from app.config import SPECIESLINK_BASE, SPECIESLINK_TOKEN, CACHE_DIR, GROUP_LABEL
from app.utils import get_json, post_json, coord_is_valid, is_cultivated

log = logging.getLogger(__name__)


def _headers() -> dict:
    h = {
        "Accept":     "application/json",
        "User-Agent": "ePOV/1.0 (epov-plant-occurrence@github)",
    }
    if SPECIESLINK_TOKEN:
        h["Authorization"] = f"Bearer {SPECIESLINK_TOKEN}"
    return h


def is_configured() -> bool:
    return bool(SPECIESLINK_TOKEN)


# ── Occurrence fetch ──────────────────────────────────────────────────────────

def fetch_occurrences(species_names: list[str],
                      force: bool = False) -> list[dict]:
    """
    Fetch occurrence records for all target species from SpeciesLink.

    Queries per species using the DarwinCore occurrence search endpoint.
    Filters: country=BR, hasCoordinate=true, kingdom=Plantae.

    Returns list of normalised occurrence dicts (ePOV schema).
    Cached to data/cache/specieslink_occurrences.json.
    """
    if not is_configured():
        log.warning("SpeciesLink: no token configured — skipping")
        return []

    cache = CACHE_DIR / "specieslink_occurrences.json"
    if cache.exists() and not force:
        log.info("SpeciesLink: loading occurrences from cache")
        return json.loads(cache.read_text(encoding="utf-8"))

    log.info("SpeciesLink: fetching occurrences for %d species…", len(species_names))
    all_records = []

    for i, sp_name in enumerate(species_names):
        records = _fetch_species(sp_name)
        all_records.extend(records)

        if (i + 1) % 100 == 0:
            log.info("  SpeciesLink: %d/%d species, %d records so far",
                     i + 1, len(species_names), len(all_records))
        time.sleep(0.25)  # polite delay

    log.info("SpeciesLink: %d total records fetched", len(all_records))
    cache.write_text(json.dumps(all_records, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    return all_records


def _fetch_species(species_name: str, max_records: int = 1000) -> list[dict]:
    """Fetch all SpeciesLink records for one species."""
    results = []
    page    = 1
    per_page = 500

    while len(results) < max_records:
        # SpeciesLink new API — DarwinCore occurrence search
        params = {
            "scientificname": species_name,
            "country":        "Brasil",
            "hascoordinates": "true",
            "per_page":       per_page,
            "page":           page,
        }
        data = get_json(
            f"{SPECIESLINK_BASE}/occurrence/search",
            params=params,
            headers=_headers(),
        )
        if not data:
            break

        # Response can be list or dict with 'data' key
        raw_list = data if isinstance(data, list) else data.get("data", [])
        if not raw_list:
            break

        for rec in raw_list:
            parsed = _parse_record(rec)
            if parsed:
                results.append(parsed)

        # Pagination: check if more pages exist
        total   = (data.get("total", 0) if isinstance(data, dict) else len(raw_list))
        fetched = page * per_page
        if fetched >= total or len(raw_list) < per_page:
            break
        page += 1
        time.sleep(0.2)

    return results


def _parse_record(rec: dict) -> Optional[dict]:
    """Parse and validate a single SpeciesLink DarwinCore record."""
    lat = rec.get("decimalLatitude") or rec.get("verbatimLatitude")
    lon = rec.get("decimalLongitude") or rec.get("verbatimLongitude")

    valid, reason = coord_is_valid(lat, lon)
    if not valid:
        return None

    if is_cultivated(rec):
        return None

    # Reject records clearly outside Brazil
    country = str(rec.get("country", rec.get("pais", ""))).lower()
    if country and "brasil" not in country and "brazil" not in country and country != "br":
        return None

    sp_name = (rec.get("scientificName") or
               rec.get("acceptedNameUsage") or
               rec.get("specificEpithet", ""))

    if not sp_name or " " not in str(sp_name):
        # Try to reconstruct from genus + epithet
        genus   = rec.get("genus", "")
        epithet = rec.get("specificEpithet", "")
        if genus and epithet:
            sp_name = f"{genus} {epithet}"
        else:
            return None

    parts = str(sp_name).strip().split()
    binomial = f"{parts[0]} {parts[1]}" if len(parts) >= 2 else str(sp_name)

    # Year extraction
    year = None
    for field in ("year", "ano", "eventDate", "dataColeta"):
        val = rec.get(field)
        if val:
            try:
                year = int(str(val)[:4])
                if 1600 <= year <= 2100:
                    break
            except (ValueError, TypeError):
                pass

    # State normalisation
    state = (rec.get("stateProvince") or
             rec.get("estado") or
             rec.get("province", ""))

    return {
        "record_id":             str(uuid.uuid4())[:16],
        "species_name":          binomial,
        "accepted_name":         binomial,   # resolved later
        "name_status":           "Unresolved",
        "family":                rec.get("family", rec.get("familia", "")),
        "order":                 rec.get("order", rec.get("ordem", "")),
        "group":                 _infer_group(rec),
        "life_form":             rec.get("lifeForm", ""),
        "endemic_brazil":        None,
        "biome":                 rec.get("biome", rec.get("bioma", "")),
        "state":                 state,
        "municipality":          rec.get("municipality", rec.get("municipio", "")),
        "latitude":              float(lat),
        "longitude":             float(lon),
        "coordinate_precision_m":rec.get("coordinateUncertaintyInMeters"),
        "year":                  year,
        "collector":             rec.get("recordedBy", rec.get("coletor", "")),
        "catalog_number":        rec.get("catalogNumber",
                                         rec.get("numeroTombo", "")),
        "institution_code":      rec.get("institutionCode",
                                         rec.get("siglaInstituicao", "")),
        "source_bank":           "SpeciesLink",
        "basis_of_record":       rec.get("basisOfRecord",
                                         rec.get("tipoRegistro", "")),
        "is_native":             _parse_native(rec),
        "is_duplicate":          False,
        "duplicate_of":          None,
        "gbif_n":                0,
        "flora_funga_n":         0,
        "specieslink_n":         0,
        "total_unique_points":   0,
    }


def _infer_group(rec: dict) -> str:
    """Try to infer plant group from SpeciesLink record fields."""
    for field in ("class", "classe", "phylum", "division"):
        val = rec.get(field, "")
        if val in GROUP_LABEL:
            return GROUP_LABEL[val]
    return ""


def _parse_native(rec: dict) -> str:
    em = rec.get("establishmentMeans", rec.get("origemOcorrencia", ""))
    if not em:
        return "unknown"
    em_l = str(em).lower()
    if "native" in em_l or "nativa" in em_l:
        return "native"
    if "naturali" in em_l:
        return "naturalized"
    if "introduc" in em_l or "introduzi" in em_l:
        return "introduced"
    if "cultivat" in em_l or "cultiva" in em_l:
        return "cultivated"
    return str(em)
