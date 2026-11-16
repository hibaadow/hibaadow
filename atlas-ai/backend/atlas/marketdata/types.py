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
    volume: float  # tick volume / sample count (FX has no centralised volume)
    quote_volume: float = 0.0
    spread: float = 0.0  # average bid/ask spread in price units during the bar (0 = unknown)


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
    sp: np.ndarray | None = None

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
            np.array([x.spread for x in candles], dtype=float),
        )

    def __len__(self) -> int:
        return len(self.t)

    def slice(self, end: int, start: int = 0) -> "CandleSeries":
        """Bars [start, end) — used by the backtester to hide the future."""
        sp = self.sp[start:end] if self.sp is not None else None
        return CandleSeries(self.symbol, self.timeframe, self.venue, self.t[start:end], self.o[start:end], self.h[start:end],
                            self.l[start:end], self.c[start:end], self.v[start:end], self.qv[start:end], self.quality, sp)

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




def resample_candles(candles: list[Candle], tf: str) -> list[Candle]:
    """Aggregate lower-timeframe candles into ``tf`` buckets (UTC-aligned). The last bucket may be partial."""
    step = TF_MS[tf]
    out: list[Candle] = []
    for c in candles:
        b = c.open_time // step * step
        if out and out[-1].open_time == b:
            o = out[-1]
            n = o.quote_volume + 1  # count of sub-bars, used for the running spread mean
            o.high = max(o.high, c.high)
            o.low = min(o.low, c.low)
            o.close = c.close
            o.volume += c.volume
            o.spread = (o.spread * (n - 1) + c.spread) / n
            o.quote_volume = n
        else:
            out.append(Candle(b, c.open, c.high, c.low, c.close, c.volume, 1, c.spread))
    for o in out:
        o.quote_volume = 0.0
    return out


def complete_buckets(candles: list[Candle], tf: str, sub_tf: str, now_ms: int) -> list[Candle]:
    """Resample and keep only buckets that have fully closed."""
    step = TF_MS[tf]
    return [c for c in resample_candles(candles, tf) if c.open_time + step <= now_ms]
