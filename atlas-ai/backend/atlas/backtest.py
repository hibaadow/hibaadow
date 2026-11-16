"""Event-driven historical backtester for gold & forex.

Bias controls
-------------
* Strategies only see CLOSED bars up to bar i (same window as live); 1h/4h bars are built from the
  primary bars and only become visible once complete. No look-ahead.
* Signals at bar i close are executed at bar i+1 OPEN: buys at mid + half spread + slippage, sells at
  mid − half spread − slippage. The per-bar spread comes from the data when the broker supplies bid/ask
  candles (OANDA "BA", MT5 spread); otherwise the configured fixed spread is used.
* Exits: longs are evaluated on bid (mid − half spread), shorts on ask. Stops are checked before targets
  inside a bar; gaps through a stop fill at the open. Commission is charged per lot per side.
* Identical sizing (``risk.size_position``: pip value, stop distance, lot step, margin) and position rules
  (``execution.rules``) as paper trading. Daily loss limit and loss-streak cooldown are simulated.
* Sessions and the economic calendar are NOT replayed historically (no reliable archive is wired in);
  results therefore exclude the news blackout — a known optimistic/pessimistic bias, reported in the UI.
* Pip values for crosses (e.g. EUR/GBP, GBP/JPY) use the conversion rate at run time (approximation).
* Out-of-sample and walk-forward evaluation as before. Historical performance is not evidence of future profitability.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np

from .execution import costs
from .execution.rules import PosState, RuleParams, apply, manage
from .instruments import INSTRUMENTS, CONVERSION_PAIRS
from .marketdata.types import TF_MS, Candle, CandleSeries
from .portfolio import max_drawdown, trade_metrics
from .risk import size_position
from .strategies.base import StrategyContext
from .strategies.library import build
from .trading_config import TradingConfig

WINDOW = 500
WARMUP = 220


@dataclass
class BTParams:
    symbol: str
    strategy: str
    timeframe: str
    starting_capital: float = 10_000.0
    spread_pips: float | None = None  # None → use per-bar spread from data, else the instrument default
    strategy_params: dict = field(default_factory=dict)
    oos_fraction: float = 0.3
    conversion_mids: dict = field(default_factory=dict)  # live mids for cross-currency pip values


def resample(series: CandleSeries, tf: str) -> tuple[CandleSeries, np.ndarray]:
    """Aggregate to a higher timeframe. Returns the HTF series and each HTF bar's close time (ms)."""
    step = TF_MS[tf]
    bucket = series.t // step * step
    out: list[Candle] = []
    starts = np.flatnonzero(np.r_[True, bucket[1:] != bucket[:-1]])
    ends = np.r_[starts[1:], len(bucket)]
    for a, b in zip(starts, ends):
        sp = float(series.sp[a:b].mean()) if series.sp is not None else 0.0
        out.append(Candle(int(bucket[a]), float(series.o[a]), float(series.h[a:b].max()), float(series.l[a:b].min()),
                          float(series.c[b - 1]), float(series.v[a:b].sum()), 0.0, sp))
    htf = CandleSeries.from_candles(series.symbol, tf, series.venue, out)
    return htf, htf.t + step


def _sharpe_sortino(equity_by_day: list[float]) -> tuple[float | None, float | None]:
    if len(equity_by_day) < 3:
        return None, None
    e = np.asarray(equity_by_day)
    r = e[1:] / e[:-1] - 1
    if r.std(ddof=1) == 0:
        return None, None
    sharpe = r.mean() / r.std(ddof=1) * math.sqrt(365)
    downside = r[r < 0]
    sortino = r.mean() / downside.std(ddof=1) * math.sqrt(365) if len(downside) > 1 and downside.std(ddof=1) > 0 else None
    return round(float(sharpe), 3), (round(float(sortino), 3) if sortino is not None else None)


def metrics(trades: list[dict], curve: list[dict], start_capital: float, bars: int, bar_ms: int) -> dict:
    pnls = [t["net_pnl"] for t in trades]
    m = trade_metrics(pnls, [t["risk_amount"] for t in trades])
    final = curve[-1]["equity"] if curve else start_capital
    first = curve[0]["equity"] if curve else start_capital
    mdd, _ = max_drawdown([c["equity"] for c in curve]) if curve else (0.0, [])
    by_day: dict[str, float] = {}
    for c in curve:
        by_day[datetime.fromtimestamp(c["t"] / 1000, timezone.utc).strftime("%Y-%m-%d")] = c["equity"]
    sharpe, sortino = _sharpe_sortino(list(by_day.values()))
    holds = [t["bars_held"] for t in trades]
    m.update({
        "net_return_pct": round((final / first - 1) * 100, 4) if first else 0.0,
        "final_equity": round(final, 4),
        "max_drawdown_pct": mdd,
        "sharpe": sharpe,
        "sortino": sortino,
        "avg_trade_return_pct": round(float(np.mean([t["return_pct"] for t in trades])), 4) if trades else None,
        "avg_holding_minutes": round(float(np.mean(holds)) * bar_ms / 60000, 1) if holds else None,
        "fees": round(sum(t["fees"] for t in trades), 4),
        "slippage_cost": round(sum(t["slippage_cost"] for t in trades), 4),
        "bars": bars,
        "exposure_pct": round(sum(holds) / bars * 100, 2) if bars else 0.0,
    })
    return m


class Backtester:
    def __init__(self, cfg: TradingConfig, rules: RuleParams | None = None):
        self.cfg = cfg
        self.rules = rules or RuleParams()

    def _mids(self, inst, price: float, p: BTParams) -> dict[str, float]:
        """Conversion rates for pip value: exact for USD-quoted / USD-based pairs, live rate for crosses."""
        mids = dict(p.conversion_mids)
        if inst.quote == "USD" or inst.base == "USD":
            mids[inst.symbol] = price
        pair = CONVERSION_PAIRS.get(inst.quote)
        if pair and pair not in mids:
            mids[pair] = {"JPY": 150.0, "CHF": 0.9, "CAD": 1.37, "GBP": 1.27, "EUR": 1.08, "AUD": 0.65, "NZD": 0.6}[inst.quote]
            mids["_approx"] = 1
        return mids

    def run(self, series: CandleSeries, p: BTParams, start_index: int = 0, end_index: int | None = None) -> dict:
        cfg, cm = self.cfg, self.cfg.costs
        inst = INSTRUMENTS[p.symbol]
        n = len(series) if end_index is None else end_index
        step = TF_MS[series.timeframe]
        h1, h1_close = resample(series, "1h")
        h4, h4_close = resample(series, "4h")
        strat = build(p.strategy, p.strategy_params)
        balance = p.starting_capital
        pos: dict | None = None
        pending: dict | None = None
        pending_exit: str | None = None
        trades: list[dict] = []
        curve: list[dict] = []
        day_key, day_start = None, balance
        streak, last_loss_t = 0, None
        signals = rejected = 0
        first = max(WARMUP, start_index)
        default_sp = (p.spread_pips if p.spread_pips is not None else inst.max_spread_pips * 0.5) * inst.pip_size

        def spread_at(i):
            if p.spread_pips is None and series.sp is not None and series.sp[i] > 0:
                return float(series.sp[i])
            return default_sp

        def upnl(px_mid, i):
            if not pos:
                return 0.0
            st = pos["st"]
            close_px = px_mid - st.sign * spread_at(i) / 2
            mids = self._mids(inst, px_mid, p)
            rate = costs.pip_value_usd(inst, mids) / inst.pip_value_quote if costs.pip_value_usd(inst, mids) else 1.0
            return st.sign * (close_px - st.entry) * st.qty * inst.contract_size * rate

        for i in range(first, n):
            t_open = int(series.t[i])
            o, h, l, c = float(series.o[i]), float(series.h[i]), float(series.l[i]), float(series.c[i])
            half = spread_at(i) / 2
            dk = t_open // 86_400_000
            if dk != day_key:
                day_key, day_start = dk, balance + upnl(o, i)
            if pending_exit and pos:
                balance += self._exit(pos, o, half, pending_exit, i, t_open, trades, p, "exit")
                streak, last_loss_t = self._streak(trades, streak, last_loss_t, t_open)
                pos = None
            pending_exit = None
            if pending and pos is None:
                e = pending
                side, sg = e["side"], (1 if e["side"] == "buy" else -1)
                ref = o + sg * half
                mids = self._mids(inst, o, p)
                if sg * (ref - e["stop"]) > 0:
                    sz = size_position(cfg, inst, side, balance, 0.0, 0.0, streak, ref, e["stop"], e["target"], 2 * half, mids)
                    if sz and sz.lots >= inst.min_lot and sz.net_rr >= cfg.risk.min_risk_reward - 1e-6:
                        slip = costs.slippage_pips(inst, cm)
                        fill = costs.apply_slippage(ref, slip, inst, side)
                        comm = costs.commission_per_side(inst, sz.lots, cm)
                        balance -= comm
                        r = sg * (fill - e["stop"])
                        tp2 = sz.target + sg * r
                        pos = {"entry_i": i, "entry_t": t_open, "lots": sz.lots, "fees": comm, "pv": sz.pip_value_usd, "risk": sz.risk_amount,
                               "slip": slip * sz.pip_value_usd * sz.lots, "pnl": 0.0, "reason": e["reason"], "side": side, "strength": e["strength"], "eq": balance,
                               "st": PosState(fill, sz.lots, sz.lots, e["stop"], e["stop"], sz.target, tp2, t_open / 1000, side,
                                              best=fill, cost_per_unit=2 * comm / sz.lots / sz.pip_value_usd * inst.pip_size, through=inst.pip_size * 0.1)}
                    else:
                        rejected += 1
                else:
                    rejected += 1
            pending = None
            if pos:
                st: PosState = pos["st"]
                sg = st.sign
                # prices on the closing side of the book
                co, ch, cl, cc = o - sg * half, h - sg * half, l - sg * half, c - sg * half
                for act in manage(st, cl, ch, cc, (t_open + step) / 1000, self.rules, open_=co):
                    if act.kind == "move_stop":
                        apply(st, act)
                        continue
                    lots = round(st.qty * act.fraction, 2) if act.fraction < 1 else st.qty
                    if act.kind in ("tp1", "tp2"):
                        px = act.price
                    else:
                        slip = costs.slippage_pips(inst, cm, stop=act.kind == "stop")
                        px = costs.apply_slippage(act.price, slip, inst, "sell" if sg == 1 else "buy")
                        pos["slip"] += slip * pos["pv"] * lots
                    balance += self._realize(pos, px, lots, p)
                    apply(st, act, lots)
                    if st.qty <= 1e-9:
                        self._record(pos, i, t_open, act.reason, act.kind, trades)
                        streak, last_loss_t = self._streak(trades, streak, last_loss_t, t_open)
                        pos = None
                        break
            lo = max(0, i + 1 - WINDOW)
            close_t = t_open + step
            j1 = int(np.searchsorted(h1_close, close_t, side="right"))
            j4 = int(np.searchsorted(h4_close, close_t, side="right"))
            ctx = StrategyContext(p.symbol, series.slice(i + 1, lo), h1.slice(j1, max(0, j1 - 300)), h4.slice(j4, max(0, j4 - 200)), close_t)
            sig = strat.evaluate(ctx)
            mtm = balance + upnl(c, i)
            if pos and sig.direction == "exit" and sig.features.get("exit_for") == pos["side"]:
                pending_exit = "strategy exit: " + "; ".join(sig.reasons)
            elif pos is None and sig.direction in ("buy", "sell") and i + 1 < n:
                signals += 1
                day_loss = (mtm / day_start - 1) * 100 if day_start else 0
                cooling = streak >= cfg.risk.consecutive_loss_cooldown and last_loss_t is not None and t_open - last_loss_t < cfg.risk.cooldown_minutes * 60000
                if day_loss <= -cfg.risk.max_daily_loss_pct or cooling:
                    rejected += 1
                else:
                    pending = {"side": sig.direction, "stop": sig.stop, "target": sig.targets[0], "strength": sig.strength, "reason": "; ".join(sig.reasons[:3])}
            curve.append({"t": close_t, "equity": round(mtm, 4)})
        if pos:
            last = n - 1
            balance += self._exit(pos, float(series.c[last]), spread_at(last) / 2, "end of backtest", last, int(series.t[last]), trades, p, "exit")
            if curve:
                curve[-1]["equity"] = round(balance, 4)
        res = {"trades": trades, "curve": curve, "signals": signals, "rejected": rejected,
               "metrics": metrics(trades, curve, p.starting_capital, max(0, n - first), step)}
        res["metrics"]["cross_rate_approximated"] = bool(self._mids(inst, float(series.c[-1]), p).get("_approx"))
        return res

    def _realize(self, pos, px, lots, p: BTParams) -> float:
        inst = INSTRUMENTS[p.symbol]
        st: PosState = pos["st"]
        rate = pos["pv"] / inst.pip_value_quote
        gross = st.sign * (px - st.entry) * lots * inst.contract_size * rate
        comm = costs.commission_per_side(inst, lots, self.cfg.costs)
        pos["pnl"] += gross
        pos["fees"] += comm
        pos.setdefault("exit_value", 0.0)
        pos["exit_value"] = pos["exit_value"] + px * lots
        pos["exit_lots"] = pos.get("exit_lots", 0.0) + lots
        return gross - comm

    def _exit(self, pos, mid, half, reason, i, t, trades, p, kind) -> float:
        inst = INSTRUMENTS[p.symbol]
        st: PosState = pos["st"]
        slip = costs.slippage_pips(inst, self.cfg.costs)
        px = costs.apply_slippage(mid - st.sign * half, slip, inst, "sell" if st.sign == 1 else "buy")
        pos["slip"] += slip * pos["pv"] * st.qty
        delta = self._realize(pos, px, st.qty, p)
        st.qty = 0
        self._record(pos, i, t, reason, kind, trades)
        return delta

    @staticmethod
    def _record(pos, i, t, reason, kind, trades):
        st: PosState = pos["st"]
        net = pos["pnl"] - pos["fees"]
        trades.append({"entry_time": pos["entry_t"], "exit_time": t, "side": pos["side"], "entry": round(st.entry, 6),
                       "exit": round(pos["exit_value"] / pos["exit_lots"], 6) if pos.get("exit_lots") else None, "lots": pos["lots"],
                       "gross_pnl": round(pos["pnl"], 4), "net_pnl": round(net, 4), "fees": round(pos["fees"], 4), "slippage_cost": round(pos["slip"], 4),
                       "risk_amount": round(pos["risk"], 4), "r_multiple": round(net / pos["risk"], 4) if pos["risk"] else None,
                       "return_pct": round(net / pos["eq"] * 100, 4) if pos.get("eq") else 0.0, "bars_held": i - pos["entry_i"] + 1,
                       "exit_reason": reason, "exit_kind": kind, "entry_reason": pos["reason"], "strength": pos["strength"]})

    @staticmethod
    def _streak(trades, streak, last_t, t):
        if trades and trades[-1]["net_pnl"] < 0:
            return streak + 1, t
        return 0, last_t


def split_metrics(result: dict, series: CandleSeries, p: BTParams) -> tuple[dict, dict]:
    """In-sample vs out-of-sample metrics by entry time (OOS = last oos_fraction of the period)."""
    t_split = int(series.t[int(len(series) * (1 - p.oos_fraction))])
    step = TF_MS[series.timeframe]
    out = []
    for sel in (lambda tr: tr["entry_time"] < t_split, lambda tr: tr["entry_time"] >= t_split):
        trs = [tr for tr in result["trades"] if sel(tr)]
        cv = [c for c in result["curve"] if sel({"entry_time": c["t"]})]
        out.append(metrics(trs, cv, cv[0]["equity"] if cv else p.starting_capital, len(cv), step))
    out[0]["period_end"] = t_split
    out[1]["period_start"] = t_split
    return out[0], out[1]


def _objective(m: dict) -> float:
    if m["total_trades"] < 5:
        return -1e9
    return (m.get("expectancy_r") or -1) * math.sqrt(m["total_trades"])


def walk_forward(bt: Backtester, series: CandleSeries, p: BTParams, folds: int = 3, train_ratio: float = 2.0) -> dict:
    """Anchored-window walk-forward: optimise on [train], test on the next unseen [test] window."""
    from .strategies.library import STRATEGIES

    grid = STRATEGIES[p.strategy].param_grid
    keys = list(grid)
    combos = [dict(zip(keys, vals)) for vals in itertools.product(*[grid[k] for k in keys])] or [{}]
    usable = len(series) - WARMUP
    unit = usable / (folds + train_ratio)
    results, oos_trades = [], []
    for f in range(folds):
        tr_start = WARMUP + int(f * unit)
        tr_end = WARMUP + int((f + train_ratio) * unit)
        te_end = min(len(series), WARMUP + int((f + train_ratio + 1) * unit))
        best, best_score, best_m = None, -math.inf, None
        for params in combos:
            pp = BTParams(**{**p.__dict__, "strategy_params": {**p.strategy_params, **params}})
            r = bt.run(series, pp, tr_start, tr_end)
            sc = _objective(r["metrics"])
            if sc > best_score:
                best, best_score, best_m = params, sc, r["metrics"]
        pp = BTParams(**{**p.__dict__, "strategy_params": {**p.strategy_params, **(best or {})}})
        test = bt.run(series, pp, tr_end, te_end)
        oos_trades += test["trades"]
        results.append({"fold": f + 1, "train": [int(series.t[tr_start]), int(series.t[tr_end - 1])],
                        "test": [int(series.t[tr_end]), int(series.t[te_end - 1])], "params": best,
                        "train_metrics": _brief(best_m), "test_metrics": _brief(test["metrics"])})
    agg = trade_metrics([t["net_pnl"] for t in oos_trades], [t["risk_amount"] for t in oos_trades])
    is_exp = [r["train_metrics"].get("expectancy_r") for r in results if r["train_metrics"].get("expectancy_r") is not None]
    oos_exp = agg.get("expectancy_r")
    eff = round(oos_exp / np.mean(is_exp), 3) if is_exp and oos_exp is not None and np.mean(is_exp) > 0 else None
    return {"folds": results, "oos_aggregate": agg, "walk_forward_efficiency": eff, "grid_size": len(combos),
            "note": "Each test window is unseen by the optimiser. Efficiency = OOS expectancy / mean in-sample expectancy."}


def _brief(m: dict | None) -> dict:
    if not m:
        return {}
    keys = ("total_trades", "win_rate", "profit_factor", "expectancy_r", "net_return_pct", "max_drawdown_pct")
    return {k: m.get(k) for k in keys}
