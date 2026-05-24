"""Project-wide paths and constants. Keep this tiny and obvious."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
RESULTS_DIR = DATA_DIR / "results"

CACHE_VERSION = 1  # bump per SPECS §7 when on-disk schemas change

CALENDAR_SYMBOL = "RELIANCE"  # SPECS §6 — used as trading-day source of truth
