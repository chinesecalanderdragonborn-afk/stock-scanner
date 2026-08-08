"""Central configuration for the stock scanner / trade-ideas dashboard.

Everything tunable lives here: the ticker universe, screener thresholds,
refresh cadence and which data provider to use. Override with env vars.
"""
from __future__ import annotations

import os


# --- Data provider ---------------------------------------------------------
# "yahoo"     -> live yfinance data (default); safely falls back to the
#                simulator if Yahoo can't be reached, and says so
# "auto"      -> same behaviour as "yahoo"
# "simulated" -> force the built-in market simulator (no network needed)
PROVIDER = os.getenv("SCANNER_PROVIDER", "yahoo").lower()

# How often (seconds) the backend recomputes scans and pushes over the socket.
# Live (Yahoo) uses a slower cadence to stay well under rate limits.
REFRESH_SECONDS = float(os.getenv("SCANNER_REFRESH", "4"))
LIVE_REFRESH_SECONDS = float(os.getenv("SCANNER_LIVE_REFRESH", "15"))

# Server
HOST = os.getenv("SCANNER_HOST", "0.0.0.0")
PORT = int(os.getenv("SCANNER_PORT", "8000"))


# --- Ticker universe -------------------------------------------------------
# The scanner watches this universe every refresh. These are all REAL, liquid,
# actively-traded US tickers, so live (Yahoo) mode populates cleanly. It mixes
# mega-caps with the volatile, high-volume names that momentum traders watch
# (miners, EV, meme, AI small-caps). In "simulated" mode the same symbols get
# synthetic-but-plausible float / price / volume profiles.
UNIVERSE = [
    # mega / large cap
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AMD", "NFLX",
    "AVGO", "PLTR", "UBER", "DIS", "BABA", "PYPL", "SHOP", "INTC", "BAC",
    # high-beta / high-volume movers
    "SOFI", "NIO", "MARA", "RIOT", "COIN", "HOOD", "PLUG", "LCID", "RIVN",
    "GME", "AMC", "SMCI", "BBAI", "ENPH", "SNAP", "AAL", "CCL", "F", "T", "KO",
]

# Symbols treated as "focus" / auto-watchlist highlights.
FOCUS = ["NVDA", "TSLA", "AMD", "COIN"]


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


# --- Risk / position sizing ------------------------------------------------
# Defaults for the trade-plan engine. The dashboard lets a trader override
# account size and per-trade risk live (position size is a pure division by
# risk-per-share, so it recomputes instantly in the browser).
ACCOUNT_SIZE = float(os.getenv("SCANNER_ACCOUNT_SIZE", "25000"))     # $
RISK_PER_TRADE_PCT = float(os.getenv("SCANNER_RISK_PCT", "1.0"))     # % of acct
MAX_POSITION_PCT = float(os.getenv("SCANNER_MAX_POSITION_PCT", "40"))  # notional cap
