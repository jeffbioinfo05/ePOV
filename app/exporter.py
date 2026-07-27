"""
exporter.py — ePOV
CSV output: one row per occurrence record, all fields, per-species counts.
"""
from __future__ import annotations

import csv
import json
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

# Column order in final CSV
CSV_COLUMNS = [
    "record_id",
    "species_name",
    "accepted_name",
    "name_status",
    "family",
    "order",
    "group",
    "life_form",
    "endemic_brazil",
    "biome",
    "state",
    "municipality",
    "latitude",
    "longitude",
    "coordinate_precision_m",
    "year",
    "collector",
    "catalog_number",
    "institution_code",
    "source_bank",
    "basis_of_record",
    "is_native",
    "is_duplicate",
    "duplicate_of",
    "gbif_n",
    "flora_funga_n",
    "specieslink_n",
    "total_unique_points",
]


def write_csv(records: list[dict],
              species_counts: dict[str, dict],
              output_path: Path) -> Path:
    """
    Write the final ePOV CSV.

    Per-species count columns (gbif_n, flora_funga_n, specieslink_n,
    total_unique_points) are filled from species_counts for every row
    of that species — convenient for filtering in Excel/R/pandas without
    needing a join.

    Returns the output path.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()

        for rec in records:
            aname  = rec.get("accepted_name", rec.get("species_name", ""))
            counts = species_counts.get(aname, {})

            row = dict(rec)
            row["gbif_n"]             = counts.get("gbif_n", 0)
            row["flora_funga_n"]      = counts.get("flora_funga_n", 0)
            row["specieslink_n"]      = counts.get("specieslink_n", 0)
            row["total_unique_points"]= counts.get("total_unique_points", 0)

            # Boolean normalisation
            row["is_duplicate"]   = "true" if rec.get("is_duplicate") else "false"
            row["endemic_brazil"] = (
                "true"  if rec.get("endemic_brazil") is True else
                "false" if rec.get("endemic_brazil") is False else ""
            )

            writer.writerow(row)
            written += 1

    log.info("CSV written: %d records → %s", written, output_path)
    return output_path


def write_summary_json(records: list[dict],
                       species_counts: dict,
                       output_path: Path) -> Path:
    """Write a summary JSON with build metadata and per-group stats."""
    from collections import Counter
    by_group  = Counter(r.get("group", "") for r in records)
    by_source = Counter(r.get("source_bank", "") for r in records)
    n_unique  = sum(1 for r in records if not r.get("is_duplicate"))
    n_species = len(species_counts)

    summary = {
        "tool":      "ePOV — eDNA Brazilian Plant Occurrence Validator",
        "version":   "1.0.0",
        "built_at":  datetime.utcnow().isoformat() + "Z",
        "total_records":       len(records),
        "unique_occurrences":  n_unique,
        "species_count":       n_species,
        "records_by_group":    dict(by_group),
        "records_by_source":   dict(by_source),
        "dedup_radius_m":      100,
        "dedup_same_year":     True,
        "sources": [
            "Flora e Funga do Brasil (servicos.jbrj.gov.br/v2)",
            "SpeciesLink (api.splink.org.br)",
            "GBIF — non-JBRJ publishers (api.gbif.org)",
        ],
    }
    output_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info("Summary JSON → %s", output_path)
    return output_path
