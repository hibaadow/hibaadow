"""No-credentials data source: live bid/ask from Swissquote's public quote feed.

* Quotes: ``/public-quotes/bboquotes/instrument/{BASE}/{QUOTE}``. The feed returns several
  platforms/spread profiles; ATLAS uses the median spread profile (conservative, not the tightest).
* Candles: there is no keyless intraday history API we can legitimately use, so 1-minute bars are
  BUILT from the sampled quotes (mid-price OHLC, average spread, sample count as volume) and
  persisted. Higher timeframes are resampled. History therefore accumulates from the moment ATLAS
  starts; strategies that need more bars than exist simply report "insufficient data".
  These are SAMPLED bars (one quote every few seconds), not full tick data — use a broker data
  source (OANDA / MT5) for precise candles and for backtesting.
"""
from __future__ import annotations

import statistics
import time

from ..config import get_settings
from ..instruments import INSTRUMENTS
from ..marketdata.http import ProviderClient, ProviderError
from ..marketdata.types import TF_MS, Candle, Quote, resample_candles


def pick_quote(symbol: str, payload) -> Quote | None:
    cands = []
    for entry in payload if isinstance(payload, list) else []:
        for prof in entry.get("spreadProfilePrices", []) if isinstance(entry, dict) else []:
            try:
                bid, ask = float(prof["bid"]), float(prof["ask"])
            except (KeyError, TypeError, ValueError):
                continue
            if bid > 0 and ask >= bid:
                cands.append((ask - bid, bid, ask, entry.get("ts")))
    if not cands:
        return None
    cands.sort()
    spread, bid, ask, ts = cands[len(cands) // 2]
    q = Quote(symbol, "public", bid, ask, (bid + ask) / 2)
    if isinstance(ts, (int, float)) and ts > 1e12:
        q.ts = min(time.time(), ts / 1000)  # use the feed's own timestamp to detect stale data
    return q


class BarBuilder:
    """Builds 1-minute mid-price bars from quote samples."""

    def __init__(self):
        self.bars: dict[str, list[Candle]] = {}
        self.current: dict[str, Candle] = {}
        self._spread_n: dict[str, int] = {}
        self.completed: list[tuple[str, Candle]] = []  # drained by the persistence layer

    def load(self, symbol: str, candles: list[Candle]) -> None:
        self.bars[symbol] = sorted(candles, key=lambda c: c.open_time)[-6000:]

    def add(self, q: Quote) -> None:
        t = int(q.ts * 1000) // 60_000 * 60_000
        mid, spr = q.mid, q.ask - q.bid
        cur = self.current.get(q.symbol)
        if cur is not None and cur.open_time != t:
            if t > cur.open_time:
                self.bars.setdefault(q.symbol, []).append(cur)
                self.bars[q.symbol] = self.bars[q.symbol][-6000:]
                self.completed.append((q.symbol, cur))
            cur = None
        if cur is None:
            self.current[q.symbol] = Candle(t, mid, mid, mid, mid, 1.0, 0.0, spr)
            self._spread_n[q.symbol] = 1
            return
        n = self._spread_n[q.symbol] + 1
        self._spread_n[q.symbol] = n
        cur.high, cur.low, cur.close = max(cur.high, mid), min(cur.low, mid), mid
        cur.volume += 1
        cur.spread = cur.spread + (spr - cur.spread) / n

    def candles(self, symbol: str, tf: str) -> list[Candle]:
        base = self.bars.get(symbol, [])
        if tf == "1m":
            return list(base)
        now = int(time.time() * 1000)
        step = TF_MS[tf]
        return [c for c in resample_candles([Candle(**{k: getattr(b, k) for k in Candle.__slots__}) for b in base], tf) if c.open_time + step <= now]


class PublicSource:
    name = "public"

    def __init__(self):
        s = get_settings()
        self.client = ProviderClient("public_quotes", s.public_quotes_url, rate_per_sec=2.0, burst=3, max_retries=1)
        self.builder = BarBuilder()

    async def quotes(self, symbols: list[str]) -> dict[str, Quote]:
        out = {}
        for sym in symbols:
            inst = INSTRUMENTS[sym]
            try:
                data = await self.client.get(f"/public-quotes/bboquotes/instrument/{inst.public_feed}")
            except ProviderError:
                continue
            q = pick_quote(sym, data)
            if q:
                out[sym] = q
                self.builder.add(q)
        return out

    async def candles(self, symbol: str, tf: str, count: int) -> list[Candle]:
        return self.builder.candles(symbol, tf)[-count:]

    def health(self) -> dict:
        return {"public_quotes": self.client.health()}

    async def close(self) -> None:
        await self.client.close()

    @staticmethod
    def spread_stats(samples: list[float]) -> float:
        return statistics.median(samples) if samples else 0.0
