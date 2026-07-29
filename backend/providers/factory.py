"""Provider selection with graceful fallback.

PROVIDER=auto tries Yahoo once; if the probe fails (no network / blocked
proxy / rate limit) it transparently falls back to the simulator so the
dashboard always runs.
"""
from __future__ import annotations

import config
from backend.providers.simulated import SimulatedProvider


def _probe_yahoo(universe):
    from backend.providers.yahoo import YahooProvider
    p = YahooProvider(universe=universe)
    quotes = p.get_quotes(universe[:2])
    if not quotes or not any(q.bars for q in quotes):
        raise RuntimeError("Yahoo returned no data")
    return p


def make_provider(universe=None):
    universe = universe or config.UNIVERSE
    choice = config.PROVIDER

    if choice == "simulated":
        return SimulatedProvider(universe), "simulated"

    if choice == "yahoo":
        return _probe_yahoo(universe), "yahoo"

    # auto
    try:
        return _probe_yahoo(universe), "yahoo"
    except Exception as e:  # noqa: BLE001
        print(f"[provider] live Yahoo unavailable ({e!s:.80}); "
              f"using simulator")
        return SimulatedProvider(universe), "simulated"
