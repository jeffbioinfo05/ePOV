"""
config.py — ePOV
Central configuration: API credentials, constants, group/biome mappings.
Credentials are loaded from environment variables or .env file.
Never hardcode tokens here — use the .env file (see README).
"""
from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(Path(__file__).parent / ".env")

# ── API credentials ───────────────────────────────────────────────────────────
SPECIESLINK_TOKEN: str = os.getenv("SPECIESLINK_TOKEN", "")
FLORA_FUNGA_TOKEN: str = os.getenv("FLORA_FUNGA_TOKEN", "")  # if required

# ── API base URLs ─────────────────────────────────────────────────────────────
GBIF_BASE         = "https://api.gbif.org/v1"
FLORA_FUNGA_BASE  = "https://servicos.jbrj.gov.br/v2"
SPECIESLINK_BASE  = "https://api.splink.org.br"

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT       = Path(__file__).parent
DATA_DIR   = ROOT / "data"
CACHE_DIR  = DATA_DIR / "cache"
OUTPUT_DIR = DATA_DIR / "output"
LOG_DIR    = ROOT / "logs"

for d in (DATA_DIR, CACHE_DIR, OUTPUT_DIR, LOG_DIR):
    d.mkdir(parents=True, exist_ok=True)

# ── Brazil bounding box ───────────────────────────────────────────────────────
BRAZIL_BBOX = dict(min_lat=-33.75, max_lat=5.27,
                   min_lon=-73.99, max_lon=-28.84)

# ── Target plant groups (as used by Flora e Funga API) ───────────────────────
TARGET_GROUPS = {
    "Angiospermas",
    "Gimnospermas",
    "Samambaias e Licófitas",   # Pteridophyta
    "Briófitas",
}

# Mapping Flora e Funga group name → standardised ePOV group label
GROUP_LABEL = {
    "Angiospermas":           "Angiospermae",
    "Gimnospermas":           "Gymnospermae",
    "Samambaias e Licófitas": "Pteridophyta",
    "Briófitas":              "Bryophyta",
    # GBIF / SpeciesLink variants
    "Magnoliopsida":          "Angiospermae",
    "Liliopsida":             "Angiospermae",
    "Pinopsida":              "Gymnospermae",
    "Cycadopsida":            "Gymnospermae",
    "Polypodiopsida":         "Pteridophyta",
    "Lycopodiopsida":         "Pteridophyta",
    "Bryopsida":              "Bryophyta",
    "Anthocerotopsida":       "Bryophyta",
    "Marchantiopsida":        "Bryophyta",
    "Jungermanniopsida":      "Bryophyta",
    "Sphagnopsida":           "Bryophyta",
}

# GBIF class keys for target groups
GBIF_CLASS_KEYS = {
    # Angiosperms
    "Magnoliopsida": 220,    # eudicots + magnoliids
    "Liliopsida":    196,    # monocots
    # Gymnosperms
    "Pinopsida":     194,
    "Cycadopsida":   140,
    "Gnetopsida":    152,
    # Pteridophytes
    "Polypodiopsida":  186,
    "Lycopodiopsida":  174,
    "Equisetopsida":   200,  # horsetails
    # Bryophytes
    "Bryopsida":       191,
    "Marchantiopsida": 131,
    "Anthocerotopsida":182,
    "Jungermanniopsida":192,
    "Sphagnopsida":    183,
}

# ── Brazil state codes ────────────────────────────────────────────────────────
BRAZIL_STATES = {
    "AC","AL","AM","AP","BA","CE","DF","ES","GO","MA","MG","MS","MT",
    "PA","PB","PE","PI","PR","RJ","RN","RO","RR","RS","SC","SE","SP","TO",
}

# ── Biome names (Flora e Funga) ───────────────────────────────────────────────
BIOMES = {
    "Amazônia", "Caatinga", "Cerrado", "Mata Atlântica",
    "Pampa", "Pantanal",
}

# ── Curation constants ────────────────────────────────────────────────────────
MIN_YEAR              = 1700      # include historical records
MAX_COORD_UNCERTAINTY = 10_000    # metres — records with known uncertainty above this are flagged
DEDUP_RADIUS_M        = 100       # metres — same species + year + within this = duplicate
DEDUP_SAME_YEAR       = True      # require same year for deduplication

# GBIF issues that invalidate a record
FATAL_GBIF_ISSUES = {
    "ZERO_COORDINATE",
    "COORDINATE_OUT_OF_RANGE",
    "COORDINATE_INVALID",
    "COUNTRY_COORDINATE_MISMATCH",
    "TAXON_MATCH_NONE",
}

# Establishment means that indicate cultivated / not wild
CULTIVATED_VALUES = {
    "CULTIVATED", "MANAGED", "INTRODUCED",
    "cultivated", "managed", "introduced",
    "Cultivada", "Cultivado", "Introduzida",
}

# Known institution centroids to blacklist (lon, lat)
COORD_BLACKLIST = [
    (-43.2096, -22.9035),   # Jardim Botânico Rio de Janeiro
    (-46.6333, -23.5505),   # IBt São Paulo
    (-43.1729, -22.8138),   # JBRJ generic
    (-47.6476, -22.8150),   # Unicamp Herbário
    (-51.2177, -30.0346),   # UFRGS herbário
    (-48.0000, -15.7500),   # Brasília generic
]
BLACKLIST_RADIUS_M = 50     # metres — coords this close to blacklist = flag
