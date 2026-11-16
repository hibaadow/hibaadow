from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

TF_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


@dataclass(slots=True)
class Candle:
    open_time: int  # ms epoch, start of the bar
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float = 0.0


@dataclass
class CandleSeries:
    """Columnar candle data for one symbol/timeframe — only CLOSED candles."""

    symbol: str
    timeframe: str
    venue: str
    t: np.ndarray
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray
    qv: np.ndarray
    quality: dict = field(default_factory=dict)

    @classmethod
    def from_candles(cls, symbol: str, timeframe: str, venue: str, candles: list[Candle], quality: dict | None = None):
        return cls(
            symbol,
            timeframe,
            venue,
            np.array([x.open_time for x in candles], dtype=np.int64),
            np.array([x.open for x in candles], dtype=float),
            np.array([x.high for x in candles], dtype=float),
            np.array([x.low for x in candles], dtype=float),
            np.array([x.close for x in candles], dtype=float),
            np.array([x.volume for x in candles], dtype=float),
            np.array([x.quote_volume for x in candles], dtype=float),
            quality or {},
        )

    def __len__(self) -> int:
        return len(self.t)

    def slice(self, end: int, start: int = 0) -> "CandleSeries":
        """Bars [start, end) — used by the backtester to hide the future."""
        return CandleSeries(self.symbol, self.timeframe, self.venue, self.t[start:end], self.o[start:end], self.h[start:end],
                            self.l[start:end], self.c[start:end], self.v[start:end], self.qv[start:end], self.quality)

    @property
    def last_close_time(self) -> int | None:
        if not len(self.t):
            return None
        return int(self.t[-1]) + TF_MS[self.timeframe]


@dataclass
class Quote:
    symbol: str
    venue: str
    bid: float
    ask: float
    last: float
    ts: float = field(default_factory=time.time)  # seconds epoch of receipt

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2

    @property
    def spread_bps(self) -> float:
        m = self.mid
        return (self.ask - self.bid) / m * 1e4 if m > 0 else float("inf")

    def age(self, now: float | None = None) -> float:
        return (now or time.time()) - self.ts


@dataclass
class MarketStats:
    symbol: str
    venue: str
    price_change_pct_24h: float
    volume_base_24h: float
    volume_quote_24h: float
    high_24h: float
    low_24h: float
    ts: float = field(default_factory=time.time)


@dataclass
class Depth:
    symbol: str
    bid_depth_1pct_usd: float
    ask_depth_1pct_usd: float
    ts: float = field(default_factory=time.time)

    @property
    def liquidity_usd(self) -> float:
        return min(self.bid_depth_1pct_usd, self.ask_depth_1pct_usd)
