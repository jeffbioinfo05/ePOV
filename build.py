#!/usr/bin/env python3
"""
build.py — ePOV
eDNA Brazilian Plant Occurrence Validator — main pipeline.

Downloads and curates occurrence data for all Brazilian plant species
(Angiospermas, Gimnospermas, Pteridófitas, Briófitas) from three sources:

  1. Flora e Funga do Brasil  (taxonomy reference + JBRJ herbarium via GBIF)
  2. SpeciesLink              (Brazilian herbarium collections)
  3. GBIF                     (all other publishers, Brazil, curated)

Output
------
  data/output/epov_occurrences_YYYYMMDD.csv
  data/output/epov_summary_YYYYMMDD.json

Resumable
---------
  Each phase caches results in data/cache/.
  Re-running skips completed phases automatically.
  Use --rebuild to force a full rebuild.

Usage
-----
  python build.py
  python build.py --rebuild
  python build.py --phase checklist
  python build.py --phase flora
  python build.py --phase gbif
  python build.py --phase specieslink
  python build.py --phase merge
  python build.py --min-records 3

Credentials (.env file in project root)
-----------------------------------------
  SPECIESLINK_TOKEN=your_token
  FLORA_FUNGA_TOKEN=your_token   # only if API requires auth

See README.md for full setup instructions.
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from app.config       import DATA_DIR, CACHE_DIR, OUTPUT_DIR, LOG_DIR
from app.flora_funga  import fetch_species_checklist, fetch_herbarium_occurrences
from app.specieslink  import fetch_occurrences as fetch_specieslink
from app.specieslink  import is_configured as splink_ok
from app.gbif_client  import fetch_occurrences_by_group
from app.taxonomy     import build_name_index, resolve_records, filter_non_target_groups
from app.utils        import deduplicate_records, compute_species_counts
from app.exporter     import write_csv, write_summary_json

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / f"epov_build_{datetime.now().strftime('%Y%m%d_%H%M')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
log = logging.getLogger("epov.build")

_interrupted = False

def _sigint(sig, frame):
    global _interrupted
    _interrupted = True
    log.warning("Interrupt received — stopping after current phase.")

signal.signal(signal.SIGINT, _sigint)


# ── Pipeline steps ────────────────────────────────────────────────────────────

def step_checklist(force: bool) -> tuple[list[dict], dict]:
    _banner("Phase 1 — Flora e Funga species checklist")
    checklist  = fetch_species_checklist(force=force)
    name_index = build_name_index(checklist)
    n_acc = sum(1 for r in checklist if r.get("name_status", "") != "Synonym")
    n_syn = sum(1 for r in checklist if r.get("name_status", "") == "Synonym")
    log.info("Checklist: %d accepted names + %d synonyms", n_acc, n_syn)
    return checklist, name_index


def step_flora(checklist: list[dict], force: bool) -> list[dict]:
    _banner("Phase 2 — Herbário Virtual REFLORA (JBRJ via GBIF)")
    names = list({r.get("species_name", "") for r in checklist if r.get("species_name")})
    recs  = fetch_herbarium_occurrences(names, force=force)
    log.info("Flora e Funga: %d occurrence records", len(recs))
    return recs


def step_gbif(force: bool) -> list[dict]:
    _banner("Phase 3 — GBIF (non-JBRJ publishers, Brazil)")
    recs = fetch_occurrences_by_group(force=force)
    log.info("GBIF: %d records", len(recs))
    return recs


def step_specieslink(checklist: list[dict], force: bool) -> list[dict]:
    _banner("Phase 4 — SpeciesLink")
    if not splink_ok():
        log.warning("SpeciesLink token not set — skipping. "
                    "Add SPECIESLINK_TOKEN to .env to include this source.")
        return []
    names = list({r.get("species_name", "") for r in checklist if r.get("species_name")})
    recs  = fetch_specieslink(names, force=force)
    log.info("SpeciesLink: %d records", len(recs))
    return recs


def step_merge(all_records: list[dict], name_index: dict,
               min_records: int) -> Path:
    _banner("Phase 5 — Taxonomy resolution")
    all_records = resolve_records(all_records, name_index, {})
    all_records = filter_non_target_groups(all_records, name_index)
    log.info("After group filter: %d records", len(all_records))

    _banner("Phase 6 — Deduplication (100 m radius + same year)")
    all_records = deduplicate_records(all_records)
    n_dup  = sum(1 for r in all_records if r.get("is_duplicate"))
    n_uniq = len(all_records) - n_dup
    log.info("%d total records | %d unique points | %d cross-bank duplicates",
             len(all_records), n_uniq, n_dup)

    _banner("Phase 7 — Species counts")
    species_counts = compute_species_counts(all_records)

    if min_records > 1:
        keep = {n for n, c in species_counts.items()
                if c["total_unique_points"] >= min_records}
        before = len(all_records)
        all_records = [r for r in all_records
                       if r.get("accepted_name", r.get("species_name", "")) in keep]
        log.info("Min-records filter (%d): kept %d/%d species",
                 min_records, len(keep), len(species_counts))
        species_counts = {n: c for n, c in species_counts.items() if n in keep}

    log.info("Final: %d species | %d records", len(species_counts), len(all_records))

    _banner("Phase 8 — CSV export")
    tag      = datetime.now().strftime("%Y%m%d")
    csv_path  = OUTPUT_DIR / f"epov_occurrences_{tag}.csv"
    json_path = OUTPUT_DIR / f"epov_summary_{tag}.json"
    write_csv(all_records, species_counts, csv_path)
    write_summary_json(all_records, species_counts, json_path)
    return csv_path


def _load_caches() -> list[dict]:
    """Load all phase caches for a merge-only run."""
    all_records = []
    for fname in ("flora_occurrences.json", "gbif_occurrences.json",
                  "specieslink_occurrences.json"):
        p = CACHE_DIR / fname
        if p.exists():
            batch = json.loads(p.read_text(encoding="utf-8"))
            log.info("Loaded cache %s: %d records", fname, len(batch))
            all_records.extend(batch)
    return all_records


def _banner(msg: str):
    log.info("─" * 55)
    log.info(msg)
    log.info("─" * 55)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="epov-build",
        description="ePOV — build Brazilian plant occurrence CSV",
    )
    parser.add_argument(
        "--phase", default="all",
        choices=["all", "checklist", "flora", "gbif", "specieslink", "merge"],
        help="Run a single phase (default: all)",
    )
    parser.add_argument(
        "--rebuild", action="store_true",
        help="Ignore all caches and re-download everything",
    )
    parser.add_argument(
        "--min-records", type=int, default=1, metavar="N",
        help="Minimum unique points required per species (default: 1)",
    )
    args  = parser.parse_args()
    force = args.rebuild

    log.info("═" * 55)
    log.info("ePOV — eDNA Brazilian Plant Occurrence Validator")
    log.info("Started: %s UTC", datetime.utcnow().strftime("%Y-%m-%d %H:%M"))
    log.info("Phase: %-12s  Force rebuild: %s", args.phase, force)
    log.info("═" * 55)

    from app.config import SPECIESLINK_TOKEN, FLORA_FUNGA_TOKEN
    log.info("SpeciesLink token : %s", "set" if SPECIESLINK_TOKEN else "NOT SET (source will be skipped)")
    log.info("Flora Funga token : %s", "set" if FLORA_FUNGA_TOKEN else "not required")

    # Phase 1 is always needed for taxonomy
    checklist, name_index = step_checklist(force)
    if _interrupted or args.phase == "checklist":
        return

    all_records: list[dict] = []

    if args.phase == "merge":
        all_records = _load_caches()
    else:
        if args.phase in ("all", "flora"):
            all_records.extend(step_flora(checklist, force))
            if _interrupted:
                return

        if args.phase in ("all", "gbif"):
            all_records.extend(step_gbif(force))
            if _interrupted:
                return

        if args.phase in ("all", "specieslink"):
            all_records.extend(step_specieslink(checklist, force))
            if _interrupted:
                return

    if not all_records:
        log.error("No records to process. Check API credentials and network.")
        sys.exit(1)

    csv_out = step_merge(all_records, name_index, args.min_records)

    log.info("═" * 55)
    log.info("Done. Output: %s", csv_out)
    log.info("═" * 55)


if __name__ == "__main__":
    main()
