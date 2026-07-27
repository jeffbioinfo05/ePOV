"""
api.py — ePOV
FastAPI application for the ePOV browser interface.
Serves occurrence queries against the pre-built CSV index.
"""
from __future__ import annotations

import csv
import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

log      = logging.getLogger(__name__)
BASE_DIR = Path(__file__).parent.parent

app = FastAPI(
    title="ePOV",
    description="eDNA Brazilian Plant Occurrence Validator",
    version="1.0.0",
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# ── Load the most recent CSV into memory ──────────────────────────────────
_records: list[dict] = []
_loaded  = False

def _load_records():
    global _records, _loaded
    if _loaded:
        return
    _loaded = True
    out_dir = BASE_DIR / "data" / "output"
    csvs    = sorted(out_dir.glob("epov_occurrences_*.csv"), reverse=True)
    if not csvs:
        log.warning("No occurrence CSV found in data/output/. Run build.py first.")
        return
    latest = csvs[0]
    log.info("Loading occurrence data from %s…", latest.name)
    with open(latest, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Parse numeric fields
            for fld in ("latitude", "longitude", "coordinate_precision_m",
                        "year", "gbif_n", "flora_funga_n",
                        "specieslink_n", "total_unique_points"):
                val = row.get(fld, "")
                if val not in ("", None):
                    try:
                        row[fld] = int(val) if fld in ("year","gbif_n","flora_funga_n",
                                                        "specieslink_n","total_unique_points") \
                                   else float(val)
                    except (ValueError, TypeError):
                        row[fld] = None
            row["is_duplicate"]   = row.get("is_duplicate", "false").lower() == "true"
            row["endemic_brazil"] = row.get("endemic_brazil", "").lower() == "true"
            _records.append(row)
    log.info("Loaded %d records from CSV", len(_records))


@app.on_event("startup")
async def startup():
    _load_records()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/api/occurrences")
async def occurrences(
    lat:    float = Query(..., ge=-33.75, le=5.27),
    lon:    float = Query(..., ge=-73.99, le=-28.84),
    radius: float = Query(100, ge=5, le=500),
    group:  str   = Query("all"),
    source: str   = Query("all"),
    top:    Optional[int] = Query(None, ge=1),
):
    """Return occurrence records within radius_km of the query point."""
    from app.utils import haversine_m

    _load_records()
    if not _records:
        return JSONResponse(
            status_code=503,
            content={"error": "No occurrence data loaded. Run build.py first."}
        )

    radius_m = radius * 1000
    matched  = []

    for rec in _records:
        rlat = rec.get("latitude")
        rlon = rec.get("longitude")
        if rlat is None or rlon is None:
            continue
        if haversine_m(lat, lon, rlat, rlon) > radius_m:
            continue
        if group != "all" and rec.get("group", "") != group:
            continue
        if source != "all" and rec.get("source_bank", "") != source:
            continue
        matched.append(rec)

    if top:
        matched = matched[:top]

    n_unique  = sum(1 for r in matched if not r.get("is_duplicate"))
    n_species = len({r.get("accepted_name", r.get("species_name","")) for r in matched})

    return {
        "query": {
            "lat": lat, "lon": lon,
            "radius_km": radius,
            "group_filter": group,
            "source_filter": source,
        },
        "n_total":   len(matched),
        "n_unique":  n_unique,
        "n_species": n_species,
        "records":   matched,
    }


@app.post("/api/validate-list")
async def validate_list(
    lat:  float = Query(...),
    lon:  float = Query(...),
    file: UploadFile = File(...),
):
    text = (await file.read()).decode("utf-8", errors="replace")
    names = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            names.append(f"{parts[0]} {parts[1]}")
    names = list(dict.fromkeys(names))

    if not names:
        return JSONResponse(status_code=422, content={"error": "No valid names found."})
    if len(names) > 200:
        return JSONResponse(status_code=422, content={"error": "List exceeds 200 species."})

    # Simple validation: check against loaded records
    _load_records()
    species_index: dict[str, list[dict]] = defaultdict(list)
    for rec in _records:
        aname = rec.get("accepted_name", rec.get("species_name", ""))
        if aname:
            species_index[aname.lower()].append(rec)

    from app.utils import haversine_m
    import math

    results = []
    for sp in names:
        sp_lower = sp.lower()
        hits     = species_index.get(sp_lower, [])

        nearest_km = None
        n50 = n100 = n250 = 0

        for rec in hits:
            rlat = rec.get("latitude")
            rlon = rec.get("longitude")
            if rlat is None or rlon is None:
                continue
            d_m = haversine_m(lat, lon, rlat, rlon)
            d_km = d_m / 1000
            if nearest_km is None or d_km < nearest_km:
                nearest_km = d_km
            if d_km <= 50:   n50  += 1
            if d_km <= 100:  n100 += 1
            if d_km <= 250:  n250 += 1

        # Probability label
        if nearest_km is None:
            label = "No data in index"
            score = 0.2
        elif nearest_km <= 50:
            label, score = "Very likely", 0.95
        elif nearest_km <= 150:
            label, score = "Likely", 0.75
        elif nearest_km <= 400:
            label, score = "Possible", 0.50
        elif nearest_km <= 1000:
            label, score = "Unlikely", 0.25
        else:
            label, score = "Very unlikely", 0.08

        first = hits[0] if hits else {}
        results.append({
            "species":              sp,
            "family":               first.get("family", ""),
            "group":                first.get("group", ""),
            "nearest_distance_km":  round(nearest_km, 1) if nearest_km else None,
            "n50": n50, "n100": n100, "n250": n250,
            "probability_label":    label,
            "occurrence_score":     round(score, 3),
            "geographically_compatible": nearest_km is not None and nearest_km < 2000,
        })

    results.sort(key=lambda x: x["occurrence_score"], reverse=True)
    return {
        "query":       {"lat": lat, "lon": lon},
        "n_submitted": len(names),
        "n_processed": len(results),
        "results":     results,
    }


@app.get("/api/stats")
async def stats():
    _load_records()
    from collections import Counter
    by_src   = Counter(r.get("source_bank","") for r in _records)
    by_group = Counter(r.get("group","") for r in _records)
    n_unique = sum(1 for r in _records if not r.get("is_duplicate"))
    n_sp     = len({r.get("accepted_name","") for r in _records})
    return {
        "n_total_records": len(_records),
        "n_unique_points": n_unique,
        "n_species":       n_sp,
        "by_source":       dict(by_src),
        "by_group":        dict(by_group),
    }


@app.get("/api/health")
async def health():
    return {"status": "ok", "tool": "ePOV", "version": "1.0.0",
            "records_loaded": len(_records)}
