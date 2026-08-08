"""Trade-plan engine — the decision layer on top of the raw metrics.

A scanner tells you *what* is moving. A day trader still has to answer the three
questions that actually matter before clicking buy:

    1. Which way do I lean, and is this even worth taking?  -> bias + grade
    2. Where do I get in, get out, and take profit?          -> entry / stop / targets
    3. How many shares, given what I'm willing to lose?       -> position size

This module answers all three from the `Metrics` row, so every name the scanner
surfaces arrives as a complete, risk-defined plan instead of just a quote.

The levels are deliberately mechanical and defensible:

* **Bias** comes from where price sits relative to VWAP and the day's move —
  the two references momentum traders anchor to.
* **Stop** is anchored to VWAP (the intraday line-in-the-sand) but never wider
  than 1 ATR, so risk stays bounded even when price is stretched from VWAP.
* **Targets** are pure R-multiples (1R / 2R) off the defined risk, plus a
  measured move, so reward:risk is explicit up front.
* **Grade** blends the quality signals a trader would eyeball anyway — relative
  volume, thrust, VWAP alignment, location in the day's range, float rotation
  and the resulting reward:risk — into a single 0-100 score.

Nothing here is investment advice; it is a disciplined restatement of the
metrics into an actionable, size-aware plan.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import config
from backend.engine.metrics import Metrics


@dataclass
class TradePlan:
    symbol: str
    bias: str            # "long" | "short" | "none"
    setup: str           # human label, e.g. "HOD breakout"
    grade: str           # "A+" | "A" | "B" | "C"
    score: float         # 0-100 composite quality
    entry: float         # trigger price
    stop: float          # protective stop
    risk_per_share: float
    target1: float       # 1R
    target2: float       # 2R
    target_measured: float  # measured-move / range-extension objective
    reward_risk: float   # to target2
    shares: int          # sized to the configured account risk
    dollar_risk: float   # $ at risk at the configured account risk
    position_value: float
    notes: str

    def as_dict(self) -> dict:
        return asdict(self)


def _round(v: float, price: float) -> float:
    """Round a price level to a sensible tick for its magnitude."""
    return round(v, 3 if price < 1 else 2)


def _score(m: Metrics, bias: str, reward_risk: float) -> float:
    """Composite 0-100 setup quality. Each term is clamped to [0, 1] then
    weighted; the weights sum to 100."""
    def clamp01(x: float) -> float:
        return 0.0 if x < 0 else 1.0 if x > 1 else x

    # Relative volume — the single most important confirmation. 1x -> 0, 5x -> 1.
    rvol_s = clamp01((m.rvol - 1.0) / 4.0)

    # Thrust: short-window momentum in the direction of the bias, 0-2% -> 0-1.
    thrust = m.mom_2min_pct if bias == "long" else -m.mom_2min_pct
    thrust_s = clamp01(thrust / 2.0)

    # VWAP alignment: reward price being on the correct side of VWAP.
    vd = m.vwap_dist_pct if bias == "long" else -m.vwap_dist_pct
    vwap_s = clamp01((vd + 0.5) / 2.5)   # -0.5% -> 0, +2% -> 1

    # Location in the day's range: longs want to be near the high, shorts low.
    if bias == "long":
        loc_s = clamp01(1.0 + m.dist_from_hod_pct / 3.0)  # at HOD -> 1
    else:
        # distance above the low, in %: (price-lod)/lod
        above_low = (m.price - m.lod) / m.lod * 100 if m.lod else 0.0
        loc_s = clamp01(1.0 - above_low / 3.0)             # at LOD -> 1

    # Float rotation / squeeze potential — bonus for low, fast-rotating float.
    rot_s = clamp01(m.float_rotation / 1.0)

    # Reward:risk quality — 1:1 -> 0, 3:1 -> 1.
    rr_s = clamp01((reward_risk - 1.0) / 2.0)

    score = (rvol_s * 26 + thrust_s * 22 + vwap_s * 18
             + loc_s * 16 + rr_s * 12 + rot_s * 6)
    return round(score, 1)


def _grade(score: float) -> str:
    if score >= 80:
        return "A+"
    if score >= 65:
        return "A"
    if score >= 50:
        return "B"
    return "C"


def _bias(m: Metrics) -> str:
    """Which way the setup leans, from VWAP side and the day's direction."""
    if m.halted:
        return "none"
    long_ok = m.price >= m.vwap and m.change_pct > 0
    short_ok = m.price < m.vwap and m.change_pct < 0
    if long_ok and not short_ok:
        return "long"
    if short_ok and not long_ok:
        return "short"
    # Ambiguous: break the tie with short-window momentum.
    if m.mom_2min_pct > 0:
        return "long"
    if m.mom_2min_pct < 0:
        return "short"
    return "none"


def build(m: Metrics,
          account: float | None = None,
          risk_pct: float | None = None) -> TradePlan:
    """Turn a Metrics row into a complete, sized trade plan.

    `account` / `risk_pct` default to the values in config; the frontend lets a
    trader override them interactively (position size is a pure division by
    risk-per-share, so it recomputes client-side without a round-trip too).
    """
    account = account if account is not None else config.ACCOUNT_SIZE
    risk_pct = risk_pct if risk_pct is not None else config.RISK_PER_TRADE_PCT

    price = m.price
    atr = m.atr or max(price * 0.01, 0.01)   # guard against a zero ATR
    bias = _bias(m)

    if bias == "long":
        # Enter on a break of the high of day (or here-and-now if already there).
        entry = max(price, m.hod)
        # Stop under VWAP, but never risk more than ~1 ATR.
        vwap_stop = min(m.vwap, m.lod)
        atr_stop = entry - atr
        stop = max(vwap_stop, atr_stop)
        if stop >= entry:                    # degenerate: fall back to ATR stop
            stop = entry - atr
        risk = entry - stop
        t1, t2 = entry + risk, entry + 2 * risk
        measured = entry + (m.hod - m.lod)   # range-extension objective
        setup = "HOD breakout" if m.dist_from_hod_pct > -1 else "VWAP reclaim long"
    elif bias == "short":
        entry = min(price, m.lod)
        vwap_stop = max(m.vwap, m.hod)
        atr_stop = entry + atr
        stop = min(vwap_stop, atr_stop)
        if stop <= entry:
            stop = entry + atr
        risk = stop - entry
        t1, t2 = entry - risk, entry - 2 * risk
        measured = entry - (m.hod - m.lod)
        setup = "LOD breakdown" if m.dist_from_hod_pct < -3 else "VWAP reject short"
    else:
        # No clean bias — return a flat, un-actionable plan.
        return TradePlan(
            symbol=m.symbol, bias="none", setup="no clean setup", grade="C",
            score=0.0, entry=price, stop=price, risk_per_share=0.0,
            target1=price, target2=price, target_measured=price,
            reward_risk=0.0, shares=0, dollar_risk=0.0, position_value=0.0,
            notes="Price is chopping around VWAP with no directional edge.",
        )

    risk = max(risk, 0.01)
    reward_risk = round(abs(t2 - entry) / risk, 2)
    score = _score(m, bias, reward_risk)

    # Position sizing: risk a fixed % of the account per trade, then cap the
    # notional so a low-priced, wide-stop name can't blow past a sane position.
    dollar_budget = account * (risk_pct / 100.0)
    shares = int(dollar_budget / risk) if risk else 0
    max_shares_by_notional = int((account * config.MAX_POSITION_PCT / 100.0) / price) if price else 0
    if max_shares_by_notional > 0:
        shares = min(shares, max_shares_by_notional)
    shares = max(shares, 0)
    dollar_risk = round(shares * risk, 2)
    position_value = round(shares * entry, 2)

    notes = (f"{'Long' if bias == 'long' else 'Short'} {setup.lower()}: "
             f"trigger {_round(entry, price)}, stop {_round(stop, price)} "
             f"({'under' if bias == 'long' else 'over'} "
             f"{'VWAP' if abs(stop - m.vwap) <= atr else 'ATR'}), "
             f"risking {_round(risk, price)}/sh for {reward_risk:g}R to T2. "
             f"RVol {m.rvol:g}x confirms.")

    return TradePlan(
        symbol=m.symbol,
        bias=bias,
        setup=setup,
        grade=_grade(score),
        score=score,
        entry=_round(entry, price),
        stop=_round(stop, price),
        risk_per_share=_round(risk, price),
        target1=_round(t1, price),
        target2=_round(t2, price),
        target_measured=_round(measured, price),
        reward_risk=reward_risk,
        shares=shares,
        dollar_risk=dollar_risk,
        position_value=position_value,
        notes=notes,
    )
