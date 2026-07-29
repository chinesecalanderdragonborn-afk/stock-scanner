"""Derived analytics computed from a Quote's session bars.

These are the numbers momentum scanners live on: relative volume, VWAP and
distance from it, ATR and ATR-based spreads, high/low of day, gap %, and
short-window momentum ("2-min %").
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from backend.models import Bar, Quote

# US regular session length in minutes (09:30 -> 16:00 ET).
SESSION_MINUTES = 390


@dataclass
class Metrics:
    symbol: str
    name: str
    price: float
    prev_close: float
    open: float
    change_pct: float       # vs prev close
    gap_pct: float          # open vs prev close
    volume: float           # cumulative session volume
    rvol: float             # relative volume vs expected-by-now
    float_shares: float
    float_rotation: float   # cumulative volume / float
    vwap: float
    vwap_dist_pct: float    # price vs vwap
    atr: float              # 14-bar ATR on 1-min candles
    hod: float
    lod: float
    dist_from_hod_pct: float
    atr_spread: float       # (hod-lod)/atr  -> intraday range in ATRs
    atr_hod: float          # (hod-price)/atr -> ATRs below the high
    mom_2min_pct: float     # % change over trailing 2 minutes
    exchange: str
    sector: str
    halted: bool
    halt_reason: str

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        return d


def _true_ranges(bars: list[Bar]) -> list[float]:
    trs = []
    prev_close = bars[0].o
    for b in bars:
        tr = max(b.h - b.l, abs(b.h - prev_close), abs(b.l - prev_close))
        trs.append(tr)
        prev_close = b.c
    return trs


def _atr(bars: list[Bar], period: int = 14) -> float:
    if not bars:
        return 0.0
    trs = _true_ranges(bars)
    window = trs[-period:] if len(trs) >= period else trs
    return sum(window) / len(window) if window else 0.0


def _session_fraction(now: float, first_bar_t: int) -> float:
    """Fraction of the regular session elapsed, clamped to (0, 1].

    Used to scale average daily volume into an "expected volume by now" so
    relative volume is meaningful early in the day.
    """
    minutes = max(1.0, (now - first_bar_t) / 60.0)
    return min(1.0, minutes / SESSION_MINUTES)


def compute(quote: Quote, now: float | None = None) -> Metrics | None:
    """Turn a raw Quote into a full Metrics row. Returns None if no bars."""
    bars = quote.bars
    if not bars:
        return None
    now = now or time.time()

    open_ = bars[0].o
    price = bars[-1].c
    hod = max(b.h for b in bars)
    lod = min(b.l for b in bars)
    volume = sum(b.v for b in bars)

    prev_close = quote.prev_close or open_
    change_pct = (price - prev_close) / prev_close * 100 if prev_close else 0.0
    gap_pct = (open_ - prev_close) / prev_close * 100 if prev_close else 0.0

    # VWAP over the session.
    pv = sum(((b.h + b.l + b.c) / 3.0) * b.v for b in bars)
    vwap = pv / volume if volume else price
    vwap_dist_pct = (price - vwap) / vwap * 100 if vwap else 0.0

    # Relative volume vs expected-by-now.
    frac = _session_fraction(now, bars[0].t)
    expected = quote.avg_volume * frac
    rvol = volume / expected if expected else 0.0

    float_rotation = volume / quote.float_shares if quote.float_shares else 0.0

    atr = _atr(bars)
    dist_from_hod_pct = (price - hod) / hod * 100 if hod else 0.0
    atr_spread = (hod - lod) / atr if atr else 0.0
    atr_hod = (hod - price) / atr if atr else 0.0

    # 2-minute momentum: last 1-min bar close vs close two bars earlier.
    if len(bars) >= 3:
        ref = bars[-3].c
        mom_2min_pct = (price - ref) / ref * 100 if ref else 0.0
    else:
        mom_2min_pct = change_pct

    return Metrics(
        symbol=quote.symbol,
        name=quote.name or quote.symbol,
        price=round(price, 4),
        prev_close=round(prev_close, 4),
        open=round(open_, 4),
        change_pct=round(change_pct, 2),
        gap_pct=round(gap_pct, 2),
        volume=round(volume),
        rvol=round(rvol, 2),
        float_shares=quote.float_shares,
        float_rotation=round(float_rotation, 2),
        vwap=round(vwap, 4),
        vwap_dist_pct=round(vwap_dist_pct, 2),
        atr=round(atr, 4),
        hod=round(hod, 4),
        lod=round(lod, 4),
        dist_from_hod_pct=round(dist_from_hod_pct, 2),
        atr_spread=round(atr_spread, 2),
        atr_hod=round(atr_hod, 2),
        mom_2min_pct=round(mom_2min_pct, 2),
        exchange=quote.exchange,
        sector=quote.sector,
        halted=quote.halted,
        halt_reason=quote.halt_reason,
    )
