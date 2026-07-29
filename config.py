"""Central configuration for the stock scanner / trade-ideas dashboard.

Everything tunable lives here: the ticker universe, screener thresholds,
refresh cadence and which data provider to use. Override with env vars.
"""
from __future__ import annotations

import os


# --- Data provider ---------------------------------------------------------
# "auto"      -> try live (Yahoo) first, fall back to the simulator
# "yahoo"     -> force live yfinance data (needs outbound network)
# "simulated" -> force the built-in market simulator (no network needed)
PROVIDER = os.getenv("SCANNER_PROVIDER", "auto").lower()

# How often (seconds) the backend recomputes scans and pushes over the socket.
REFRESH_SECONDS = float(os.getenv("SCANNER_REFRESH", "3"))

# Server
HOST = os.getenv("SCANNER_HOST", "0.0.0.0")
PORT = int(os.getenv("SCANNER_PORT", "8000"))


# --- Ticker universe -------------------------------------------------------
# The scanner watches this universe every refresh. In "simulated" mode these
# are given synthetic-but-plausible float / price / volume profiles. Mix of
# large caps (for indices/news flavour) and low-float small caps (the kind of
# names momentum day-trading scanners surface).
UNIVERSE = [
    # low-float / small-cap momentum candidates
    "GWAV", "GSUN", "SOXS", "MUZ", "AGEN", "BTBT", "STAK", "REPL", "SXC",
    "HLP", "NCRA", "PAL", "CASI", "BTDR", "JBDI", "AORZ", "DFNS", "SPRC",
    "GENVR", "AGRZ", "CNET", "ANIX", "FVN", "HCAI", "CLDI", "CBZ", "AMIX",
    # large / liquid names for context + news
    "AAPL", "AMZN", "TSLA", "NVDA", "AMD", "F", "KO", "ENPH", "TFX", "PLTR",
]

# Symbols treated as "focus" / auto-watchlist highlights.
FOCUS = ["GWAV", "GSUN", "BTBT", "JBDI"]


# --- Screener thresholds ---------------------------------------------------
# A "momentum" candidate must clear these to appear in the Momo scans.
MOMO_MIN_PRICE = float(os.getenv("SCANNER_MOMO_MIN_PRICE", "0.5"))
MOMO_MAX_PRICE = float(os.getenv("SCANNER_MOMO_MAX_PRICE", "50"))
MOMO_MIN_RVOL = float(os.getenv("SCANNER_MOMO_MIN_RVOL", "1.5"))   # rel. volume
MOMO_MIN_2MIN = float(os.getenv("SCANNER_MOMO_MIN_2MIN", "0.4"))    # % over 2m

# Low-float runner definition.
LOW_FLOAT_MAX = float(os.getenv("SCANNER_LOW_FLOAT_MAX", "50_000_000".replace("_", "")))

# Gappers.
GAP_MIN_PCT = float(os.getenv("SCANNER_GAP_MIN_PCT", "3"))

# Near-high-of-day proximity (percent).
HOD_PROXIMITY_PCT = float(os.getenv("SCANNER_HOD_PROXIMITY", "1.0"))

# How many rows each scan table returns.
SCAN_LIMIT = int(os.getenv("SCANNER_SCAN_LIMIT", "12"))
