"""Exchange market-data adapters (public endpoints, no API keys required).

* Binance (spot, via the public market-data mirror data-api.binance.vision):
  primary venue for candles, top-of-book and depth for USDC pairs.
* Coinbase Exchange: REST candles fallback + reference prices.
* Kraken: REST candles fallback + reference prices.
"""
from __future__ import annotations

import time

from ..config import get_settings
from .http import ProviderClient, ProviderError
from .types import TF_MS, Candle, Depth, MarketStats, Quote

QUOTES = ("USDC", "USDT", "USD")


def split_symbol(symbol: str) -> tuple[str, str]:
    for q in QUOTES:
        if symbol.endswith(q) and len(symbol) > len(q):
            return symbol[: -len(q)], q
    raise ValueError(f"cannot split symbol {symbol}")


def _num(x) -> float:
    v = float(x)
    if v != v or v in (float("inf"), float("-inf")):
        raise ValueError("non-finite number")
    return v


class BinanceMarketData:
    venue = "binance"
    INTERVALS = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h", "4h": "4h", "1d": "1d"}

    def __init__(self, client: ProviderClient | None = None):
        s = get_settings()
        self.client = client or ProviderClient("binance", s.binance_rest_url, rate_per_sec=8, burst=20)

    async def candles(self, symbol: str, timeframe: str, limit: int = 500, start_ms: int | None = None,
                      end_ms: int | None = None) -> list[Candle]:
        data = await self.client.get("/api/v3/klines", symbol=symbol, interval=self.INTERVALS[timeframe],
                                     limit=min(limit, 1000), startTime=start_ms, endTime=end_ms)
        if not isinstance(data, list):
            raise ProviderError("binance", "unexpected klines shape")
        out = []
        for row in data:
            try:
                out.append(Candle(int(row[0]), _num(row[1]), _num(row[2]), _num(row[3]), _num(row[4]), _num(row[5]), _num(row[7])))
            except (ValueError, TypeError, IndexError):
                continue  # counted by validation as missing
        return out

    async def history(self, symbol: str, timeframe: str, start_ms: int, end_ms: int, max_bars: int = 50_000) -> list[Candle]:
        out: list[Candle] = []
        cursor = start_ms
        step = TF_MS[timeframe]
        while cursor < end_ms and len(out) < max_bars:
            batch = await self.candles(symbol, timeframe, 1000, start_ms=cursor, end_ms=end_ms)
            if not batch:
                break
            out.extend(batch)
            nxt = batch[-1].open_time + step
            if nxt <= cursor:
                break
            cursor = nxt
        return out

    async def quote(self, symbol: str) -> Quote:
        d = await self.client.get("/api/v3/ticker/bookTicker", symbol=symbol)
        bid, ask = _num(d["bidPrice"]), _num(d["askPrice"])
        if bid <= 0 or ask <= 0 or ask < bid:
            raise ProviderError("binance", f"invalid book for {symbol}")
        return Quote(symbol, self.venue, bid, ask, (bid + ask) / 2)

    async def quotes(self, symbols: list[str]) -> dict[str, Quote]:
        import json as _json

        d = await self.client.get("/api/v3/ticker/bookTicker", symbols=_json.dumps(symbols, separators=(",", ":")))
        out = {}
        for row in d if isinstance(d, list) else []:
            try:
                bid, ask = _num(row["bidPrice"]), _num(row["askPrice"])
                if bid > 0 and ask >= bid:
                    out[row["symbol"]] = Quote(row["symbol"], self.venue, bid, ask, (bid + ask) / 2)
            except (KeyError, ValueError, TypeError):
                continue
        return out

    async def stats_24h(self, symbols: list[str]) -> dict[str, MarketStats]:
        import json as _json

        d = await self.client.get("/api/v3/ticker/24hr", symbols=_json.dumps(symbols, separators=(",", ":")))
        out = {}
        for row in d if isinstance(d, list) else []:
            try:
                out[row["symbol"]] = MarketStats(row["symbol"], self.venue, _num(row["priceChangePercent"]), _num(row["volume"]),
                                                 _num(row["quoteVolume"]), _num(row["highPrice"]), _num(row["lowPrice"]))
            except (KeyError, ValueError, TypeError):
                continue
        return out

    async def depth(self, symbol: str) -> Depth:
        d = await self.client.get("/api/v3/depth", symbol=symbol, limit=500)
        bids = [(float(p), float(q)) for p, q in d.get("bids", [])]
        asks = [(float(p), float(q)) for p, q in d.get("asks", [])]
        if not bids or not asks:
            raise ProviderError("binance", f"empty book for {symbol}")
        mid = (bids[0][0] + asks[0][0]) / 2
        bd = sum(p * q for p, q in bids if p >= mid * 0.99)
        ad = sum(p * q for p, q in asks if p <= mid * 1.01)
        return Depth(symbol, bd, ad)


class CoinbaseMarketData:
    venue = "coinbase"
    GRAN = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}

    def __init__(self, client: ProviderClient | None = None):
        s = get_settings()
        self.client = client or ProviderClient("coinbase", s.coinbase_rest_url, rate_per_sec=4, burst=8)

    @staticmethod
    def product(symbol: str) -> str:
        base, _ = split_symbol(symbol)
        return f"{base}-USD"  # Coinbase unified USDC into USD books

    async def candles(self, symbol: str, timeframe: str, limit: int = 300) -> list[Candle]:
        if timeframe not in self.GRAN:
            raise ProviderError("coinbase", f"timeframe {timeframe} unsupported")
        data = await self.client.get(f"/products/{self.product(symbol)}/candles", granularity=self.GRAN[timeframe])
        if not isinstance(data, list):
            raise ProviderError("coinbase", "unexpected candles shape")
        out = []
        for row in data[:limit]:  # [time, low, high, open, close, volume], newest first
            try:
                out.append(Candle(int(row[0]) * 1000, _num(row[3]), _num(row[2]), _num(row[1]), _num(row[4]), _num(row[5]), _num(row[5]) * _num(row[4])))
            except (ValueError, TypeError, IndexError):
                continue
        return sorted(out, key=lambda c: c.open_time)

    async def quote(self, symbol: str) -> Quote:
        d = await self.client.get(f"/products/{self.product(symbol)}/ticker")
        bid, ask, last = _num(d["bid"]), _num(d["ask"]), _num(d["price"])
        return Quote(symbol, self.venue, bid, ask, last)


class KrakenMarketData:
    venue = "kraken"
    INTERVAL = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240}
    BASE_ALIASES = {"BTC": "XBT"}

    def __init__(self, client: ProviderClient | None = None):
        s = get_settings()
        self.client = client or ProviderClient("kraken", s.kraken_rest_url, rate_per_sec=1, burst=3)

    def pair(self, symbol: str) -> str:
        base, _ = split_symbol(symbol)
        return f"{self.BASE_ALIASES.get(base, base)}USD"

    async def candles(self, symbol: str, timeframe: str, limit: int = 500) -> list[Candle]:
        d = await self.client.get("/0/public/OHLC", pair=self.pair(symbol), interval=self.INTERVAL[timeframe])
        if d.get("error"):
            raise ProviderError("kraken", "; ".join(d["error"])[:200])
        result = d.get("result", {})
        rows = next((v for k, v in result.items() if k != "last"), [])
        out = []
        for row in rows[-limit:]:  # [time, open, high, low, close, vwap, volume, count]
            try:
                out.append(Candle(int(row[0]) * 1000, _num(row[1]), _num(row[2]), _num(row[3]), _num(row[4]), _num(row[6]), _num(row[6]) * _num(row[5])))
            except (ValueError, TypeError, IndexError):
                continue
        return out

    async def quote(self, symbol: str) -> Quote:
        d = await self.client.get("/0/public/Ticker", pair=self.pair(symbol))
        if d.get("error"):
            raise ProviderError("kraken", "; ".join(d["error"])[:200])
        row = next(iter(d["result"].values()))
        return Quote(symbol, self.venue, _num(row["b"][0]), _num(row["a"][0]), _num(row["c"][0]))


def now_ms() -> int:
    return int(time.time() * 1000)
