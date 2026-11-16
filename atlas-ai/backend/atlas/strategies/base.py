"""Strategy interface. Strategies emit structured, evidence-backed signals; they never trade.

A tradeable signal must be supported by at least ``MIN_CONFLUENCE`` independent evidence
categories (e.g. trend + structure + momentum). A single indicator can never trigger a trade.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import numpy as np

from .. import indicators as ind
from ..marketdata.types import CandleSeries

MIN_CONFLUENCE = 3
CATEGORIES = ("trend", "structure", "momentum", "level", "liquidity", "volume", "vwap", "session", "macro")


@dataclass
class Signal:
    strategy: str
    symbol: str
    timeframe: str
    direction: str  # buy | sell | exit | none
    candle_time: int  # open time of the last CLOSED bar used
    entry: float | None = None
    stop: float | None = None
    targets: list[float] = field(default_factory=list)
    strength: float = 0.0  # 0..1 strategy conviction — NOT a probability
    features: dict = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)  # [{category, detail}]
    invalidation: list[str] = field(default_factory=list)
    tradeable: bool = True

    @property
    def side_sign(self) -> int:
        return 1 if self.direction == "buy" else -1

    @property
    def risk_per_unit(self) -> float | None:
        if self.entry is None or self.stop is None or self.direction not in ("buy", "sell"):
            return None
        return (self.entry - self.stop) * self.side_sign

    @property
    def rr(self) -> float | None:
        r = self.risk_per_unit
        if not r or r <= 0 or not self.targets:
            return None
        return (self.targets[0] - self.entry) * self.side_sign / r

    @property
    def categories(self) -> set[str]:
        return {e["category"] for e in self.evidence}

    def to_dict(self) -> dict:
        d = asdict(self)
        d["rr"] = self.rr
        return d


@dataclass
class StrategyContext:
    """Closed-candle data visible to a strategy at decision time."""

    symbol: str
    primary: CandleSeries
    htf: CandleSeries | None = None  # 1h
    htf2: CandleSeries | None = None  # 4h
    now_ms: int | None = None
    usd_strength: float | None = None  # derived currency-strength score for USD (+ = strong)
    strength: dict | None = None  # all currencies
    us10y_trend: str | None = None  # rising | falling | flat
    session: str | None = None  # active session label

    @property
    def now(self) -> int:
        return self.now_ms if self.now_ms is not None else int(self.primary.t[-1]) + 1


def clean(x, nd: int = 6):
    if x is None or (isinstance(x, (float, np.floating)) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(float(x), nd)


def htf_trend(series: CandleSeries | None, min_bars: int = 60) -> dict:
    if series is None or len(series) < min_bars:
        return {"trend": "unknown", "detail": f"insufficient higher-timeframe data ({0 if series is None else len(series)} bars)"}
    c = series.c
    e21, e50 = ind.ema(c, 21), ind.ema(c, 50)
    slope = (e50[-1] / e50[-6] - 1) * 100 if len(c) > 55 and not np.isnan(e50[-6]) else 0.0
    if c[-1] > e21[-1] > e50[-1] and slope > 0:
        trend = "up"
    elif c[-1] < e21[-1] < e50[-1] and slope < 0:
        trend = "down"
    else:
        trend = "range"
    return {"trend": trend, "ema21": clean(e21[-1]), "ema50": clean(e50[-1]), "ema50_slope_pct": clean(slope, 4), "bars": len(series)}


def aligned(trend: str, side: str) -> bool:
    return (trend == "up" and side == "buy") or (trend == "down" and side == "sell")


class Strategy:
    name = "base"
    label = "Base"
    min_bars = 150
    default_params: dict = {}
    param_grid: dict = {}
    instruments: tuple[str, ...] | None = None  # None = all supported instruments

    def __init__(self, params: dict | None = None):
        self.params = {**self.default_params, **(params or {})}

    def applies_to(self, symbol: str) -> bool:
        return self.instruments is None or symbol in self.instruments

    def evaluate(self, ctx: StrategyContext) -> Signal:
        raise NotImplementedError

    def none(self, ctx: StrategyContext, *reasons: str, **features) -> Signal:
        t = int(ctx.primary.t[-1]) if len(ctx.primary) else 0
        return Signal(self.name, ctx.symbol, ctx.primary.timeframe, "none", t, reasons=list(reasons), features=features)

    def exit(self, ctx: StrategyContext, exit_side: str, reason: str, **features) -> Signal:
        s = self.none(ctx, reason, **features)
        s.direction = "exit"
        s.features["exit_for"] = exit_side
        return s

    def make(self, ctx: StrategyContext, side: str, entry: float, stop: float, strength: float, evidence: list[tuple[str, str]],
             invalidation: list[str], features: dict, rr_targets=(2.0, 3.0)) -> Signal:
        ev = [{"category": c, "detail": d} for c, d in evidence]
        cats = {c for c, _ in evidence}
        if len(cats) < MIN_CONFLUENCE:
            return self.none(ctx, f"insufficient confluence ({len(cats)} of {MIN_CONFLUENCE} evidence categories: {', '.join(sorted(cats))})",
                             **features)
        sign = 1 if side == "buy" else -1
        r = (entry - stop) * sign
        if r <= 0:
            return self.none(ctx, "invalid stop placement", **features)
        targets = [entry + sign * k * r for k in rr_targets]
        return Signal(self.name, ctx.symbol, ctx.primary.timeframe, side, int(ctx.primary.t[-1]), clean(entry, 8), clean(stop, 8),
                      [clean(x, 8) for x in targets], round(max(0.0, min(1.0, strength)), 3), features,
                      [d for _, d in evidence], ev, invalidation)

    @staticmethod
    def atr_stop(side: str, entry: float, structural: float, atr: float, lo: float = 1.0, hi: float = 3.0) -> float:
        """Stop beyond the structural level, constrained to [lo, hi] × ATR from entry."""
        sign = 1 if side == "buy" else -1
        dist = (entry - structural) * sign
        dist = min(max(dist, lo * atr), hi * atr)
        return entry - sign * dist
