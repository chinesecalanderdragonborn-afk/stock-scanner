"""FastAPI app: REST endpoints + a websocket that streams scans live.

Run with:  python start.py        (recommended, cross-platform)
       or  uvicorn backend.main:app
"""
from __future__ import annotations

import asyncio
import contextlib
import time
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import config
from backend.engine import metrics as metrics_engine
from backend.engine import scanners
from backend.engine import signals
from backend.providers.factory import make_provider

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

provider, provider_name = make_provider(config.UNIVERSE)


def _interval() -> float:
    """Live data polls slower than the simulator to respect rate limits."""
    return (config.LIVE_REFRESH_SECONDS if provider_name == "yahoo"
            else config.REFRESH_SECONDS)


class Snapshot:
    """Holds the latest computed state, refreshed on a background loop."""

    def __init__(self):
        self.rows: list[metrics_engine.Metrics] = []
        self.scans: dict[str, list[dict]] = {}
        self.news: list[dict] = []
        self.indices: list[dict] = []
        self.halts: list[dict] = []
        self.bars: dict[str, list] = {}   # symbol -> list[Bar] (1-min session)
        self.plans: dict[str, dict] = {}  # symbol -> trade plan dict
        self.top_setups: list[dict] = []  # rows ranked by setup grade/score
        self.updated: float = 0.0
        self.error: str = ""
        self.provider = provider_name

    def refresh(self):
        quotes = provider.get_quotes(config.UNIVERSE)
        now = time.time()
        rows = []
        bars = {}
        for q in quotes:
            m = metrics_engine.compute(q, now)
            if m:
                rows.append(m)
                bars[q.symbol] = q.bars
        self.rows = rows
        self.bars = bars
        # Build a risk-defined trade plan for every name, then rank the
        # actionable ones by setup grade so the best setups float to the top.
        self.plans = {m.symbol: signals.build(m).as_dict() for m in rows}
        ranked = sorted(
            (p for p in self.plans.values() if p["bias"] != "none" and p["score"] > 0),
            key=lambda p: p["score"], reverse=True,
        )
        self.top_setups = ranked[:config.SCAN_LIMIT]
        self.scans = scanners.run_all(rows)
        self.news = [n.__dict__ for n in provider.get_news(30)]
        self.indices = [i.__dict__ for i in provider.get_indices()]
        halts_fn = getattr(provider, "get_halts", None)
        if halts_fn:
            self.halts = [h.__dict__ for h in halts_fn()]
        self.error = "" if rows else "no market data returned"
        self.updated = now

    def payload(self) -> dict:
        return {
            "type": "snapshot",
            "provider": self.provider,
            "updated": self.updated,
            "server_time": time.time(),
            "loading": self.updated == 0.0,
            "error": self.error,
            "rows": [m.as_dict() for m in self.rows],
            "plans": self.plans,
            "top_setups": self.top_setups,
            "scans": self.scans,
            "risk": {
                "account": config.ACCOUNT_SIZE,
                "risk_pct": config.RISK_PER_TRADE_PCT,
                "max_position_pct": config.MAX_POSITION_PCT,
            },
            "news": self.news,
            "indices": self.indices,
            "halts": self.halts,
            "focus": config.FOCUS,
        }


snapshot = Snapshot()


async def _refresh_loop():
    interval = _interval()
    while True:
        try:
            await asyncio.to_thread(snapshot.refresh)
        except Exception as e:  # noqa: BLE001
            snapshot.error = str(e)
            print(f"[refresh] error: {e}")
        await asyncio.sleep(interval)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the background refresh without blocking server startup, so the
    # page is reachable immediately and fills in as data arrives.
    task = asyncio.create_task(_refresh_loop())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


app = FastAPI(title="Stock Scanner / Trade Ideas Dashboard", lifespan=lifespan)


# --- REST -----------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"ok": True, "provider": snapshot.provider,
            "universe": len(config.UNIVERSE), "updated": snapshot.updated}


@app.get("/api/snapshot")
def get_snapshot():
    return JSONResponse(snapshot.payload())


@app.get("/api/scan/{name}")
def get_scan(name: str):
    if name not in snapshot.scans:
        return JSONResponse({"error": "unknown scan", "available":
                             list(scanners.SCANS)}, status_code=404)
    return {"name": name, "rows": snapshot.scans[name]}


@app.get("/api/quote/{symbol}")
def get_quote(symbol: str):
    for m in snapshot.rows:
        if m.symbol == symbol.upper():
            return m.as_dict()
    return JSONResponse({"error": "not found"}, status_code=404)


@app.get("/api/plan/{symbol}")
def get_plan(symbol: str, account: float | None = None, risk_pct: float | None = None):
    """A full, sized trade plan for one symbol. `account` and `risk_pct` let a
    trader size the plan to their own book without touching config."""
    sym = symbol.upper()
    for m in snapshot.rows:
        if m.symbol == sym:
            return signals.build(m, account=account, risk_pct=risk_pct).as_dict()
    return JSONResponse({"error": "not found"}, status_code=404)


@app.get("/api/bars/{symbol}")
def get_bars(symbol: str, interval: str = "1m"):
    """Return session candles for the chart, served from the cached snapshot
    (refreshed on the background loop) so opening a chart never triggers an
    extra live fetch."""
    sym = symbol.upper()
    bars = snapshot.bars.get(sym)
    if not bars:                       # fall back to an on-demand fetch
        quotes = provider.get_quotes([sym])
        bars = quotes[0].bars if quotes else None
    if not bars:
        return JSONResponse({"error": "no data"}, status_code=404)
    if interval == "5m":
        bars = _resample(bars, 5)
    return {"symbol": sym, "interval": interval,
            "bars": [b.as_dict() for b in bars]}


def _resample(bars, minutes):
    from backend.models import Bar
    out = []
    for i in range(0, len(bars), minutes):
        chunk = bars[i:i + minutes]
        if not chunk:
            continue
        out.append(Bar(
            t=chunk[0].t, o=chunk[0].o,
            h=max(b.h for b in chunk), l=min(b.l for b in chunk),
            c=chunk[-1].c, v=sum(b.v for b in chunk),
        ))
    return out


# --- WebSocket ------------------------------------------------------------
@app.websocket("/ws")
async def ws(sock: WebSocket):
    await sock.accept()
    try:
        await sock.send_json(snapshot.payload())
        last = snapshot.updated
        while True:
            await asyncio.sleep(config.REFRESH_SECONDS)
            if snapshot.updated != last:
                last = snapshot.updated
                await sock.send_json(snapshot.payload())
    except WebSocketDisconnect:
        return
    except Exception:
        return


# --- static frontend ------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
