"""Strategy interface. Strategies emit structured signals; they never trade."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import numpy as np

from .. import indicators as ind
from ..marketdata.types import CandleSeries


@dataclass
class Signal:
    strategy: str
    symbol: str
    timeframe: str
    direction: str  # long | exit | none
    candle_time: int  # open_time of the last CLOSED bar the signal was computed on
    entry: float | None = None
    stop: float | None = None
    targets: list[float] = field(default_factory=list)
    strength: float = 0.0  # 0..1, strategy-internal conviction (NOT a probability)
    features: dict = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    tradeable: bool = True

    @property
    def risk_per_unit(self) -> float | None:
        if self.entry is None or self.stop is None:
            return None
        return self.entry - self.stop

    @property
    def rr(self) -> float | None:
        r = self.risk_per_unit
        if not r or r <= 0 or not self.targets:
            return None
        return (self.targets[0] - self.entry) / r

    def to_dict(self) -> dict:
        d = asdict(self)
        d["rr"] = self.rr
        return d


@dataclass
class StrategyContext:
    """Closed-candle data visible to a strategy at decision time."""

    symbol: str
    primary: CandleSeries
    htf: CandleSeries | None = None  # higher timeframe trend filter (1h)
    htf2: CandleSeries | None = None  # 4h


def clean(x: float, nd: int = 6):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(float(x), nd)


def htf_trend(series: CandleSeries | None) -> dict:
    """Higher-timeframe trend classification from closed bars only."""
    if series is None or len(series) < 60:
        return {"trend": "unknown", "detail": "insufficient higher-timeframe data"}
    c = series.c
    e21, e50 = ind.ema(c, 21), ind.ema(c, 50)
    e200 = ind.ema(c, 200) if len(c) >= 200 else np.full_like(c, np.nan)
    last, a, b, z = c[-1], e21[-1], e50[-1], e200[-1]
    slope = (e50[-1] / e50[-6] - 1) * 100 if not np.isnan(e50[-6]) else 0.0
    if last > a > b and slope > 0:
        trend = "up"
    elif last < a < b and slope < 0:
        trend = "down"
    else:
        trend = "range"
    return {"trend": trend, "ema21": clean(a), "ema50": clean(b), "ema200": clean(z), "ema50_slope_pct": clean(slope, 4),
            "above_ema200": None if np.isnan(z) else bool(last > z)}


class Strategy:
    name = "base"
    label = "Base"
    min_bars = 220
    default_params: dict = {}
    param_grid: dict = {}

    def __init__(self, params: dict | None = None):
        self.params = {**self.default_params, **(params or {})}

    def evaluate(self, ctx: StrategyContext) -> Signal:
        raise NotImplementedError

    def none(self, ctx: StrategyContext, *reasons: str, **features) -> Signal:
        t = int(ctx.primary.t[-1]) if len(ctx.primary) else 0
        return Signal(self.name, ctx.symbol, ctx.primary.timeframe, "none", t, reasons=list(reasons), features=features)

    def make_long(self, ctx: StrategyContext, entry: float, stop: float, strength: float, reasons: list[str],
                  features: dict, rr_targets=(2.0, 3.0)) -> Signal:
        r = entry - stop
        targets = [entry + k * r for k in rr_targets]
        return Signal(self.name, ctx.symbol, ctx.primary.timeframe, "long", int(ctx.primary.t[-1]), clean(entry, 10),
                      clean(stop, 10), [clean(x, 10) for x in targets], round(max(0.0, min(1.0, strength)), 3),
                      features, reasons)

    def clamp_stop(self, entry: float, stop: float, atr: float, lo: float = 0.8, hi: float = 3.0) -> float:
        dist = entry - stop
        dist = min(max(dist, lo * atr), hi * atr)
        return entry - dist
