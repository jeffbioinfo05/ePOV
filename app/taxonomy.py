"""
taxonomy.py — ePOV
Taxonomic name resolution using the Flora e Funga do Brasil checklist
as the authoritative reference.

For each record coming from GBIF or SpeciesLink:
  1. Look up the species name in the Flora e Funga accepted name index
  2. If found as a synonym, replace accepted_name with the accepted name
  3. Set name_status: 'Accepted' | 'Synonym' | 'Unresolved'
  4. Enrich with life_form, endemic_brazil, biomes, states from checklist

This runs after all records are fetched, before deduplication.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

log = logging.getLogger(__name__)


def build_name_index(checklist: list[dict]) -> dict:
    """
    Build a lookup index from the Flora e Funga checklist.

    Returns dict:
        normalised_name → {
            accepted_name, name_status, family, order, group,
            life_form, endemic_brazil, biomes, states
        }
    Includes both accepted names and synonyms as keys.
    """
    index = {}
    for rec in checklist:
        sp_name  = _normalise(rec.get("species_name", ""))
        acc_name = _normalise(rec.get("accepted_name", ""))
        status   = rec.get("name_status", "Accepted")

        payload = {
            "accepted_name":  rec.get("accepted_name", ""),
            "name_status":    status,
            "family":         rec.get("family", ""),
            "order":          rec.get("order", ""),
            "group":          rec.get("group", ""),
            "life_form":      rec.get("life_form", ""),
            "endemic_brazil": rec.get("endemic_brazil"),
            "biomes":         rec.get("biomes", ""),
            "states":         rec.get("states", ""),
        }

        # Index the name as-is
        index[sp_name]  = payload

        # Also index accepted name (in case it differs from sp_name)
        if acc_name and acc_name != sp_name:
            acc_payload = dict(payload)
            acc_payload["name_status"] = "Accepted"
            index[acc_name] = acc_payload

    log.info("Taxonomy index built: %d name entries", len(index))
    return index


def _normalise(name: str) -> str:
    """Lowercase, strip author names and infraspecific epithets."""
    if not name:
        return ""
    # Remove author abbreviations (anything after the second word)
    parts = name.strip().split()
    if len(parts) >= 2:
        # Keep only genus + epithet
        binomial = f"{parts[0]} {parts[1]}"
    else:
        binomial = name.strip()
    return binomial.lower()


def resolve_records(records: list[dict], name_index: dict,
                    checklist_lookup: dict) -> list[dict]:
    """
    Resolve taxonomy for all records using the Flora e Funga name index.

    Modifies records in-place:
      - accepted_name: resolved or kept as-is
      - name_status:   Accepted | Synonym | Unresolved
      - family, order, group, life_form, endemic_brazil, biomes, states:
        filled from checklist when missing from source record

    Returns modified records list.
    """
    resolved = 0
    synonym  = 0
    unresolved = 0

    for rec in records:
        sp_name = _normalise(rec.get("species_name", ""))
        match   = name_index.get(sp_name)

        if match:
            rec["accepted_name"]  = match["accepted_name"] or rec["species_name"]
            rec["name_status"]    = match["name_status"] or "Accepted"
            if rec["name_status"] == "Synonym":
                synonym += 1
            else:
                resolved += 1

            # Fill missing fields from checklist
            for field in ("family", "order", "group", "life_form",
                          "endemic_brazil", "biomes", "states"):
                if not rec.get(field) and match.get(field) is not None:
                    rec[field] = match[field]
        else:
            rec["name_status"] = "Unresolved"
            unresolved += 1

    log.info("Taxonomy resolution: %d accepted, %d synonyms, %d unresolved",
             resolved, synonym, unresolved)
    return records


def filter_non_target_groups(records: list[dict],
                              name_index: dict) -> list[dict]:
    """
    Remove records whose resolved group is not in the target plant groups.
    Keeps records with group='' (unresolved) to avoid false negatives.
    """
    target = {"Angiospermae", "Gymnospermae", "Pteridophyta", "Bryophyta", ""}
    kept = [r for r in records if r.get("group", "") in target]
    removed = len(records) - len(kept)
    if removed:
        log.info("Taxonomy: removed %d records outside target groups", removed)
    return kept
