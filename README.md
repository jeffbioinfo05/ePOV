# 🌿 ePOV
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21625717.svg)](https://doi.org/10.5281/zenodo.21625717)

**eDNA Brazilian Plant Occurrence Validator**

ePOV builds a curated occurrence database for Brazilian plants (Angiospermas,
Gimnospermas, Pteridófitas, Briófitas) by combining three data sources and
applying multi-layer quality filters. The result is a CSV with one row per
occurrence record and a web interface for spatial queries.

---

## Data sources

| Source | Coverage | Curation level |
|--------|----------|----------------|
| **Flora e Funga do Brasil** | Taxonomy reference + JBRJ herbarium | High — specialist-curated |
| **SpeciesLink** | Brazilian herbarium collections | Medium-high — institutional |
| **GBIF** | All other publishers, Brazil | Variable — filtered aggressively |

---

## Setup

### 1. Install dependencies
```bash
cd epov
pip install -r requirements.txt
```

### 2. Configure credentials
```bash
cp .env.example .env
```
Edit `.env`:
```
SPECIESLINK_TOKEN=your_token_here
```

**Where to get credentials:**
- **SpeciesLink**: request at https://specieslink.net/ws/ — free for research
- **Flora e Funga**: currently a public API, no token required

The tool runs without SpeciesLink credentials — that data source will simply
be skipped. Flora e Funga and GBIF work without authentication.

### 3. Build the occurrence database
```bash
python build.py
```
This downloads and curates all occurrence data. Expected runtime:
- Flora e Funga checklist: ~30 min
- GBIF occurrences: 4–12 h depending on record volume
- SpeciesLink: 2–6 h
- Total: run overnight; safe to interrupt (`Ctrl+C`) and resume

**Resume after interruption:**
```bash
python build.py   # automatically skips completed phases
```

**Force full rebuild:**
```bash
python build.py --rebuild
```

**Run a single phase:**
```bash
python build.py --phase checklist   # taxonomy only
python build.py --phase gbif        # GBIF occurrences only
python build.py --phase specieslink
python build.py --phase flora
python build.py --phase merge       # deduplicate + export (no downloads)
```

### 4. Start the interface
```bash
python run.py
```
Open **http://localhost:8001** in a browser.

---

## Output CSV

One row per occurrence record. The file is saved to `data/output/epov_occurrences_YYYYMMDD.csv`.

| Column | Description |
|--------|-------------|
| `record_id` | Unique identifier assigned by ePOV |
| `species_name` | Name as it appears in the source bank |
| `accepted_name` | Name accepted by Flora e Funga |
| `name_status` | Accepted / Synonym / Unresolved |
| `family` | Plant family |
| `order` | Taxonomic order |
| `group` | Angiospermae / Gymnospermae / Pteridophyta / Bryophyta |
| `life_form` | Life form from Flora e Funga |
| `endemic_brazil` | true / false |
| `biome` | Amazônia / Cerrado / Mata Atlântica / etc. |
| `state` | Brazilian state abbreviation |
| `municipality` | Municipality name |
| `latitude` | Decimal degrees WGS-84 |
| `longitude` | Decimal degrees WGS-84 |
| `coordinate_precision_m` | Reported uncertainty in metres (when available) |
| `year` | Year of collection |
| `collector` | Collector name(s) |
| `catalog_number` | Herbarium catalog / voucher number |
| `institution_code` | Institution acronym (e.g. RB, SP, INPA) |
| `source_bank` | Flora_Funga / SpeciesLink / GBIF |
| `basis_of_record` | PreservedSpecimen / HumanObservation / etc. |
| `is_native` | native / naturalized / introduced / cultivated / unknown |
| `is_duplicate` | true = same species + same year + within 100 m of another bank's record |
| `duplicate_of` | record_id of the canonical record (when is_duplicate=true) |
| `gbif_n` | Unique GBIF points for this species (species-level, repeated per row) |
| `flora_funga_n` | Unique Flora e Funga points for this species |
| `specieslink_n` | Unique SpeciesLink points for this species |
| `total_unique_points` | Total deduplicated points across all banks |

---

## Curation filters applied

**Coordinate filters (discarded):**
- Missing or non-numeric coordinates
- Coordinates `(0, 0)`
- Outside Brazil bounding box (`-33.75°` to `5.27°` lat, `-73.99°` to `-28.84°` lon)
- Known institution centroid coordinates (e.g. JBRJ main building)
- Both lat and lon are whole-number integers (centroid geocoding artifact)

**Record filters (discarded):**
- Fatal GBIF issues: `ZERO_COORDINATE`, `COORDINATE_INVALID`,
  `COORDINATE_OUT_OF_RANGE`, `COUNTRY_COORDINATE_MISMATCH`, `TAXON_MATCH_NONE`
- `establishmentMeans` = cultivated / managed / introduced

**Deduplication (flagged, not removed):**
- Same `accepted_name` + coordinates within 100 m + same year of collection
- Records from lower-priority sources are flagged (`is_duplicate=true`)
- Priority order: Flora_Funga > SpeciesLink > GBIF

---

## Portability

The built database (`data/output/`) and cache (`data/cache/`) can be copied
to another machine. Requires only Python + `requirements.txt` to run the
web interface — no internet connection needed after the build.

---

## Version

**1.0.0** — stable.
