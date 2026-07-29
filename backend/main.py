"""FastAPI app: REST endpoints + a websocket that streams scans live.

Run with:  uvicorn backend.main:app --reload   (or ./run.sh)
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import config
from backend.engine import metrics as metrics_engine
from backend.engine import scanners
from backend.providers.factory import make_provider

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="Stock Scanner / Trade Ideas Dashboard")

provider, provider_name = make_provider(config.UNIVERSE)


class Snapshot:
    """Holds the latest computed state, refreshed on a background loop."""

    def __init__(self):
        self.rows: list[metrics_engine.Metrics] = []
        self.scans: dict[str, list[dict]] = {}
        self.news: list[dict] = []
        self.indices: list[dict] = []
        self.halts: list[dict] = []
        self.updated: float = 0.0
        self.provider = provider_name

    def refresh(self):
        quotes = provider.get_quotes(config.UNIVERSE)
        now = time.time()
        rows = [m for q in quotes if (m := metrics_engine.compute(q, now))]
        self.rows = rows
        self.scans = scanners.run_all(rows)
        self.news = [n.__dict__ for n in provider.get_news(30)]
        self.indices = [i.__dict__ for i in provider.get_indices()]
        halts_fn = getattr(provider, "get_halts", None)
        if halts_fn:
            self.halts = [h.__dict__ for h in halts_fn()]
        self.updated = now

    def payload(self) -> dict:
        return {
            "type": "snapshot",
            "provider": self.provider,
            "updated": self.updated,
            "server_time": time.time(),
            "scans": self.scans,
            "news": self.news,
            "indices": self.indices,
            "halts": self.halts,
            "focus": config.FOCUS,
        }


snapshot = Snapshot()


@app.on_event("startup")
async def _startup():
    snapshot.refresh()
    asyncio.create_task(_refresh_loop())


async def _refresh_loop():
    while True:
        await asyncio.sleep(config.REFRESH_SECONDS)
        try:
            await asyncio.to_thread(snapshot.refresh)
        except Exception as e:  # noqa: BLE001
            print(f"[refresh] error: {e}")


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


@app.get("/api/bars/{symbol}")
def get_bars(symbol: str, interval: str = "1m"):
    """Return session candles for the chart. interval: 1m or 5m."""
    quotes = provider.get_quotes([symbol.upper()])
    if not quotes or not quotes[0].bars:
        return JSONResponse({"error": "no data"}, status_code=404)
    bars = quotes[0].bars
    if interval == "5m":
        bars = _resample(bars, 5)
    return {"symbol": symbol.upper(), "interval": interval,
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
