"""Strategies A–D. All computations use closed bars only (no look-ahead)."""
from __future__ import annotations

import numpy as np

from .. import indicators as ind
from .base import Signal, Strategy, StrategyContext, clean, htf_trend


def _common(ctx: StrategyContext) -> dict:
    s = ctx.primary
    a = ind.atr(s.h, s.l, s.c, 14)
    return {"atr": a, "atr_last": float(a[-1]), "close": float(s.c[-1]),
            "atr_pct": float(a[-1] / s.c[-1] * 100) if s.c[-1] else float("nan")}


class TrendFollowing(Strategy):
    """Strategy A — trend continuation on pullbacks to the EMA21 in an EMA-stacked trend."""

    name = "trend_following"
    label = "Trend Following"
    default_params = {"stop_atr_mult": 1.5, "min_rel_volume": 1.0, "pullback_bars": 4}
    param_grid = {"stop_atr_mult": [1.2, 1.5, 2.0], "min_rel_volume": [0.8, 1.0, 1.3]}

    def evaluate(self, ctx: StrategyContext) -> Signal:
        s = ctx.primary
        if len(s) < self.min_bars:
            return self.none(ctx, f"need {self.min_bars} closed bars, have {len(s)}")
        c = s.c
        e9, e21, e50, e200 = ind.ema(c, 9), ind.ema(c, 21), ind.ema(c, 50), ind.ema(c, 200)
        line, sig, hist = ind.macd(c)
        rv = ind.relative_volume(s.v, 20)
        k = _common(ctx)
        atr = k["atr_last"]
        htf = htf_trend(ctx.htf)
        f = {"ema9": clean(e9[-1]), "ema21": clean(e21[-1]), "ema50": clean(e50[-1]), "ema200": clean(e200[-1]),
             "macd_hist": clean(hist[-1], 8), "rel_volume": clean(rv[-1], 3), "atr": clean(atr), "htf": htf}
        # Exit logic for open positions: trend structure broken.
        if c[-1] < e21[-1] and hist[-1] < 0 and hist[-2] < 0:
            sig_exit = self.none(ctx, "close below EMA21 with negative MACD histogram", **f)
            sig_exit.direction = "exit"
            return sig_exit
        stacked = e9[-1] > e21[-1] > e50[-1] and c[-1] > e200[-1]
        if not stacked:
            return self.none(ctx, "EMAs not stacked bullish (9>21>50, price>200)", **f)
        n = self.params["pullback_bars"]
        touched = bool((s.l[-n:] <= e21[-n:] * 1.002).any())
        resumed = c[-1] > e9[-1] and c[-1] > s.o[-1]
        if not touched:
            return self.none(ctx, "trend intact but no pullback to EMA21 — avoiding chasing extended price", **f)
        if not resumed:
            return self.none(ctx, "pullback in progress; waiting for a close back above EMA9", **f)
        macd_ok = hist[-1] > 0 or (hist[-1] > hist[-2] > hist[-3])
        if not macd_ok:
            return self.none(ctx, "MACD momentum not confirming continuation", **f)
        if not (rv[-1] >= self.params["min_rel_volume"]):
            return self.none(ctx, f"volume {rv[-1]:.2f}x average below {self.params['min_rel_volume']}x confirmation", **f)
        swing_low = float(s.l[-10:].min())
        stop = self.clamp_stop(c[-1], min(swing_low, e50[-1]) - 0.25 * atr, atr, 0.8, self.params["stop_atr_mult"] * 2)
        stop = max(stop, c[-1] - self.params["stop_atr_mult"] * 2 * atr)
        strength = 0.45 + 0.15 * (htf["trend"] == "up") + 0.1 * min(rv[-1] / 2, 1) + 0.1 * (hist[-1] > 0) \
            + 0.1 * ((e50[-1] / e50[-10] - 1) > 0) + 0.1 * (htf.get("above_ema200") is True)
        reasons = ["EMA 9>21>50 stacked and price above EMA200", f"pullback touched EMA21 within {n} bars and resumed above EMA9",
                   f"MACD histogram {hist[-1]:+.6g}", f"volume {rv[-1]:.2f}x 20-bar average", f"1h trend: {htf['trend']}"]
        return self.make_long(ctx, float(c[-1]), float(stop), strength, reasons, f)


class Momentum(Strategy):
    """Strategy B — developing momentum with RSI/MACD/volume confirmation and an overextension guard."""

    name = "momentum"
    label = "Momentum"
    default_params = {"rsi_low": 55, "rsi_high": 70, "min_rel_volume": 1.5, "stop_atr_mult": 1.5, "max_ext_atr": 2.5}
    param_grid = {"min_rel_volume": [1.3, 1.5, 2.0], "stop_atr_mult": [1.2, 1.5, 2.0]}

    def evaluate(self, ctx: StrategyContext) -> Signal:
        s = ctx.primary
        if len(s) < self.min_bars:
            return self.none(ctx, f"need {self.min_bars} closed bars, have {len(s)}")
        c = s.c
        r = ind.rsi(c, 14)
        line, sig, hist = ind.macd(c)
        rv = ind.relative_volume(s.v, 20)
        roc3 = ind.roc(c, 3)
        e21 = ind.ema(c, 21)
        k = _common(ctx)
        atr = k["atr_last"]
        ext = (c[-1] - e21[-1]) / atr if atr > 0 else np.inf
        htf = htf_trend(ctx.htf)
        f = {"rsi": clean(r[-1], 2), "macd": clean(line[-1], 8), "macd_signal": clean(sig[-1], 8), "rel_volume": clean(rv[-1], 3),
             "roc3": clean(roc3[-1], 4), "roc3_prev": clean(roc3[-2], 4), "extension_atr": clean(ext, 3), "atr": clean(atr), "htf": htf}
        if r[-1] < 45 or (line[-1] < sig[-1] and line[-2] >= sig[-2]):
            out = self.none(ctx, "momentum fading (RSI<45 or bearish MACD cross)", **f)
            out.direction = "exit"
            return out
        p = self.params
        if r[-1] > 75:
            return self.none(ctx, f"RSI {r[-1]:.1f} overextended (>75) — not buying exhaustion", **f)
        if not (p["rsi_low"] <= r[-1] <= p["rsi_high"] and r[-1] > r[-2]):
            return self.none(ctx, f"RSI {r[-1]:.1f} not in rising {p['rsi_low']}-{p['rsi_high']} momentum band", **f)
        crossed = any(line[-i] > sig[-i] and line[-i - 1] <= sig[-i - 1] for i in range(1, 4))
        if not (crossed and hist[-1] > 0):
            return self.none(ctx, "no fresh bullish MACD cross in last 3 bars", **f)
        if not (rv[-1] >= p["min_rel_volume"]):
            return self.none(ctx, f"relative volume {rv[-1]:.2f}x below {p['min_rel_volume']}x", **f)
        if not (roc3[-1] > 0 and roc3[-1] > roc3[-2]):
            return self.none(ctx, "price not accelerating (3-bar ROC not rising)", **f)
        if ext > p["max_ext_atr"]:
            return self.none(ctx, f"price {ext:.1f} ATR above EMA21 — overextended", **f)
        stop = c[-1] - p["stop_atr_mult"] * atr
        stop = min(stop, float(s.l[-3:].min()) - 0.1 * atr) if float(s.l[-3:].min()) - 0.1 * atr > c[-1] - 3 * atr else stop
        strength = 0.4 + 0.15 * (htf["trend"] == "up") + 0.15 * min(rv[-1] / 3, 1) + 0.15 * (1 - ext / p["max_ext_atr"]) + 0.15 * (60 <= r[-1] <= 68)
        reasons = [f"RSI {r[-1]:.1f} rising inside momentum band", "fresh bullish MACD cross", f"relative volume {rv[-1]:.2f}x",
                   f"3-bar ROC accelerating ({roc3[-2]:.2f}% → {roc3[-1]:.2f}%)", f"extension {ext:.2f} ATR above EMA21 (limit {p['max_ext_atr']})"]
        return self.make_long(ctx, float(c[-1]), float(stop), strength, reasons, f)


class Breakout(Strategy):
    """Strategy C — consolidation breakouts and retests with false-breakout filtering."""

    name = "breakout"
    label = "Breakout"
    default_params = {"range_bars": 24, "max_range_atr": 4.5, "min_rel_volume": 1.8, "buffer_pct": 0.05}
    param_grid = {"range_bars": [18, 24, 36], "min_rel_volume": [1.5, 1.8, 2.2]}

    def _range(self, s, end: int, n: int):
        return float(s.h[end - n:end].max()), float(s.l[end - n:end].min())

    def evaluate(self, ctx: StrategyContext) -> Signal:
        s = ctx.primary
        p = self.params
        n = p["range_bars"]
        if len(s) < self.min_bars:
            return self.none(ctx, f"need {self.min_bars} closed bars, have {len(s)}")
        c, h, l, o = s.c, s.h, s.l, s.o
        a = ind.atr(h, l, c, 14)
        atr = float(a[-1])
        atr50 = float(np.nanmean(a[-50:]))
        rv = ind.relative_volume(s.v, 20)
        sr = ind.support_resistance(h, l, c)
        htf = htf_trend(ctx.htf)
        # consolidation measured on bars BEFORE the breakout bar
        hi, lo = self._range(s, len(s) - 1, n)
        width_atr = (hi - lo) / atr if atr > 0 else np.inf
        compressed = width_atr <= p["max_range_atr"] and atr <= atr50 * 1.1
        f = {"range_high": clean(hi), "range_low": clean(lo), "range_width_atr": clean(width_atr, 3), "atr": clean(atr),
             "atr50": clean(atr50), "rel_volume": clean(rv[-1], 3), "resistance": sr["resistance"], "support": sr["support"], "htf": htf}
        # false-breakout history: breakouts above a rolling range that closed back inside within 3 bars
        failures = 0
        for i in range(len(s) - 60, len(s) - 4):
            rh = float(h[i - n:i].max())
            if c[i] > rh and (c[i + 1:i + 4] < rh).any():
                failures += 1
        f["recent_false_breakouts"] = failures
        bar_range = h[-1] - l[-1]
        close_pos = (c[-1] - l[-1]) / bar_range if bar_range > 0 else 0
        upper_wick = (h[-1] - max(c[-1], o[-1])) / bar_range if bar_range > 0 else 0
        level = hi * (1 + p["buffer_pct"] / 100)
        # Retest mode: breakout happened 2-6 bars ago, price came back to the level and held
        for j in range(2, 7):
            bh, bl = self._range(s, len(s) - j, n)
            if c[-j] > bh * (1 + p["buffer_pct"] / 100) and (bh - bl) / atr <= p["max_range_atr"] and rv[-j] >= p["min_rel_volume"]:
                touched = l[-1] <= bh * 1.003
                held = c[-1] > bh and c[-1] > o[-1]
                if touched and held and (c[-j + 1:] > bl).all():
                    stop = self.clamp_stop(c[-1], min(l[-1], bh) - 0.5 * atr, atr, 0.8, 2.5)
                    strength = 0.55 + 0.15 * (htf["trend"] == "up") + 0.15 * (failures == 0) + 0.15 * min(rv[-j] / 3, 1)
                    f.update(mode="retest", breakout_level=clean(bh), bars_since_breakout=j)
                    reasons = [f"breakout above {bh:.6g} {j} bars ago on {rv[-j]:.2f}x volume", "price retested the breakout level and held",
                               f"{failures} false breakouts in last 60 bars", f"1h trend: {htf['trend']}"]
                    return self.make_long(ctx, float(c[-1]), float(stop), strength, reasons, f)
        if not compressed:
            return self.none(ctx, f"no consolidation (range {width_atr:.1f} ATR, limit {p['max_range_atr']})", **f)
        if not c[-1] > level:
            return self.none(ctx, f"consolidating between {lo:.6g} and {hi:.6g}; no breakout yet", **f)
        if not rv[-1] >= p["min_rel_volume"]:
            return self.none(ctx, f"breakout on weak volume ({rv[-1]:.2f}x) — likely false breakout", **f)
        if close_pos < 0.7 or upper_wick > 0.4:
            return self.none(ctx, "breakout bar closed weak / large upper wick — rejection risk", **f)
        if failures >= 3:
            return self.none(ctx, f"{failures} recent false breakouts — level is unreliable", **f)
        stop = self.clamp_stop(c[-1], (hi + lo) / 2, atr, 1.0, 2.5)
        strength = 0.45 + 0.15 * (htf["trend"] == "up") + 0.15 * min(rv[-1] / 3, 1) + 0.15 * close_pos + 0.1 * (failures == 0)
        f["mode"] = "breakout"
        reasons = [f"{n}-bar consolidation {width_atr:.1f} ATR wide with ATR compression", f"close {c[-1]:.6g} broke range high {hi:.6g}",
                   f"breakout volume {rv[-1]:.2f}x average", f"strong close (top {100 * (1 - close_pos):.0f}% of bar)",
                   f"{failures} false breakouts in last 60 bars"]
        return self.make_long(ctx, float(c[-1]), float(stop), strength, reasons, f)


class VWAPReversion(Strategy):
    """Strategy D — long mean reversion after deep deviation below session VWAP, only outside strong downtrends."""

    name = "vwap_reversion"
    label = "VWAP Reversion"
    default_params = {"z_entry": -2.0, "rsi_max": 35, "max_adx": 30, "stop_atr": 0.6}
    param_grid = {"z_entry": [-1.75, -2.0, -2.5], "stop_atr": [0.5, 0.6, 0.8]}

    def evaluate(self, ctx: StrategyContext) -> Signal:
        s = ctx.primary
        p = self.params
        if len(s) < self.min_bars:
            return self.none(ctx, f"need {self.min_bars} closed bars, have {len(s)}")
        c = s.c
        vw, dev = ind.vwap(s.h, s.l, c, s.v, s.t)
        r = ind.rsi(c, 14)
        ax = ind.adx(s.h, s.l, c, 14)
        k = _common(ctx)
        atr = k["atr_last"]
        z = (c[-1] - vw[-1]) / dev[-1] if dev[-1] and dev[-1] > 0 else 0.0
        zp = (c[-2] - vw[-2]) / dev[-2] if dev[-2] and dev[-2] > 0 else 0.0
        htf = htf_trend(ctx.htf)
        bars_in_session = int(((s.t // 86_400_000) == (s.t[-1] // 86_400_000)).sum())
        f = {"vwap": clean(vw[-1]), "vwap_std": clean(dev[-1]), "z": clean(z, 3), "z_prev": clean(zp, 3), "rsi": clean(r[-1], 2),
             "adx": clean(ax[-1], 2), "atr": clean(atr), "bars_in_session": bars_in_session, "htf": htf}
        if c[-1] >= vw[-1]:
            out = self.none(ctx, "price at/above VWAP — mean reversion complete", **f)
            out.direction = "exit"
            return out
        if bars_in_session < 12:
            return self.none(ctx, "too early in session for a reliable VWAP", **f)
        if not (zp <= p["z_entry"] or z <= p["z_entry"]):
            return self.none(ctx, f"deviation z={z:.2f} not beyond {p['z_entry']}", **f)
        if not r[-1] <= p["rsi_max"] + 10 or not min(r[-3:]) <= p["rsi_max"]:
            return self.none(ctx, f"RSI not oversold (≤{p['rsi_max']}) recently", **f)
        if ax[-1] > p["max_adx"] and htf["trend"] == "down":
            return self.none(ctx, f"strong downtrend (ADX {ax[-1]:.0f}, 1h down) — reversion too dangerous", **f)
        reversal = c[-1] > s.o[-1] and c[-1] > c[-2] and z > zp
        if not reversal:
            return self.none(ctx, "waiting for a bullish reversal bar", **f)
        stop = float(s.l[-5:].min()) - p["stop_atr"] * atr
        stop = self.clamp_stop(c[-1], stop, atr, 0.7, 2.5)
        risk = c[-1] - stop
        room_r = (vw[-1] - c[-1]) / risk if risk > 0 else 0
        f["room_to_vwap_r"] = clean(room_r, 3)
        if room_r < 2.0:
            return self.none(ctx, f"distance to VWAP only {room_r:.2f}R — below 2R minimum", **f)
        strength = 0.45 + 0.15 * min(abs(zp) / 3, 1) + 0.15 * (htf["trend"] != "down") + 0.15 * (r[-1] < 40) + 0.1 * min(room_r / 4, 1)
        reasons = [f"price deviated {zp:.2f}σ below session VWAP", f"RSI {min(r[-3:]):.1f} oversold, now turning", "bullish reversal bar",
                   f"VWAP target {room_r:.2f}R away", f"ADX {ax[-1]:.0f}; 1h trend {htf['trend']}"]
        sig = self.make_long(ctx, float(c[-1]), float(stop), strength, reasons, f)
        sig.targets = [clean(c[-1] + 2 * risk, 10), clean(max(vw[-1], c[-1] + 2 * risk), 10)]
        return sig


STRATEGIES: dict[str, type[Strategy]] = {cls.name: cls for cls in (TrendFollowing, Momentum, Breakout, VWAPReversion)}


def build(name: str, params: dict | None = None) -> Strategy:
    return STRATEGIES[name](params)
