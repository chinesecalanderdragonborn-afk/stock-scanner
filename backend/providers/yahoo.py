"""Live market data provider backed by yfinance (Yahoo Finance).

No API key required, but it needs outbound network access to Yahoo's
endpoints. If Yahoo is unreachable, the factory in ``providers/__init__`` will
fall back to the simulator when PROVIDER is "auto".

Yahoo does not expose a real-time halt feed, so ``get_halts`` returns nothing;
the dashboard's halt panel is simply empty in live mode.
"""
from __future__ import annotations

import time

from backend.models import Bar, Halt, Index, NewsItem, Quote

_INDEX_SYMBOLS = [("DJIA", "^DJI"), ("S&P500", "^GSPC"),
                  ("NASDAQ", "^IXIC"), ("Oil", "CL=F")]


class YahooProvider:
    name = "yahoo"

    def __init__(self, universe=None):
        import yfinance as yf  # imported lazily so the sim works without it
        self._yf = yf
        self.universe = universe
        self._meta_cache: dict[str, dict] = {}
        self._meta_ts: dict[str, float] = {}

    def _meta(self, sym: str) -> dict:
        """Cache slow-changing reference data (float, name, prev close)."""
        now = time.time()
        if sym in self._meta_cache and now - self._meta_ts.get(sym, 0) < 900:
            return self._meta_cache[sym]
        info = {}
        try:
            fi = self._yf.Ticker(sym).get_fast_info()
            info = {
                "prev_close": float(fi.get("previousClose") or 0),
                "float_shares": float(fi.get("shares") or 0),
                "name": sym,
                "exchange": fi.get("exchange") or "NASDAQ",
            }
        except Exception:
            info = {"prev_close": 0, "float_shares": 0, "name": sym,
                    "exchange": "NASDAQ"}
        self._meta_cache[sym] = info
        self._meta_ts[sym] = now
        return info

    def get_quotes(self, symbols: list[str]) -> list[Quote]:
        yf = self._yf
        # Batch download 1-minute bars for the day for all symbols at once.
        data = yf.download(
            tickers=" ".join(symbols), period="1d", interval="1m",
            group_by="ticker", threads=True, progress=False, auto_adjust=False,
        )
        quotes: list[Quote] = []
        for sym in symbols:
            try:
                df = data[sym] if len(symbols) > 1 else data
                df = df.dropna()
            except Exception:
                continue
            bars: list[Bar] = []
            for ts, row in df.iterrows():
                bars.append(Bar(
                    t=int(ts.timestamp()),
                    o=float(row["Open"]), h=float(row["High"]),
                    l=float(row["Low"]), c=float(row["Close"]),
                    v=float(row["Volume"]),
                ))
            if not bars:
                continue
            m = self._meta(sym)
            avg_vol = 0.0
            try:
                avg_vol = float(self._yf.Ticker(sym).get_fast_info()
                                .get("threeMonthAverageVolume") or 0)
            except Exception:
                pass
            quotes.append(Quote(
                symbol=sym, name=m["name"], prev_close=m["prev_close"],
                float_shares=m["float_shares"], avg_volume=avg_vol or 1e6,
                exchange=m["exchange"], bars=bars,
            ))
        return quotes

    def get_halts(self) -> list[Halt]:
        return []  # Yahoo has no halt feed

    def get_news(self, limit: int = 30) -> list[NewsItem]:
        yf = self._yf
        out: list[NewsItem] = []
        symbols = (self.universe or [])[:8]
        for sym in symbols:
            try:
                for n in (yf.Ticker(sym).news or [])[:4]:
                    content = n.get("content", n)
                    title = content.get("title") or n.get("title", "")
                    pub = content.get("pubDate") or n.get("providerPublishTime")
                    t = int(time.time())
                    if isinstance(pub, (int, float)):
                        t = int(pub)
                    out.append(NewsItem(t=t, symbol=sym, headline=title,
                                        source=content.get("provider", {})
                                        .get("displayName", "")
                                        if isinstance(content.get("provider"), dict)
                                        else ""))
            except Exception:
                continue
        out.sort(key=lambda x: x.t, reverse=True)
        return out[:limit]

    def get_indices(self) -> list[Index]:
        out: list[Index] = []
        for name, sym in _INDEX_SYMBOLS:
            try:
                fi = self._yf.Ticker(sym).get_fast_info()
                last = float(fi.get("lastPrice") or 0)
                prev = float(fi.get("previousClose") or last)
                chg = (last - prev) / prev * 100 if prev else 0.0
                out.append(Index(name=name, last=round(last, 2),
                                 change_pct=round(chg, 2)))
            except Exception:
                out.append(Index(name=name, last=0.0, change_pct=0.0))
        return out
