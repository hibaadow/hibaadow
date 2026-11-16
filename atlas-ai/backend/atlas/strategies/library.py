"""Gold & forex strategies. All computations use closed bars only (no look-ahead).

1. trend_pullback   — multi-timeframe trend following with pullback entries
2. breakout_retest  — consolidation breakout, retest entry, false-breakout filter
3. liquidity_sweep  — stop-run through a liquidity pool + market-structure shift
4. supply_demand    — first return to a fresh supply/demand zone with rejection
5. gold_session     — XAU/USD London/New York session model (Asian range sweep/breakout, USD & yields)
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from .. import analysis as an
from .. import indicators as ind
from ..instruments import GOLD, INSTRUMENTS
from ..sessions import LDN, NY, active_sessions
from .base import Signal, Strategy, StrategyContext, aligned, clean, htf_trend


def _base(ctx: StrategyContext) -> dict:
    s = ctx.primary
    a = ind.atr(s.h, s.l, s.c, 14)
    return {"atr": a, "atr_last": float(a[-1]), "close": float(s.c[-1])}


def _vwap_session(ctx: StrategyContext) -> float | None:
    """VWAP anchored at today's London open (the institutional session start for gold & FX)."""
    s = ctx.primary
    now = datetime.fromtimestamp(ctx.now / 1000, timezone.utc)
    lo = now.astimezone(LDN).replace(hour=8, minute=0, second=0, microsecond=0)
    if lo > now:
        return None
    return an.anchored_vwap(s.t, s.h, s.l, s.c, s.v, int(lo.timestamp() * 1000))


def _bias(ctx: StrategyContext) -> tuple[str, dict, dict]:
    h1, h4 = htf_trend(ctx.htf), htf_trend(ctx.htf2, min_bars=40)
    if h1["trend"] in ("up", "down") and h4["trend"] in (h1["trend"], "range", "unknown"):
        return h1["trend"], h1, h4
    return "none", h1, h4


def _vol_ok(s, i=-1, mult=1.2) -> tuple[bool, float | None]:
    if s.v[-25:].sum() <= 0:
        return False, None
    rv = ind.relative_volume(s.v, 20)
    return bool(rv[i] >= mult), clean(rv[i], 2)


class TrendPullback(Strategy):
    name = "trend_pullback"
    label = "Trend Following · Pullback"
    default_params = {"pullback_bars": 5, "stop_atr_min": 1.0, "stop_atr_max": 2.5, "rsi_floor": 40.0}
    param_grid = {"stop_atr_min": [0.8, 1.0, 1.3], "pullback_bars": [4, 6]}

    def evaluate(self, ctx: StrategyContext) -> Signal:
        s = ctx.primary
        if len(s) < self.min_bars:
            return self.none(ctx, f"need {self.min_bars} closed bars, have {len(s)}")
        c, o, h, l = s.c, s.o, s.h, s.l
        e9, e21, e50 = ind.ema(c, 9), ind.ema(c, 21), ind.ema(c, 50)
        rsi = ind.rsi(c, 14)
        _, _, hist = ind.macd(c)
        k = _base(ctx)
        atr = k["atr_last"]
        bias, h1, h4 = _bias(ctx)
        st = an.market_structure(h, l, c)
        vw = _vwap_session(ctx)
        f = {"h1": h1, "h4": h4, "structure": st.trend, "ema21": clean(e21[-1]), "ema50": clean(e50[-1]), "rsi": clean(rsi[-1], 1),
             "macd_hist": clean(hist[-1], 8), "atr": clean(atr), "vwap": clean(vw)}
        # exits for open positions: structure flips against the trade
        if c[-1] < e50[-1] and st.bos == "bearish":
            return self.exit(ctx, "buy", "bearish break of structure below EMA50", **f)
        if c[-1] > e50[-1] and st.bos == "bullish":
            return self.exit(ctx, "sell", "bullish break of structure above EMA50", **f)
        if bias == "none":
            return self.none(ctx, f"no clear higher-timeframe trend (1h {h1['trend']}, 4h {h4['trend']})", **f)
        side = "buy" if bias == "up" else "sell"
        sg = 1 if side == "buy" else -1
        n = self.params["pullback_bars"]
        if sg * (e21[-1] - e50[-1]) <= 0:
            return self.none(ctx, f"{s.timeframe} EMAs not aligned with the {bias} trend", **f)
        touched = bool(((l[-n:] <= e21[-n:] * (1 + 0.0002)) if side == "buy" else (h[-n:] >= e21[-n:] * (1 - 0.0002))).any())
        if not touched:
            return self.none(ctx, f"trend intact, waiting for a pullback to the EMA21/50 value area", **f)
        resumed = (c[-1] > e9[-1] and c[-1] > o[-1]) if side == "buy" else (c[-1] < e9[-1] and c[-1] < o[-1])
        if not resumed:
            return self.none(ctx, "pullback in progress — waiting for a resumption candle", **f)
        mom_ok = (rsi[-1] > rsi[-2] and self.params["rsi_floor"] <= rsi[-1] <= 70) if side == "buy" else \
                 (rsi[-1] < rsi[-2] and 30 <= rsi[-1] <= 100 - self.params["rsi_floor"])
        ev = [("trend", f"1h trend {h1['trend']}, 4h {h4['trend']}"),
              ("level", f"pullback into EMA21 ({e21[-1]:.5g}) value area within {n} bars")]
        if st.trend == ("bullish" if side == "buy" else "bearish"):
            ev.append(("structure", f"{s.timeframe} structure {st.trend} ({st.detail})"))
        if mom_ok and sg * hist[-1] > sg * hist[-2]:
            ev.append(("momentum", f"RSI turning {'up' if side == 'buy' else 'down'} ({rsi[-2]:.0f}→{rsi[-1]:.0f}) with MACD histogram improving"))
        if vw and sg * (c[-1] - vw) > 0:
            ev.append(("vwap", f"price on the {'bullish' if side == 'buy' else 'bearish'} side of London-anchored VWAP {vw:.5g}"))
        swing = float(l[-n - 2:].min()) if side == "buy" else float(h[-n - 2:].max())
        stop = self.atr_stop(side, float(c[-1]), swing - sg * 0.25 * atr, atr, self.params["stop_atr_min"], self.params["stop_atr_max"])
        strength = 0.35 + 0.1 * len(ev) + 0.1 * (h4["trend"] == h1["trend"])
        inval = [f"{s.timeframe} close {'below' if side == 'buy' else 'above'} {stop:.5g} (pullback {'low' if side == 'buy' else 'high'})",
                 f"1h close back {'below' if side == 'buy' else 'above'} EMA50 ({h1.get('ema50')})"]
        return self.make(ctx, side, float(c[-1]), stop, strength, ev, inval, f)


class BreakoutRetest(Strategy):
    name = "breakout_retest"
    label = "Breakout · Retest"
    default_params = {"range_bars": 24, "max_range_atr": 4.5, "min_body_atr": 0.6, "max_wait": 8}
    param_grid = {"range_bars": [18, 24, 36], "max_range_atr": [3.5, 4.5]}

    def evaluate(self, ctx: StrategyContext) -> Signal:
        s = ctx.primary
        p = self.params
        if len(s) < self.min_bars:
            return self.none(ctx, f"need {self.min_bars} closed bars, have {len(s)}")
        c, o, h, l = s.c, s.o, s.h, s.l
        k = _base(ctx)
        a, atr = k["atr"], k["atr_last"]
        bias, h1, h4 = _bias(ctx)
        n = p["range_bars"]
        f = {"h1": h1, "atr": clean(atr)}
        for j in range(2, p["max_wait"] + 1):  # breakout happened j bars ago
            b = len(s) - j
            hi, lo = float(h[b - n:b].max()), float(l[b - n:b].min())
            width = (hi - lo) / a[b] if a[b] > 0 else 99
            if width > p["max_range_atr"]:
                continue
            body = abs(c[b] - o[b])
            for side, lvl, broke in (("buy", hi, c[b] > hi), ("sell", lo, c[b] < lo)):
                if not broke or body < p["min_body_atr"] * a[b]:
                    continue
                sg = 1 if side == "buy" else -1
                after = c[b + 1:]
                if (sg * (after - lvl) < 0).any():
                    return self.none(ctx, f"breakout of {lvl:.5g} failed (closed back inside) — false breakout", **f)
                touched = (l[-1] <= lvl + 0.15 * atr) if side == "buy" else (h[-1] >= lvl - 0.15 * atr)
                held = sg * (c[-1] - lvl) > 0 and sg * (c[-1] - o[-1]) > 0
                if not (touched and held):
                    return self.none(ctx, f"{side} breakout of {lvl:.5g} {j} bars ago; waiting for a retest that holds", **f)
                fails = 0
                for i in range(len(s) - 80, len(s) - n - 4):
                    rh, rl = h[i - n:i].max(), l[i - n:i].min()
                    if (c[i] > rh and (c[i + 1:i + 4] < rh).any()) or (c[i] < rl and (c[i + 1:i + 4] > rl).any()):
                        fails += 1
                ev = [("structure", f"{n}-bar consolidation {width:.1f} ATR wide broken {'up' if side == 'buy' else 'down'} {j} bars ago"),
                      ("momentum", f"breakout candle body {body / a[b]:.1f} ATR"),
                      ("level", f"retest of broken level {lvl:.5g} held")]
                vok, rv = _vol_ok(s, b)
                if vok:
                    ev.append(("volume", f"breakout tick volume {rv}× average"))
                if aligned(bias, side):
                    ev.append(("trend", f"aligned with 1h trend ({h1['trend']})"))
                if fails >= 3:
                    return self.none(ctx, f"{fails} recent false breakouts — level unreliable", **f)
                stop = self.atr_stop(side, float(c[-1]), lvl - sg * 0.5 * atr, atr, 1.0, 2.5)
                strength = 0.35 + 0.1 * len(ev) - 0.05 * fails
                f.update(range_high=clean(hi), range_low=clean(lo), breakout_level=clean(lvl), false_breakouts=fails)
                inval = [f"close back {'below' if side == 'buy' else 'above'} the breakout level {lvl:.5g}", f"price through stop {stop:.5g}"]
                return self.make(ctx, side, float(c[-1]), stop, strength, ev, inval, f)
        hi, lo = float(h[-n - 1:-1].max()), float(l[-n - 1:-1].min())
        return self.none(ctx, f"no qualifying breakout (range {lo:.5g}–{hi:.5g}, {((hi - lo) / atr if atr else 0):.1f} ATR)", **f)


class LiquiditySweep(Strategy):
    name = "liquidity_sweep"
    label = "Liquidity Sweep · Reversal"
    default_params = {"lookback": 3, "mss_bars": 12}
    param_grid = {"lookback": [2, 3, 4], "mss_bars": [8, 12]}

    def evaluate(self, ctx: StrategyContext) -> Signal:
        s = ctx.primary
        if len(s) < self.min_bars:
            return self.none(ctx, f"need {self.min_bars} closed bars, have {len(s)}")
        c, o, h, l = s.c, s.o, s.h, s.l
        k = _base(ctx)
        atr = k["atr_last"]
        dl = an.day_levels(s.t, h, l, ctx.now)
        sw = an.swings(h[:-4], l[:-4], 5, 3)  # older swings = resting liquidity
        levels = {"prior-day high": dl["prev_day_high"], "prior-day low": dl["prev_day_low"], "Asian high": dl["asia_high"], "Asian low": dl["asia_low"]}
        hs = [x for x in sw if x.kind == "high"][-1:]
        ls = [x for x in sw if x.kind == "low"][-1:]
        if hs:
            levels["swing high"] = hs[0].price
        if ls:
            levels["swing low"] = ls[0].price
        f = {"levels": {k2: clean(v) for k2, v in levels.items()}, "atr": clean(atr)}
        sweep = an.detect_sweep(o, h, l, c, levels, self.params["lookback"], min_pen=0.05 * atr)
        if not sweep:
            return self.none(ctx, "no liquidity sweep of a key level in the last bars", **f)
        side = "sell" if sweep.side == "buy_side" else "buy"
        sg = 1 if side == "buy" else -1
        # market structure shift: close beyond the most recent minor swing in the reversal direction
        m = self.params["mss_bars"]
        minor = an.swings(h[-m - 6:], l[-m - 6:], 2, 2)
        ref = [x for x in minor if x.kind == ("high" if side == "buy" else "low")]
        mss = bool(ref) and sg * (c[-1] - ref[-1].price) > 0
        ev = [("liquidity", f"{'sell' if side == 'buy' else 'buy'}-side liquidity swept at {sweep.level_name} {sweep.level:.5g} (wick to {sweep.extreme:.5g})")]
        if mss:
            ev.append(("structure", f"market-structure shift: close {'above' if side == 'buy' else 'below'} minor swing {ref[-1].price:.5g}"))
        body = abs(c[-1] - o[-1])
        if sg * (c[-1] - o[-1]) > 0 and body >= 0.5 * (h[-1] - l[-1]):
            ev.append(("momentum", "strong reversal candle (body ≥ 50% of range)"))
        sess = active_sessions(datetime.fromtimestamp(ctx.now / 1000, timezone.utc))
        if "London" in sess or "New York" in sess:
            ev.append(("session", f"during {' + '.join(sess)} session (institutional participation)"))
        bias, h1, _ = _bias(ctx)
        if aligned(bias, side):
            ev.append(("trend", f"sweep against the move, in direction of 1h trend ({h1['trend']})"))
        if not mss:
            return self.none(ctx, f"sweep at {sweep.level_name} detected; waiting for a market-structure shift", **f)
        stop = self.atr_stop(side, float(c[-1]), sweep.extreme - sg * 0.2 * atr, atr, 0.8, 3.0)
        f.update(sweep_level=clean(sweep.level), sweep_extreme=clean(sweep.extreme), swept=sweep.level_name)
        inval = [f"price back beyond the sweep extreme {sweep.extreme:.5g}", "no follow-through within 6 bars (time stop)"]
        return self.make(ctx, side, float(c[-1]), stop, 0.35 + 0.1 * len(ev), ev, inval, f)


class SupplyDemand(Strategy):
    name = "supply_demand"
    label = "Supply & Demand · S/R"
    default_params = {"impulse_mult": 2.0, "zone_lookback": 200}
    param_grid = {"impulse_mult": [1.6, 2.0, 2.5]}

    def evaluate(self, ctx: StrategyContext) -> Signal:
        s = ctx.primary
        if len(s) < self.min_bars:
            return self.none(ctx, f"need {self.min_bars} closed bars, have {len(s)}")
        c, o, h, l = s.c, s.o, s.h, s.l
        k = _base(ctx)
        a, atr = k["atr"], k["atr_last"]
        zones = an.supply_demand_zones(o, h, l, c, a, self.params["zone_lookback"], self.params["impulse_mult"])
        sr = ind.support_resistance(h, l, c)
        bias, h1, _ = _bias(ctx)
        f = {"zones": [{"kind": z.kind, "top": clean(z.top), "bottom": clean(z.bottom), "fresh": z.fresh, "impulse_atr": clean(z.impulse_atr, 2)} for z in zones],
             "support": sr["support"], "resistance": sr["resistance"], "atr": clean(atr)}
        for z in zones:
            if not z.fresh:
                continue
            # touch on either of the last two bars, confirmation close back outside the zone on the latest bar
            if z.kind == "demand" and l[-2:].min() <= z.top and c[-1] > z.top and c[-1] > o[-1]:
                side = "buy"
                k2 = -1 if l[-1] <= z.top else -2
                wick = (min(o[k2], c[k2]) - l[k2]) / (h[k2] - l[k2] + 1e-12)
            elif z.kind == "supply" and h[-2:].max() >= z.bottom and c[-1] < z.bottom and c[-1] < o[-1]:
                side = "sell"
                k2 = -1 if h[-1] >= z.bottom else -2
                wick = (h[k2] - max(o[k2], c[k2])) / (h[k2] - l[k2] + 1e-12)
            else:
                continue
            sg = 1 if side == "buy" else -1
            ev = [("level", f"first return to fresh {z.kind} zone {z.bottom:.5g}–{z.top:.5g} (impulse {z.impulse_atr:.1f} ATR)")]
            if wick >= 0.4 or abs(c[-1] - o[-1]) >= 0.5 * atr:
                ev.append(("momentum", f"rejection: {'wick ' + format(wick, '.0%') if wick >= 0.4 else 'strong confirmation candle'}"))
            if aligned(bias, side):
                ev.append(("trend", f"with the 1h trend ({h1['trend']})"))
            opp = sr["resistance"] if side == "buy" else sr["support"]
            stop = self.atr_stop(side, float(c[-1]), (z.bottom if side == "buy" else z.top) - sg * 0.2 * atr, atr, 0.8, 3.0)
            r = sg * (c[-1] - stop)
            room = sg * (opp["price"] - c[-1]) / r if opp and r > 0 else None
            if room is None or room >= 2:
                ev.append(("structure", "clear path to target" + (f" — opposing level {room:.1f}R away" if room else " — no opposing level in lookback")))
            f.update(zone={"kind": z.kind, "top": clean(z.top), "bottom": clean(z.bottom)}, room_r=clean(room, 2))
            inval = [f"close {'below' if side == 'buy' else 'above'} the zone ({z.bottom if side == 'buy' else z.top:.5g})"]
            return self.make(ctx, side, float(c[-1]), stop, 0.35 + 0.1 * len(ev) + 0.05 * min(z.impulse_atr / 4, 1), ev, inval, f)
        return self.none(ctx, f"price not reacting at a fresh supply/demand zone ({len(zones)} zones mapped)", **f)


class GoldSession(Strategy):
    """XAU/USD only: London/NY session model around the Asian range, filtered by USD strength and US yields."""

    name = "gold_session"
    label = "Gold · London/NY Session"
    instruments = (GOLD,)
    default_params = {"window_hours": 3.0, "min_asia_range_atr": 1.0}
    param_grid = {"window_hours": [2.0, 3.0, 4.0]}

    def evaluate(self, ctx: StrategyContext) -> Signal:
        s = ctx.primary
        if ctx.symbol != GOLD:
            return self.none(ctx, "gold-only strategy")
        if len(s) < self.min_bars:
            return self.none(ctx, f"need {self.min_bars} closed bars, have {len(s)}")
        c, o, h, l = s.c, s.o, s.h, s.l
        k = _base(ctx)
        atr = k["atr_last"]
        now = datetime.fromtimestamp(ctx.now / 1000, timezone.utc)
        dl = an.day_levels(s.t, h, l, ctx.now)
        ah, al = dl["asia_high"], dl["asia_low"]
        lon_open = now.astimezone(LDN).replace(hour=8, minute=0, second=0, microsecond=0)
        ny_open = now.astimezone(NY).replace(hour=8, minute=0, second=0, microsecond=0)
        wh = self.params["window_hours"] * 3600
        in_lon = 0 <= (now - lon_open).total_seconds() <= wh
        in_ny = 0 <= (now - ny_open).total_seconds() <= wh
        f = {"asia_high": clean(ah), "asia_low": clean(al), "prev_day_high": clean(dl["prev_day_high"]), "prev_day_low": clean(dl["prev_day_low"]),
             "usd_strength": clean(ctx.usd_strength, 3), "us10y_trend": ctx.us10y_trend, "atr": clean(atr),
             "window": "London open" if in_lon else ("New York open" if in_ny else None)}
        if not (in_lon or in_ny):
            return self.none(ctx, "outside the London/New York opening windows for the gold session model", **f)
        if ah is None or al is None:
            return self.none(ctx, "Asian range not available yet", **f)
        if (ah - al) < self.params["min_asia_range_atr"] * atr:
            return self.none(ctx, f"Asian range too narrow ({(ah - al):.2f} vs ATR {atr:.2f})", **f)
        ev = [("session", f"{f['window']} window; Asian range {al:.2f}–{ah:.2f}")]
        side = None
        sweep = an.detect_sweep(o, h, l, c, {"Asian high": ah, "Asian low": al, "prior-day high": dl["prev_day_high"],
                                             "prior-day low": dl["prev_day_low"]}, 3, 0.05 * atr)
        if sweep:
            side = "sell" if sweep.side == "buy_side" else "buy"
            ev.append(("liquidity", f"{sweep.level_name} {sweep.level:.2f} swept (wick to {sweep.extreme:.2f}) and reclaimed"))
            structural = sweep.extreme
        else:
            for sd, lvl in (("buy", ah), ("sell", al)):
                sg = 1 if sd == "buy" else -1
                if sg * (c[-1] - lvl) > 0 and sg * (c[-2] - lvl) > 0 and sg * (c[-3] - lvl) <= 0 and abs(c[-2] - o[-2]) > 0.6 * atr:
                    side = sd
                    ev.append(("structure", f"accepted {'above' if sd == 'buy' else 'below'} the Asian {'high' if sd == 'buy' else 'low'} {lvl:.2f} (2 closes)"))
                    structural = lvl - sg * 0.5 * atr
                    break
        if side is None:
            return self.none(ctx, "no sweep or accepted breakout of the Asian range yet", **f)
        sg = 1 if side == "buy" else -1
        if sg * (c[-1] - o[-1]) > 0 and abs(c[-1] - o[-1]) > 0.4 * atr:
            ev.append(("momentum", f"{'bullish' if side == 'buy' else 'bearish'} confirmation candle"))
        macro = []
        if ctx.usd_strength is not None and -sg * ctx.usd_strength > 0:
            macro.append(f"USD {'weakening' if side == 'buy' else 'strengthening'} (derived strength {ctx.usd_strength:+.2f}%)")
        if ctx.us10y_trend in ("falling", "rising") and ((side == "buy") == (ctx.us10y_trend == "falling")):
            macro.append(f"US 10Y yields {ctx.us10y_trend}")
        if macro:
            ev.append(("macro", "; ".join(macro)))
        elif ctx.usd_strength is not None and sg * ctx.usd_strength > 0.15:
            return self.none(ctx, f"USD strength ({ctx.usd_strength:+.2f}%) contradicts a gold {side}", **f)
        bias, h1, _ = _bias(ctx)
        if aligned(bias, side):
            ev.append(("trend", f"with the 1h trend ({h1['trend']})"))
        stop = self.atr_stop(side, float(c[-1]), structural - sg * 0.2 * atr, atr, 1.0, 3.0)
        rl, rh = an.round_level(float(c[-1]), 10.0)
        f.update(round_levels=[rl, rh])
        inval = [f"price back {'below' if side == 'buy' else 'above'} {stop:.2f}",
                 "high-impact USD release within the news blackout window", "USD strength turns sharply against the trade"]
        return self.make(ctx, side, float(c[-1]), stop, 0.35 + 0.1 * len(ev), ev, inval, f)


STRATEGIES: dict[str, type[Strategy]] = {cls.name: cls for cls in (TrendPullback, BreakoutRetest, LiquiditySweep, SupplyDemand, GoldSession)}


def build(name: str, params: dict | None = None) -> Strategy:
    return STRATEGIES[name](params)


def for_symbol(names: list[str], symbol: str, params: dict | None = None) -> list[Strategy]:
    params = params or {}
    out = []
    for n in names:
        st = build(n, params.get(n))
        if st.applies_to(symbol) and symbol in INSTRUMENTS:
            out.append(st)
    return out
