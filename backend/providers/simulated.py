"""Deterministic-ish market simulator.

Generates a full session of 1-minute candles per symbol using a seeded random
walk, so the dashboard is fully populated and *moving* with no data feed. A
handful of low-float names are scripted as "runners" (gap + intraday spike)
so the momentum scanners always have something to show, mirroring the kind of
tape a small-cap momentum trader watches.

Every call to get_quotes() advances the clock, so successive refreshes show
live-looking movement over the websocket.
"""
from __future__ import annotations

import hashlib
import math
import random
import time

import config
from backend.models import Bar, Halt, Index, NewsItem, Quote

# Regular session, US/Eastern, expressed in epoch-relative minutes.
SESSION_MINUTES = 390


def _seed_for(symbol: str) -> int:
    return int(hashlib.md5(symbol.encode()).hexdigest()[:8], 16)


# Names scripted to run today (gap up + intraday momentum) and roughly when
# their spike peaks, as a fraction of the session.
_RUNNERS = {
    "GWAV": 0.55, "GSUN": 0.35, "BTBT": 0.60, "JBDI": 0.70,
    "STAK": 0.45, "NCRA": 0.50, "SXC": 0.40,
}
# Names scripted to fade / sell off.
_FADERS = {"SOXS": 0.3, "MUZ": 0.5, "AGEN": 0.4}

_SECTORS = [
    "Technology", "Financial - Capital Markets", "Healthcare",
    "Consumer Cyclical", "Energy", "Industrials", "Communication",
]

_NEWS_TEMPLATES = [
    "{sym} announces pricing of registered direct offering",
    "{sym} receives FDA clearance for lead product",
    "{sym} reports Q3 revenue up, narrows loss",
    "Piper Sandler keeps Overweight rating on {sym}, raises target",
    "{sym} enters strategic partnership, shares spike",
    "{sym} files S-3 shelf registration",
    "RBC Capital initiates coverage of {sym} at Outperform",
    "{sym} announces 1-for-{n} reverse stock split",
    "Insider buying reported at {sym} (Form 4)",
    "{sym} short interest rises to {n}% of float",
]


class SimulatedProvider:
    name = "simulated"

    def __init__(self, universe: list[str] | None = None):
        self.universe = universe or config.UNIVERSE
        self._static: dict[str, dict] = {}
        self._news_cache: list[NewsItem] = []
        self._news_last = 0.0
        self._halts: dict[str, Halt] = {}
        # A virtual session clock. Start "mid-session" so there's a full tape.
        self._session_start = time.time() - 0.62 * SESSION_MINUTES * 60
        self._build_static()

    # -- static per-symbol reference data ---------------------------------
    def _build_static(self) -> None:
        for sym in self.universe:
            rng = random.Random(_seed_for(sym))
            is_big = sym in {"AAPL", "AMZN", "TSLA", "NVDA", "AMD", "F", "KO",
                             "ENPH", "TFX", "PLTR"}
            if is_big:
                price = rng.uniform(25, 220)
                float_shares = rng.uniform(300e6, 4e9)
                avg_vol = rng.uniform(20e6, 80e6)
            else:
                price = rng.uniform(0.8, 12)
                float_shares = rng.uniform(2e6, 120e6)
                avg_vol = rng.uniform(300e3, 8e6)
            self._static[sym] = {
                "prev_close": round(price, 2),
                "float_shares": round(float_shares),
                "avg_volume": round(avg_vol),
                "sector": _SECTORS[_seed_for(sym) % len(_SECTORS)],
                "vol": rng.uniform(0.008, 0.03),  # per-minute vol
                "name": sym,
                "exchange": rng.choice(["NASDAQ", "NYSE", "AMEX"]),
            }

    # -- session generation ------------------------------------------------
    def _elapsed_minutes(self) -> int:
        m = int((time.time() - self._session_start) / 60)
        return max(3, min(SESSION_MINUTES, m))

    def _session_bars(self, sym: str) -> list[Bar]:
        """Build a session of 1-min candles as a scripted *level path* plus
        light AR(1) noise, so runners produce clean intraday moves instead of
        an unbounded random walk.
        """
        s = self._static[sym]
        rng = random.Random(_seed_for(sym) ^ int(self._session_start))
        n = self._elapsed_minutes()

        prev_close = s["prev_close"]
        noise = min(0.0035, s["vol"] * 0.15)   # per-bar noise, tamed

        runner = sym in _RUNNERS
        fader = sym in _FADERS

        # Opening gap.
        if runner:
            gap = rng.uniform(0.05, 0.25)
        elif fader:
            gap = rng.uniform(-0.12, -0.03)
        else:
            gap = rng.uniform(-0.03, 0.03)

        # Total scripted intraday move layered on top of the gap, realised as a
        # smooth logistic rise to `peak` then a partial fade.
        peak = _RUNNERS.get(sym, _FADERS.get(sym, 0.5))
        if runner:
            run_target = rng.uniform(0.30, 1.10)      # +30%..+110% run
        elif fader:
            run_target = -rng.uniform(0.15, 0.45)     # fade
        else:
            run_target = rng.uniform(-0.04, 0.05)     # drift

        bars: list[Bar] = []
        base_min_vol = s["avg_volume"] / SESSION_MINUTES
        eps = 0.0
        prev_c = prev_close * (1 + gap)
        for i in range(n):
            frac = i / SESSION_MINUTES
            # smooth path: logistic climb into `peak`, then relax 35% of it
            climb = 1.0 / (1.0 + math.exp(-(frac - peak) / 0.06))
            fade = max(0.0, frac - peak) * 0.5
            path = gap + run_target * (climb - fade)
            level = prev_close * (1 + path)
            # AR(1) micro-noise around the scripted level
            eps = eps * 0.7 + rng.gauss(0, noise)
            c = max(0.01, level * (1 + eps))
            o = prev_c
            hi = max(o, c) * (1 + abs(rng.gauss(0, noise)))
            lo = min(o, c) * (1 - abs(rng.gauss(0, noise)))
            # volume swells near the move and with per-bar range
            intensity = abs(c - o) / max(o, 1e-6)
            vmult = 0.6 + 4 * math.exp(-((frac - peak) ** 2) / (2 * 0.08 ** 2)) \
                + 40 * intensity
            v = base_min_vol * vmult * rng.uniform(0.7, 1.4)
            t = int(self._session_start + i * 60)
            bars.append(Bar(t=t, o=round(o, 4), h=round(hi, 4),
                            l=round(lo, 4), c=round(c, 4), v=round(v)))
            prev_c = c
        return bars

    # -- provider API ------------------------------------------------------
    def get_quotes(self, symbols: list[str]) -> list[Quote]:
        self._maybe_update_halts()
        quotes: list[Quote] = []
        for sym in symbols:
            if sym not in self._static:
                continue
            s = self._static[sym]
            bars = self._session_bars(sym)
            halt = self._halts.get(sym)
            quotes.append(Quote(
                symbol=sym,
                name=s["name"],
                prev_close=s["prev_close"],
                float_shares=s["float_shares"],
                avg_volume=s["avg_volume"],
                exchange=s["exchange"],
                sector=s["sector"],
                halted=halt is not None and halt.resume_time is None,
                halt_reason=halt.reason if halt else "",
                bars=bars,
            ))
        return quotes

    def _maybe_update_halts(self) -> None:
        now = time.time()
        # resume anything past its resume_time
        for sym, h in list(self._halts.items()):
            if h.resume_time and now >= h.resume_time:
                del self._halts[sym]
        # occasionally halt a runner on a volatility spike (LULD)
        if random.random() < 0.06 and len(self._halts) < 3:
            sym = random.choice(list(_RUNNERS))
            if sym not in self._halts:
                reason = random.choice(["LUDP", "Volatility (LULD)", "News Pending",
                                        "Regulatory Concern"])
                self._halts[sym] = Halt(
                    symbol=sym, reason=reason, halt_time=int(now),
                    resume_time=int(now) + random.randint(60, 300),
                    price=round(self._static[sym]["prev_close"], 2),
                )

    def get_halts(self) -> list[Halt]:
        return list(self._halts.values())

    def get_news(self, limit: int = 30) -> list[NewsItem]:
        now = time.time()
        if now - self._news_last > 8 and random.random() < 0.7:
            sym = random.choice(self.universe)
            tmpl = random.choice(_NEWS_TEMPLATES)
            headline = tmpl.format(sym=sym, n=random.randint(2, 20))
            self._news_cache.insert(0, NewsItem(
                t=int(now), symbol=sym, headline=headline,
                source=random.choice(["Benzinga", "PR Newswire", "SEC.gov",
                                      "Reuters", "Bloomberg"]),
            ))
            self._news_cache = self._news_cache[:60]
            self._news_last = now
        return self._news_cache[:limit]

    def get_indices(self) -> list[Index]:
        rng = random.Random(int(time.time() / 30))
        defs = [("DJIA", 44000), ("S&P500", 6300), ("NASDAQ", 20500), ("Oil", 78)]
        out = []
        for name, base in defs:
            chg = rng.uniform(-1.6, 1.6) if name != "Oil" else rng.uniform(-3, 7)
            out.append(Index(name=name, last=round(base * (1 + chg / 100), 2),
                             change_pct=round(chg, 2)))
        return out
