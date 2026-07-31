"""Live market data provider backed by yfinance (Yahoo Finance).

No API key required, but it needs outbound network access. Designed to be
*fast and quiet*:

- Intraday 1-minute bars for the whole universe are pulled in a single batch
  ``yf.download`` call per refresh (not one call per ticker).
- Slow-changing reference data (previous close, average volume, float) is
  pulled in one batched daily download + a small parallel float lookup, and
  cached for an hour, so refreshes stay cheap.
- yfinance's chatty "possibly delisted" logging is silenced.

Yahoo exposes no real-time halt feed, so ``get_halts`` returns nothing.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor

from backend.models import Bar, Halt, Index, NewsItem, Quote

# Hush yfinance's per-ticker warnings; failures are handled gracefully here.
for _n in ("yfinance", "yfinance.utils", "yfinance.data"):
    logging.getLogger(_n).setLevel(logging.CRITICAL)

_INDEX_SYMBOLS = [("DJIA", "^DJI"), ("S&P500", "^GSPC"),
                  ("NASDAQ", "^IXIC"), ("Oil", "CL=F")]

_META_TTL = 3600      # seconds to cache prev_close / avg_volume / float


class YahooProvider:
    name = "yahoo"

    def __init__(self, universe=None):
        import yfinance as yf  # imported lazily so the sim works without it
        self._yf = yf
        self.universe = universe or []
        self._meta: dict[str, dict] = {}
        self._meta_ts = 0.0

    # -- reference data (cached, batched) ---------------------------------
    def _refresh_meta(self, symbols: list[str]) -> None:
        """Populate prev_close / avg_volume (one daily batch) + float."""
        yf = self._yf
        try:
            daily = yf.download(
                tickers=" ".join(symbols), period="1mo", interval="1d",
                group_by="ticker", threads=True, progress=False,
                auto_adjust=False,
            )
        except Exception:
            daily = None

        meta: dict[str, dict] = {}
        for sym in symbols:
            prev_close, avg_vol = 0.0, 0.0
            try:
                df = (daily[sym] if daily is not None and len(symbols) > 1
                      else daily).dropna()
                closes = df["Close"].tolist()
                vols = df["Volume"].tolist()
                if len(closes) >= 2:
                    prev_close = float(closes[-2])   # yesterday's close
                elif closes:
                    prev_close = float(closes[-1])
                if vols:
                    tail = vols[-20:-1] or vols[-20:]
                    avg_vol = float(sum(tail) / len(tail))
            except Exception:
                pass
            meta[sym] = {"prev_close": prev_close,
                         "avg_volume": avg_vol or 1e6,
                         "float_shares": self._meta.get(sym, {}).get("float_shares", 0.0),
                         "name": sym, "exchange": "NASDAQ"}

        # Float / shares outstanding in parallel (best-effort).
        def _flt(sym):
            try:
                fi = yf.Ticker(sym).get_fast_info()
                return sym, float(fi.get("shares") or 0)
            except Exception:
                return sym, 0.0

        try:
            with ThreadPoolExecutor(max_workers=8) as pool:
                for sym, shares in pool.map(_flt, symbols):
                    if sym in meta:
                        meta[sym]["float_shares"] = shares
        except Exception:
            pass

        self._meta = meta
        self._meta_ts = time.time()

    def _ensure_meta(self, symbols: list[str]) -> None:
        if not self._meta or time.time() - self._meta_ts > _META_TTL:
            self._refresh_meta(symbols)

    # -- provider API ------------------------------------------------------
    def _download(self, symbols, period, interval):
        return self._yf.download(
            tickers=" ".join(symbols), period=period, interval=interval,
            group_by="ticker", threads=True, progress=False, auto_adjust=False,
        )

    def get_quotes(self, symbols: list[str]) -> list[Quote]:
        self._ensure_meta(symbols)
        # Intraday first; if the market's been closed a while and 1-min data is
        # empty, fall back to coarser bars so the dashboard still populates.
        data = self._download(symbols, "1d", "1m")
        if data is None or getattr(data, "empty", True):
            data = self._download(symbols, "5d", "5m")
        quotes: list[Quote] = []
        for sym in symbols:
            try:
                df = (data[sym] if len(symbols) > 1 else data).dropna()
            except Exception:
                continue
            bars: list[Bar] = []
            for ts, row in df.iterrows():
                if row["Volume"] == 0 and row["Open"] == row["Close"]:
                    continue
                bars.append(Bar(
                    t=int(ts.timestamp()),
                    o=float(row["Open"]), h=float(row["High"]),
                    l=float(row["Low"]), c=float(row["Close"]),
                    v=float(row["Volume"]),
                ))
            if not bars:
                continue
            m = self._meta.get(sym, {})
            quotes.append(Quote(
                symbol=sym, name=m.get("name", sym),
                prev_close=m.get("prev_close") or bars[0].o,
                float_shares=m.get("float_shares", 0.0),
                avg_volume=m.get("avg_volume") or 1e6,
                exchange=m.get("exchange", "NASDAQ"), bars=bars,
            ))
        return quotes

    def get_halts(self) -> list[Halt]:
        return []  # Yahoo has no halt feed

    def get_news(self, limit: int = 30) -> list[NewsItem]:
        yf = self._yf
        out: list[NewsItem] = []
        for sym in (self.universe or [])[:8]:
            try:
                for n in (yf.Ticker(sym).news or [])[:4]:
                    content = n.get("content", n)
                    title = content.get("title") or n.get("title", "")
                    if not title:
                        continue
                    pub = content.get("pubDate") or n.get("providerPublishTime")
                    t = int(pub) if isinstance(pub, (int, float)) else int(time.time())
                    prov = content.get("provider")
                    src = prov.get("displayName", "") if isinstance(prov, dict) else ""
                    out.append(NewsItem(t=t, symbol=sym, headline=title, source=src))
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
