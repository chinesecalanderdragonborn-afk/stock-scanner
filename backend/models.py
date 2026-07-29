"""Shared data structures passed between providers, engine and API layer."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Bar:
    """A single OHLCV candle."""
    t: int          # epoch seconds (bar open time)
    o: float
    h: float
    l: float
    c: float
    v: float

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Quote:
    """A point-in-time snapshot for one symbol plus the day's intraday bars.

    Providers are responsible for filling `bars` (1-minute candles for the
    session) and the static reference fields (float, prev_close, name). The
    metrics engine derives everything else.
    """
    symbol: str
    name: str = ""
    prev_close: float = 0.0
    float_shares: float = 0.0        # shares in the tradable float
    avg_volume: float = 0.0          # 30d average daily volume
    exchange: str = "NASDAQ"
    sector: str = ""
    halted: bool = False
    halt_reason: str = ""
    bars: list[Bar] = field(default_factory=list)  # 1-minute session bars


@dataclass
class NewsItem:
    t: int
    symbol: str
    headline: str
    source: str = ""


@dataclass
class Halt:
    symbol: str
    reason: str
    halt_time: int
    resume_time: Optional[int] = None
    price: float = 0.0


@dataclass
class Index:
    name: str
    last: float
    change_pct: float
