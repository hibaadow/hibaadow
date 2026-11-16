"""AI decision engine.

Evaluates structured strategy signals in the context of market regime,
liquidity, costs, structure and portfolio exposure, and classifies each
opportunity. The scoring model is deterministic and fully explainable: every
point of the 0–100 confidence score is attributed to a named factor.

IMPORTANT: the confidence score is a ranking of setup quality, NOT a
probability of profit. ``calibration()`` reports how scores have actually
mapped to outcomes historically so users can judge it empirically.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Decision as DecisionRow
from .strategies.base import Signal

STRONG_BUY = "STRONG BUY CANDIDATE"
BUY = "BUY CANDIDATE"
WAIT = "WAIT"
NO_TRADE = "NO TRADE"
EXIT = "EXIT"
HIGH_RISK = "HIGH RISK"
CLASSES = (STRONG_BUY, BUY, WAIT, NO_TRADE, EXIT, HIGH_RISK)

WAIT_HINTS = ("waiting", "consolidating", "pullback in progress", "trend intact")


@dataclass
class MarketContext:
    symbol: str
    price: float | None
    spread_bps: float | None
    liquidity_usd: float | None
    volume_24h_usd: float | None
    change_24h_pct: float | None
    atr_pct: float | None
    regime: str  # BTC 1h trend: up | range | down | unknown
    data_ready: bool
    data_issues: list[str] = field(default_factory=list)
    round_trip_cost_bps: float | None = None


@dataclass
class PortfolioContext:
    open_symbols: list[str]
    exposure_pct: float
    max_exposure_pct: float


@dataclass
class Evaluation:
    classification: str
    confidence: int
    breakdown: dict
    risk_flags: list[str]
    explanation: str
    actionable: bool


def _f(x, default=None):
    try:
        v = float(x)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def evaluate(sig: Signal, m: MarketContext, p: PortfolioContext, min_liquidity: float, max_spread_bps: float,
             strategy_penalty: tuple[int, str] | None = None, has_position: bool = False) -> Evaluation:
    flags: list[str] = []
    if not m.data_ready:
        flags.append("market data incomplete/stale: " + "; ".join(m.data_issues)[:200])
    if m.spread_bps is not None and m.spread_bps > max_spread_bps:
        flags.append(f"spread {m.spread_bps:.1f} bps exceeds {max_spread_bps}")
    if m.liquidity_usd is not None and m.liquidity_usd < min_liquidity:
        flags.append(f"insufficient liquidity (${m.liquidity_usd:,.0f} within ±1%)")
    if m.atr_pct is not None and m.atr_pct > 3.0:
        flags.append(f"extreme volatility (ATR {m.atr_pct:.2f}% per bar)")
    if m.change_24h_pct is not None and abs(m.change_24h_pct) > 25:
        flags.append(f"24h move {m.change_24h_pct:+.1f}% — abnormal")

    if sig.direction == "exit":
        cls = EXIT if has_position else NO_TRADE
        expl = f"{sig.strategy}: exit conditions present — " + "; ".join(sig.reasons)
        return Evaluation(cls, 0, {}, flags, expl, has_position)
    if sig.direction != "long":
        reason = "; ".join(sig.reasons) or "no setup"
        cls = WAIT if any(h in reason for h in WAIT_HINTS) else NO_TRADE
        if flags and cls == WAIT:
            cls = HIGH_RISK
            reason += " [risk: " + "; ".join(flags) + "]"
        return Evaluation(cls, 0, {}, flags, f"{sig.strategy}: {reason}", False)

    f = sig.features
    b: dict[str, dict] = {}

    def add(name, pts, maxp, why):
        b[name] = {"points": round(max(0.0, min(pts, maxp)), 2), "max": maxp, "why": why}

    add("signal_strength", 25 * sig.strength, 25, f"strategy conviction {sig.strength:.2f}")
    htf = (f.get("htf") or {}).get("trend", "unknown")
    add("higher_timeframe", {"up": 15, "range": 6, "down": 0}.get(htf, 4), 15, f"1h trend {htf}")
    add("market_regime", {"up": 10, "range": 5, "down": 0}.get(m.regime, 3), 10, f"BTC 1h regime {m.regime}")
    rv = _f(f.get("rel_volume"))
    add("volume", 10 * min((rv or 0) / 2, 1), 10, f"relative volume {rv:.2f}x" if rv is not None else "volume n/a")
    if m.atr_pct is None:
        add("volatility", 4, 10, "volatility unknown")
    else:
        a = m.atr_pct
        pts = 10 if 0.15 <= a <= 1.5 else (6 if 0.08 <= a <= 2.5 else 1)
        add("volatility", pts, 10, f"ATR {a:.3f}% per bar ({'healthy' if pts == 10 else 'outside ideal band'})")
    if m.liquidity_usd is None:
        add("liquidity", 0, 10, "depth unavailable")
    else:
        ratio = m.liquidity_usd / max(min_liquidity, 1)
        add("liquidity", 10 * min(math.log10(max(ratio, 1e-9)) / 1.0 + 0.5, 1) if ratio >= 1 else 0, 10,
            f"±1% depth ${m.liquidity_usd:,.0f} ({ratio:.1f}x minimum)")
    r = sig.risk_per_unit or 0
    if r > 0 and m.round_trip_cost_bps is not None and sig.entry:
        cost_r = sig.entry * m.round_trip_cost_bps / 1e4 / r
        add("costs", 10 * (1 - min(cost_r / 0.3, 1)), 10, f"round-trip costs = {cost_r:.2f}R")
    else:
        add("costs", 0, 10, "cost estimate unavailable")
    res = f.get("resistance")
    res_price = res.get("price") if isinstance(res, dict) else None
    if res_price and r > 0 and sig.entry:
        room = (res_price - sig.entry) / r
        add("structure", 10 if room >= 3 else (6 if room >= 2 else 0), 10, f"nearest resistance {room:.1f}R away")
    else:
        add("structure", 7, 10, "no overhead resistance identified in lookback")
    score = sum(x["points"] for x in b.values())
    if p.exposure_pct > p.max_exposure_pct * 0.5:
        score -= 5
        b["exposure_penalty"] = {"points": -5, "max": 0, "why": f"portfolio exposure {p.exposure_pct:.0f}% already high"}
    if strategy_penalty and strategy_penalty[0]:
        score -= strategy_penalty[0]
        b["track_record_penalty"] = {"points": -strategy_penalty[0], "max": 0, "why": strategy_penalty[1]}
    conf = int(round(max(0, min(100, score))))
    if flags:
        cls = HIGH_RISK
    elif conf >= 75:
        cls = STRONG_BUY
    elif conf >= 60:
        cls = BUY
    elif conf >= 45:
        cls = WAIT
    else:
        cls = NO_TRADE
    top = sorted(b.items(), key=lambda kv: kv[1]["points"] - kv[1]["max"])
    weak = [f"{k.replace('_', ' ')} ({v['why']})" for k, v in top[:2] if v["points"] < v["max"] * 0.5]
    rr = sig.rr
    expl = (f"{sig.strategy} long setup on {sig.symbol} {sig.timeframe}: " + "; ".join(sig.reasons[:4]) +
            f". Entry ≈{sig.entry:.6g}, stop {sig.stop:.6g}, TP1 {sig.targets[0]:.6g}" + (f" ({rr:.1f}R gross)" if rr else "") +
            f". Confidence {conf}/100 → {cls}." + (f" Weakest factors: {', '.join(weak)}." if weak else "") +
            (f" Risk flags: {'; '.join(flags)}." if flags else ""))
    return Evaluation(cls, conf, b, flags, expl, cls in (STRONG_BUY, BUY))


def strategy_track_record(db: Session, strategy: str, min_trades: int = 30) -> tuple[int, str] | None:
    """Penalty from measured live/paper outcomes: negative expectancy over a meaningful sample lowers scores."""
    rows = db.execute(select(DecisionRow.outcome_r).where(DecisionRow.strategy == strategy, DecisionRow.executed.is_(True),
                                                          DecisionRow.outcome_r.is_not(None)).order_by(DecisionRow.id.desc()).limit(200)).scalars().all()
    if len(rows) < min_trades:
        return None
    exp = sum(rows) / len(rows)
    if exp < 0:
        pts = int(min(15, round(-exp * 20)))
        return pts, f"{strategy} expectancy {exp:+.2f}R over last {len(rows)} paper trades"
    return 0, f"{strategy} expectancy {exp:+.2f}R over last {len(rows)} trades"


def calibration(db: Session, buckets=((0, 45), (45, 60), (60, 75), (75, 101))) -> list[dict]:
    """Empirical outcome rate per confidence bucket for executed decisions."""
    rows = db.execute(select(DecisionRow.confidence, DecisionRow.outcome, DecisionRow.outcome_r)
                      .where(DecisionRow.executed.is_(True), DecisionRow.outcome.is_not(None))).all()
    out = []
    for lo, hi in buckets:
        sel = [r for r in rows if lo <= r[0] < hi]
        n = len(sel)
        wins = sum(1 for r in sel if r[1] == "win")
        out.append({"bucket": f"{lo}-{min(hi, 100)}", "trades": n, "win_rate": round(wins / n * 100, 1) if n else None,
                    "avg_r": round(sum(r[2] or 0 for r in sel) / n, 3) if n else None,
                    "note": "insufficient sample" if n < 20 else ""})
    return out
