"""Event-driven historical backtester.

Bias controls
-------------
* Strategies only see CLOSED bars up to and including bar i (same 500-bar window as live).
* Higher-timeframe bars are built from primary bars and only become visible once fully closed.
* Signals at bar i close are executed at bar i+1 OPEN (+ half spread + modelled slippage + taker fee).
* Stops are evaluated before targets inside a bar (conservative); gaps through a stop fill at the open.
* Targets fill only when price trades through them; maker fee applied.
* Identical sizing (``risk.size_position``) and position rules (``execution.rules``) as paper trading.
* Daily loss limit and loss-streak cooldown are simulated.
* Out-of-sample: metrics reported separately for the last ``oos_fraction`` of the data.
* Walk-forward: parameters are optimised on a training window and evaluated on the following unseen window.

Historical performance is not evidence of future profitability.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np

from .execution import costs
from .execution.rules import Action, PosState, RuleParams, apply, manage
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
    spread_bps: float = 2.0
    strategy_params: dict = field(default_factory=dict)
    oos_fraction: float = 0.3


def resample(series: CandleSeries, tf: str) -> tuple[CandleSeries, np.ndarray]:
    """Aggregate to a higher timeframe. Returns the HTF series and each HTF bar's close time (ms)."""
    step = TF_MS[tf]
    bucket = series.t // step * step
    out: list[Candle] = []
    starts = np.flatnonzero(np.r_[True, bucket[1:] != bucket[:-1]])
    ends = np.r_[starts[1:], len(bucket)]
    for a, b in zip(starts, ends):
        out.append(Candle(int(bucket[a]), float(series.o[a]), float(series.h[a:b].max()), float(series.l[a:b].min()),
                          float(series.c[b - 1]), float(series.v[a:b].sum()), float(series.qv[a:b].sum())))
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

    def run(self, series: CandleSeries, p: BTParams, start_index: int = 0, end_index: int | None = None) -> dict:
        cfg, fees = self.cfg, self.cfg.fees
        n = len(series) if end_index is None else end_index
        step = TF_MS[series.timeframe]
        htf, htf_close = resample(series, "1h")
        strat = build(p.strategy, p.strategy_params)
        equity = cash = p.starting_capital
        pos: dict | None = None
        pending_entry: dict | None = None
        pending_exit: str | None = None
        trades: list[dict] = []
        curve: list[dict] = []
        day_key, day_start_eq = None, equity
        losses_streak, last_loss_t = 0, None
        signals = rejected = 0
        first = max(WARMUP, start_index)
        for i in range(first, n):
            t_open = int(series.t[i])
            o, h, l, c = float(series.o[i]), float(series.h[i]), float(series.l[i]), float(series.c[i])
            minute_qv = float(series.qv[i]) / (step / 60000)
            dk = t_open // 86_400_000
            if dk != day_key:
                day_key, day_start_eq = dk, cash + (pos["qty"] * o if pos else 0)
            # ---- 1) execute orders decided at the previous bar's close, at this bar's OPEN
            if pending_exit and pos:
                self._close(pos, o, minute_qv, pending_exit, i, t_open, trades, fees, p)
                cash += pos["cash_delta"]
                losses_streak, last_loss_t = self._streak(trades, losses_streak, last_loss_t, t_open)
                pos = None
            pending_exit = None
            if pending_entry and pos is None:
                e = pending_entry
                ref = o * (1 + p.spread_bps / 2e4)
                if e["stop"] < ref:
                    sz = size_position(cfg, cash, cash, 0.0, losses_streak, ref, e["stop"], e["target"], p.spread_bps, minute_qv)
                    if sz.net_rr >= cfg.risk.min_risk_reward - 1e-9 and sz.notional >= 10 and sz.slippage_bps <= cfg.risk.max_slippage_bps:
                        fill = costs.apply_slippage(ref, sz.slippage_bps, "buy")
                        fee = costs.fee(fees, sz.qty * fill)
                        cash -= sz.qty * fill + fee
                        tp1 = sz.target
                        r = fill - e["stop"]
                        tp2 = max(e.get("tp2") or 0, tp1 + r)
                        pos = {"entry_i": i, "entry_t": t_open, "entry": fill, "qty": sz.qty, "initial_qty": sz.qty, "fees": fee,
                               "slip": abs(fill - o) * sz.qty, "risk_amount": sz.risk_amount, "exit_value": 0.0, "exit_qty": 0.0,
                               "conf": e["strength"], "reason": e["reason"], "cash_delta": 0.0,
                               "st": PosState(fill, sz.qty, sz.qty, e["stop"], e["stop"], tp1, tp2, t_open / 1000,
                                              high_water=fill, fee_per_unit=fill * 2 * fees.taker_fee_bps / 1e4)}
                    else:
                        rejected += 1
                else:
                    rejected += 1
            pending_entry = None
            # ---- 2) manage open position within this bar
            if pos:
                st: PosState = pos["st"]
                for act in manage(st, l, h, c, (t_open + step) / 1000, self.rules, open_=o):
                    if act.kind == "move_stop":
                        apply(st, act)
                        continue
                    qty = st.qty * act.fraction if act.fraction < 1 else st.qty
                    if act.kind in ("tp1", "tp2"):
                        px, taker = act.price, False
                    else:
                        slip = costs.slippage_bps(fees, qty * act.price, minute_qv, p.spread_bps) + (fees.base_slippage_bps if act.kind == "stop" else 0)
                        px, taker = costs.apply_slippage(act.price * (1 - p.spread_bps / 2e4), slip, "sell"), True
                        pos["slip"] += abs(act.price - px) * qty
                    fee = costs.fee(fees, qty * px, taker)
                    cash += qty * px - fee
                    pos["fees"] += fee
                    pos["exit_value"] += qty * px
                    pos["exit_qty"] += qty
                    apply(st, act, qty)
                    if st.qty <= 1e-12:
                        self._record(pos, i, t_open, act.reason, act.kind, trades)
                        losses_streak, last_loss_t = self._streak(trades, losses_streak, last_loss_t, t_open)
                        pos = None
                        break
            # ---- 3) at this bar's CLOSE, evaluate the strategy on closed data only
            lo = max(0, i + 1 - WINDOW)
            visible_htf = int(np.searchsorted(htf_close, t_open + step, side="right"))
            ctx = StrategyContext(p.symbol, series.slice(i + 1, lo), htf.slice(visible_htf, max(0, visible_htf - 300)))
            sig = strat.evaluate(ctx)
            mtm = cash + (pos["st"].qty * c if pos else 0)
            if pos and sig.direction == "exit":
                pending_exit = "strategy exit: " + "; ".join(sig.reasons)
            elif pos is None and sig.direction == "long" and i + 1 < n:
                signals += 1
                day_loss = (mtm / day_start_eq - 1) * 100 if day_start_eq else 0
                cooling = (losses_streak >= cfg.risk.consecutive_loss_cooldown and last_loss_t is not None
                           and t_open - last_loss_t < cfg.risk.cooldown_minutes * 60000)
                if day_loss <= -cfg.risk.max_daily_loss_pct or cooling:
                    rejected += 1
                else:
                    pending_entry = {"stop": sig.stop, "target": sig.targets[0], "tp2": sig.targets[1] if len(sig.targets) > 1 else None,
                                     "strength": sig.strength, "reason": "; ".join(sig.reasons[:3])}
            curve.append({"t": t_open + step, "equity": round(mtm, 6)})
        if pos:  # close at the final close for accounting
            self._close(pos, float(series.c[n - 1]), float(series.qv[n - 1]) / (step / 60000), "end of backtest", n - 1,
                        int(series.t[n - 1]), trades, fees, p)
            cash += pos["cash_delta"]
            if curve:
                curve[-1]["equity"] = round(cash, 6)
        return {"trades": trades, "curve": curve, "signals": signals, "rejected": rejected,
                "metrics": metrics(trades, curve, p.starting_capital, max(0, n - first), step)}

    def _close(self, pos, price, minute_qv, reason, i, t, trades, fees, p):
        st: PosState = pos["st"]
        qty = st.qty
        slip = costs.slippage_bps(fees, qty * price, minute_qv, p.spread_bps)
        px = costs.apply_slippage(price * (1 - p.spread_bps / 2e4), slip, "sell")
        fee = costs.fee(fees, qty * px)
        pos["cash_delta"] = qty * px - fee
        pos["fees"] += fee
        pos["slip"] += abs(price - px) * qty
        pos["exit_value"] += qty * px
        pos["exit_qty"] += qty
        st.qty = 0
        self._record(pos, i, t, reason, "exit", trades)

    @staticmethod
    def _record(pos, i, t, reason, kind, trades):
        gross = pos["exit_value"] - pos["entry"] * pos["exit_qty"]
        net = gross - pos["fees"]
        cost = pos["entry"] * pos["initial_qty"]
        trades.append({"entry_time": pos["entry_t"], "exit_time": t, "entry": round(pos["entry"], 10),
                       "exit": round(pos["exit_value"] / pos["exit_qty"], 10) if pos["exit_qty"] else None, "qty": pos["initial_qty"],
                       "gross_pnl": round(gross, 6), "net_pnl": round(net, 6), "fees": round(pos["fees"], 6), "slippage_cost": round(pos["slip"], 6),
                       "risk_amount": round(pos["risk_amount"], 6), "r_multiple": round(net / pos["risk_amount"], 4) if pos["risk_amount"] else None,
                       "return_pct": round(net / cost * 100, 4) if cost else 0, "bars_held": i - pos["entry_i"] + 1,
                       "exit_reason": reason, "exit_kind": kind, "entry_reason": pos["reason"], "strength": pos["conf"]})

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
