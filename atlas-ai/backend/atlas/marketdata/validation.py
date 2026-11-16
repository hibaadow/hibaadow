"""Candle validation: sanity checks, duplicate removal, gap and staleness detection.

External API responses are untrusted. Anything that fails validation is dropped
and counted, and the series is marked unusable for trading if quality is poor.
"""
from __future__ import annotations

import math
import time

from .types import TF_MS, Candle

MAX_BAR_RANGE_PCT = 60.0  # a single bar moving >60% high-low is treated as corrupt for majors


def _finite(*xs: float) -> bool:
    return all(isinstance(x, (int, float)) and math.isfinite(x) for x in xs)


def validate_candles(candles: list[Candle], timeframe: str, now_ms: int | None = None,
                     drop_open: bool = True) -> tuple[list[Candle], dict]:
    """Return (clean_closed_candles, quality_report)."""
    step = TF_MS[timeframe]
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    report = {"received": len(candles), "invalid": 0, "duplicates": 0, "misaligned": 0, "gaps": 0,
              "missing_bars": 0, "dropped_open_bar": False, "stale": False, "usable": True, "issues": []}
    seen: dict[int, Candle] = {}
    for c in candles:
        if not _finite(c.open, c.high, c.low, c.close, c.volume) or c.open_time <= 0:
            report["invalid"] += 1
            continue
        if min(c.open, c.high, c.low, c.close) <= 0 or c.volume < 0:
            report["invalid"] += 1
            continue
        if c.high < max(c.open, c.close) or c.low > min(c.open, c.close) or c.high < c.low:
            report["invalid"] += 1
            continue
        if (c.high - c.low) / c.low * 100 > MAX_BAR_RANGE_PCT:
            report["invalid"] += 1
            continue
        if c.open_time % step != 0:
            report["misaligned"] += 1
            continue
        if c.open_time in seen:
            report["duplicates"] += 1
            # keep the version with greater volume (later update of same bar)
            if c.volume >= seen[c.open_time].volume:
                seen[c.open_time] = c
            continue
        seen[c.open_time] = c
    out = sorted(seen.values(), key=lambda x: x.open_time)
    if drop_open and out and out[-1].open_time + step > now_ms:
        out.pop()  # still-forming bar: never used for decisions
        report["dropped_open_bar"] = True
    for a, b in zip(out, out[1:]):
        diff = b.open_time - a.open_time
        if diff > step:
            report["gaps"] += 1
            report["missing_bars"] += diff // step - 1
    if out:
        last_close = out[-1].open_time + step
        # stale if the most recent closed bar is more than 2 intervals old
        if now_ms - last_close > 2 * step + 5_000:
            report["stale"] = True
            report["issues"].append(f"latest closed {timeframe} bar ended {(now_ms - last_close) / 1000:.0f}s ago")
    else:
        report["issues"].append("no valid candles")
    if report["invalid"]:
        report["issues"].append(f"{report['invalid']} invalid candles rejected")
    if report["duplicates"]:
        report["issues"].append(f"{report['duplicates']} duplicate candles removed")
    if report["missing_bars"]:
        report["issues"].append(f"{report['missing_bars']} missing bars across {report['gaps']} gaps")
    total = max(len(out), 1)
    report["usable"] = bool(out) and not report["stale"] and report["missing_bars"] / total <= 0.02 \
        and report["invalid"] <= max(2, 0.02 * report["received"])
    report["count"] = len(out)
    return out, report


def recent_window_complete(candles: list[Candle], timeframe: str, window: int = 60) -> bool:
    """True if the last ``window`` bars are contiguous (no missing candles)."""
    step = TF_MS[timeframe]
    tail = candles[-window:]
    return all(b.open_time - a.open_time == step for a, b in zip(tail, tail[1:]))
