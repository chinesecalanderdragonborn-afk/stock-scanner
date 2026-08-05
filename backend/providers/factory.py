"""Provider selection.

Default is live Yahoo Finance data. If Yahoo can't be reached (no network,
blocked proxy, rate limit) the dashboard still comes up on the simulator so it
never hard-crashes — but it says so loudly, and the UI's SIM tag makes the
fallback obvious. Set SCANNER_PROVIDER=simulated to force the offline demo.
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
        print("[provider] using the built-in market simulator (offline demo)")
        return SimulatedProvider(universe), "simulated"

    # "yahoo" (default) and "auto" both prefer live data and fall back safely.
    try:
        provider = _probe_yahoo(universe)
        print("[provider] connected to live Yahoo Finance data")
        return provider, "yahoo"
    except Exception as e:  # noqa: BLE001
        print("\n" + "!" * 64)
        print("  Could not reach live Yahoo Finance data:")
        print(f"    {e!s:.90}")
        print("  Falling back to the SIMULATOR so the app still runs.")
        print("  (Check your internet connection; the top-left tag will read SIM.)")
        print("!" * 64 + "\n")
        return SimulatedProvider(universe), "simulated"
