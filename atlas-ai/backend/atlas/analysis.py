"""Price-action toolkit: market structure, liquidity, supply/demand zones, session ranges.

All functions are causal: they only use bars up to the last index passed in. Swing points
are only "confirmed" ``right`` bars after they print, exactly as a discretionary trader would see them.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np

from . import indicators as ind
from .sessions import session_window_utc


@dataclass
class Swing:
    index: int
    price: float
    kind: str  # high | low


def swings(h: np.ndarray, l: np.ndarray, left: int = 3, right: int = 3) -> list[Swing]:
    ph, pl = ind.pivots(h, l, left, right)
    out = [Swing(i, float(h[i]), "high") for i in ph] + [Swing(i, float(l[i]), "low") for i in pl]
    return sorted(out, key=lambda s: s.index)


@dataclass
class Structure:
    trend: str  # bullish | bearish | range
    last_high: Swing | None
    last_low: Swing | None
    prev_high: Swing | None
    prev_low: Swing | None
    bos: str | None  # break of structure on the last bar: "bullish" | "bearish"
    detail: str


def market_structure(h, l, c, left: int = 3, right: int = 3) -> Structure:
    sw = swings(h, l, left, right)
    highs = [s for s in sw if s.kind == "high"]
    lows = [s for s in sw if s.kind == "low"]
    lh, ph = (highs[-1] if highs else None), (highs[-2] if len(highs) > 1 else None)
    ll, pl = (lows[-1] if lows else None), (lows[-2] if len(lows) > 1 else None)
    trend, detail = "range", "insufficient swings"
    if lh and ph and ll and pl:
        if lh.price > ph.price and ll.price > pl.price:
            trend, detail = "bullish", "higher highs and higher lows"
        elif lh.price < ph.price and ll.price < pl.price:
            trend, detail = "bearish", "lower highs and lower lows"
        else:
            detail = "mixed swings (range)"
    bos = None
    if lh and c[-1] > lh.price and (len(c) < 2 or c[-2] <= lh.price):
        bos = "bullish"
    elif ll and c[-1] < ll.price and (len(c) < 2 or c[-2] >= ll.price):
        bos = "bearish"
    return Structure(trend, lh, ll, ph, pl, bos, detail)


@dataclass
class Sweep:
    side: str  # "buy_side" (highs taken, bearish implication) | "sell_side" (lows taken, bullish implication)
    level: float
    level_name: str
    bar_index: int
    extreme: float


def detect_sweep(o, h, l, c, levels: dict[str, float], lookback: int = 3, min_pen: float = 0.0) -> Sweep | None:
    """Wick through a liquidity level followed by a close back on the other side within the last ``lookback`` bars."""
    n = len(c)
    for k in range(1, lookback + 1):
        i = n - k
        if i < 1:
            break
        for name, lvl in levels.items():
            if lvl is None:
                continue
            if h[i] > lvl + min_pen and c[i] < lvl and c[-1] < lvl:
                return Sweep("buy_side", float(lvl), name, i, float(h[i:].max()))
            if l[i] < lvl - min_pen and c[i] > lvl and c[-1] > lvl:
                return Sweep("sell_side", float(lvl), name, i, float(l[i:].min()))
    return None


@dataclass
class Zone:
    kind: str  # demand | supply
    top: float
    bottom: float
    index: int
    impulse_atr: float
    fresh: bool
    touches: int

    def contains(self, price: float, pad: float = 0.0) -> bool:
        return self.bottom - pad <= price <= self.top + pad


def supply_demand_zones(o, h, l, c, atr, lookback: int = 200, impulse_mult: float = 2.0, max_zones: int = 6) -> list[Zone]:
    """Base (small-bodied) candle(s) followed by an impulsive departure of >= impulse_mult × ATR within 3 bars."""
    n = len(c)
    start = max(20, n - lookback)
    zones: list[Zone] = []
    for i in range(start, n - 4):
        a = atr[i]
        if not np.isfinite(a) or a <= 0:
            continue
        body = abs(c[i] - o[i])
        if body > 0.6 * (h[i] - l[i] + 1e-12) and body > 0.5 * a:
            continue  # base candles are small-bodied
        move_up = h[i + 1:i + 4].max() - h[i]
        move_dn = l[i] - l[i + 1:i + 4].min()
        if move_up >= impulse_mult * a and c[i + 3] > h[i]:
            z = Zone("demand", float(max(o[i], c[i], (h[i] + l[i]) / 2)), float(l[i]), i, float(move_up / a), True, 0)
        elif move_dn >= impulse_mult * a and c[i + 3] < l[i]:
            z = Zone("supply", float(h[i]), float(min(o[i], c[i], (h[i] + l[i]) / 2)), i, float(move_dn / a), True, 0)
        else:
            continue
        # freshness: returns into the zone after the departure, excluding the last two bars (the potential
        # touch + confirmation candles); a close through the far side of the zone invalidates it
        after_l, after_h = l[i + 4:n - 2], h[i + 4:n - 2]
        if z.kind == "demand":
            z.touches = int((after_l <= z.top).sum())
            broken = bool((c[i + 4:n] < z.bottom).any())
        else:
            z.touches = int((after_h >= z.bottom).sum())
            broken = bool((c[i + 4:n] > z.top).any())
        if broken:
            continue
        z.fresh = z.touches == 0
        zones.append(z)
    zones.sort(key=lambda z: -z.index)
    return zones[:max_zones]


def day_levels(t_ms: np.ndarray, h, l, now_ms: int) -> dict[str, float | None]:
    """Previous UTC day's high/low and the current Asian (Tokyo) session range."""
    day = 86_400_000
    today = now_ms // day * day
    prev = (t_ms >= today - day) & (t_ms < today)
    out = {"prev_day_high": float(h[prev].max()) if prev.any() else None, "prev_day_low": float(l[prev].min()) if prev.any() else None}
    now = datetime.fromtimestamp(now_ms / 1000, timezone.utc)
    a0, a1 = session_window_utc(now, "Tokyo")
    if a0 > now:  # Tokyo session for "today" in Tokyo hasn't started → use the one that ended most recently
        a0, a1 = session_window_utc(now - timedelta(days=1), "Tokyo")
    m = (t_ms >= a0.timestamp() * 1000) & (t_ms < min(a1, now).timestamp() * 1000)
    out["asia_high"] = float(h[m].max()) if m.sum() >= 3 else None
    out["asia_low"] = float(l[m].min()) if m.sum() >= 3 else None
    out["asia_complete"] = bool(now >= a1)
    return out


def anchored_vwap(t_ms, h, l, c, v, anchor_ms: int) -> float | None:
    m = t_ms >= anchor_ms
    if m.sum() < 2:
        return None
    tp = (h[m] + l[m] + c[m]) / 3
    w = np.where(v[m] > 0, v[m], 1.0)  # FX tick volume can be 0 → equal weighting
    return float((tp * w).sum() / w.sum())


def round_level(price: float, step: float) -> tuple[float, float]:
    lo = np.floor(price / step) * step
    return float(lo), float(lo + step)
