"""Scanner definitions.

Each scanner takes the full list of computed Metrics and returns the subset
(ranked) that qualifies as a trade idea of a particular flavour. These map to
the panels you see on a momentum trading terminal.
"""
from __future__ import annotations

from typing import Callable

import config
from backend.engine.metrics import Metrics

Scan = Callable[[list[Metrics]], list[Metrics]]


def _tradeable(m: Metrics) -> bool:
    return config.MOMO_MIN_PRICE <= m.price <= config.MOMO_MAX_PRICE


def momo_up(rows: list[Metrics]) -> list[Metrics]:
    """Names spiking up right now: positive 2-min momentum + real volume."""
    hits = [
        m for m in rows
        if _tradeable(m)
        and m.mom_2min_pct >= config.MOMO_MIN_2MIN
        and m.rvol >= config.MOMO_MIN_RVOL
    ]
    return sorted(hits, key=lambda m: m.mom_2min_pct, reverse=True)


def momo_down(rows: list[Metrics]) -> list[Metrics]:
    """Names selling off right now: negative 2-min momentum + volume."""
    hits = [
        m for m in rows
        if _tradeable(m)
        and m.mom_2min_pct <= -config.MOMO_MIN_2MIN
        and m.rvol >= config.MOMO_MIN_RVOL
    ]
    return sorted(hits, key=lambda m: m.mom_2min_pct)


def gappers(rows: list[Metrics]) -> list[Metrics]:
    """Gap-and-go candidates: gapped up meaningfully vs prior close."""
    hits = [m for m in rows if _tradeable(m) and m.gap_pct >= config.GAP_MIN_PCT]
    return sorted(hits, key=lambda m: m.gap_pct, reverse=True)


def near_hod(rows: list[Metrics]) -> list[Metrics]:
    """Breakout watch: green on day and pinned within X% of the high."""
    hits = [
        m for m in rows
        if _tradeable(m)
        and m.change_pct > 0
        and abs(m.dist_from_hod_pct) <= config.HOD_PROXIMITY_PCT
    ]
    return sorted(hits, key=lambda m: m.dist_from_hod_pct, reverse=True)


def low_float_runners(rows: list[Metrics]) -> list[Metrics]:
    """Low-float names on the move — the highest-squeeze setups."""
    hits = [
        m for m in rows
        if _tradeable(m)
        and 0 < m.float_shares <= config.LOW_FLOAT_MAX
        and m.change_pct >= config.GAP_MIN_PCT
    ]
    return sorted(hits, key=lambda m: m.change_pct, reverse=True)


def halts(rows: list[Metrics]) -> list[Metrics]:
    """Currently halted names (volatility / news / regulatory)."""
    return [m for m in rows if m.halted]


SCANS: dict[str, Scan] = {
    "momo_up": momo_up,
    "momo_down": momo_down,
    "gappers": gappers,
    "near_hod": near_hod,
    "low_float_runners": low_float_runners,
    "halts": halts,
}


def run_all(rows: list[Metrics], limit: int | None = None) -> dict[str, list[dict]]:
    """Run every scanner and return JSON-ready rows, truncated to `limit`."""
    limit = limit or config.SCAN_LIMIT
    out: dict[str, list[dict]] = {}
    for key, fn in SCANS.items():
        result = fn(rows)
        # halts are not price-truncated the same way but limit keeps payload sane
        out[key] = [m.as_dict() for m in result[:limit]]
    return out
