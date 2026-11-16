"""AI trading analyst for gold & forex.

Scores each strategy signal on independent factors (confluence, multi-timeframe trend, session,
costs, volatility regime, currency strength / USD & yields for gold, upcoming events, structure)
and classifies it. Every point is attributed to a named factor and the analyst can — and usually
does — reject opportunities, with the reason recorded.

The 0–100 confidence is a setup-QUALITY score, NOT a probability of profit. ``calibration()``
reports how scores have mapped to realised outcomes so it can be judged empirically.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from .econ import EconEvent
from .instruments import INSTRUMENTS
from .models import Decision as DecisionRow
from .sessions import SessionInfo
from .strategies.base import Signal

STRONG_BUY, BUY = "STRONG BUY CANDIDATE", "BUY CANDIDATE"
STRONG_SELL, SELL = "STRONG SELL CANDIDATE", "SELL CANDIDATE"
WAIT, NO_TRADE, EXIT, HIGH_RISK = "WAIT", "NO TRADE", "EXIT", "HIGH RISK"
ACTIONABLE = (STRONG_BUY, BUY, STRONG_SELL, SELL)
WAIT_HINTS = ("waiting", "pullback in progress", "not available yet", "no sweep or accepted")


@dataclass
class MarketContext:
    symbol: str
    bid: float | None
    ask: float | None
    spread_pips: float | None
    spread_limit_pips: float
    atr_percentile: float | None
    session: SessionInfo
    data_ready: bool
    data_issues: list[str] = field(default_factory=list)
    strength: dict[str, float] = field(default_factory=dict)  # derived currency strength
    us10y_trend: str | None = None
    upcoming: list[EconEvent] = field(default_factory=list)  # relevant events next ~24h
    blackout: EconEvent | None = None
    now: datetime | None = None


@dataclass
class Evaluation:
    classification: str
    confidence: int
    breakdown: dict
    risk_flags: list[str]
    explanation: str
    actionable: bool
    events: list[dict] = field(default_factory=list)


def _f(x, d=None):
    try:
        v = float(x)
        return v if math.isfinite(v) else d
    except (TypeError, ValueError):
        return d


def atr_percentile(atr: np.ndarray, window: int = 120) -> float | None:
    a = atr[~np.isnan(atr)][-window:]
    if len(a) < 30:
        return None
    return float((a < a[-1]).mean())


def evaluate(sig: Signal, m: MarketContext, strategy_penalty: tuple[int, str] | None = None, has_position: str | None = None) -> Evaluation:
    inst = INSTRUMENTS[sig.symbol]
    flags: list[str] = []
    if not m.data_ready:
        flags.append("market data incomplete/stale: " + "; ".join(m.data_issues)[:200])
    if not m.session.market_open:
        flags.append("market closed")
    if m.spread_pips is not None and m.spread_pips > m.spread_limit_pips:
        flags.append(f"spread {m.spread_pips:.1f} pips exceeds {m.spread_limit_pips}")
    if m.blackout is not None:
        e = m.blackout
        flags.append(f"news blackout: {e.currency} {e.title} at {e.time:%H:%M} UTC")
    if m.atr_percentile is not None and m.atr_percentile > 0.97:
        flags.append("extreme volatility (ATR in top 3% of recent range)")
    events = [e.to_dict() for e in m.upcoming[:6]]

    if sig.direction == "exit":
        holds = has_position == sig.features.get("exit_for")
        return Evaluation(EXIT if holds else NO_TRADE, 0, {}, flags, f"{sig.strategy}: exit conditions — " + "; ".join(sig.reasons), holds, events)
    if sig.direction not in ("buy", "sell"):
        reason = "; ".join(sig.reasons) or "no setup"
        cls = WAIT if any(h in reason for h in WAIT_HINTS) else NO_TRADE
        if flags and cls == WAIT:
            cls = HIGH_RISK
            reason += " [risk: " + "; ".join(flags) + "]"
        return Evaluation(cls, 0, {}, flags, f"{sig.strategy}: {reason}", False, events)

    side = sig.direction
    sg = 1 if side == "buy" else -1
    f = sig.features
    b: dict[str, dict] = {}

    def add(name, pts, maxp, why):
        b[name] = {"points": round(max(0.0, min(pts, maxp)), 2), "max": maxp, "why": why}

    cats = sig.categories
    add("confluence", {3: 12, 4: 18}.get(len(cats), 22 if len(cats) >= 5 else 0), 22, f"{len(cats)} independent evidence categories: {', '.join(sorted(cats))}")
    add("signal_strength", 13 * sig.strength, 13, f"strategy conviction {sig.strength:.2f}")
    h1 = (f.get("h1") or {}).get("trend", "unknown")
    h4 = (f.get("h4") or {}).get("trend", "unknown")
    want = "up" if side == "buy" else "down"
    against = "down" if side == "buy" else "up"
    pts = 15 if (h1 == want and h4 in (want, "unknown")) else 10 if h1 == want else 0 if against in (h1, h4) else 5
    add("multi_timeframe", pts, 15, f"1h {h1}, 4h {h4}")
    add("session", 10 * m.session.quality, 10, f"{m.session.label}")
    r = sig.risk_per_unit or 0
    if r > 0 and m.spread_pips is not None:
        cost_r = (m.spread_pips + 2 * inst.slippage_pips) * inst.pip_size / r
        add("costs", 10 * (1 - min(cost_r / 0.25, 1)), 10, f"spread + slippage = {cost_r:.2f}R of the stop distance")
    else:
        add("costs", 0, 10, "cost estimate unavailable")
    ap = m.atr_percentile
    add("volatility", 4 if ap is None else (10 if 0.2 <= ap <= 0.85 else 5 if ap <= 0.95 else 1), 10,
        "ATR percentile n/a" if ap is None else f"ATR at {ap:.0%} percentile of recent range")
    if inst.asset_class == "gold":
        usd = m.strength.get("USD")
        score, why = 5, []
        if usd is not None:
            score += 3 if -sg * usd > 0.05 else (-3 if sg * usd > 0.05 else 0)
            why.append(f"USD strength {usd:+.2f}%")
        if m.us10y_trend in ("rising", "falling"):
            good = (side == "buy") == (m.us10y_trend == "falling")
            score += 2 if good else -2
            why.append(f"US10Y {m.us10y_trend}")
        add("macro", score, 10, ", ".join(why) or "USD/yields data unavailable")
    else:
        bs, qs = m.strength.get(inst.base), m.strength.get(inst.quote)
        if bs is None or qs is None:
            add("currency_strength", 4, 10, "currency strength unavailable")
        else:
            diff = sg * (bs - qs)
            add("currency_strength", 10 if diff > 0.1 else 6 if diff > 0 else 0, 10, f"{inst.base} {bs:+.2f}% vs {inst.quote} {qs:+.2f}%")
    rr = sig.rr or 0
    add("structure_rr", 10 if rr >= 3 else 7 if rr >= 2 else 3, 10, f"gross {rr:.1f}R to first structural target")
    score = sum(x["points"] for x in b.values())
    soon = [e for e in m.upcoming if e.impact == "High" and m.now and 0 <= (e.time - m.now).total_seconds() <= 7200]
    if soon:
        score -= 8
        b["event_risk"] = {"points": -8, "max": 0, "why": f"high-impact {soon[0].currency} {soon[0].title} within 2h"}
    if strategy_penalty and strategy_penalty[0]:
        score -= strategy_penalty[0]
        b["track_record"] = {"points": -strategy_penalty[0], "max": 0, "why": strategy_penalty[1]}
    conf = int(round(max(0, min(100, score))))
    if flags:
        cls = HIGH_RISK
    elif conf >= 75:
        cls = STRONG_BUY if side == "buy" else STRONG_SELL
    elif conf >= 60:
        cls = BUY if side == "buy" else SELL
    elif conf >= 45:
        cls = WAIT
    else:
        cls = NO_TRADE
    weak = [f"{k.replace('_', ' ')} ({v['why']})" for k, v in sorted(b.items(), key=lambda kv: kv[1]["points"] - kv[1]["max"])[:2]
            if v["max"] and v["points"] < v["max"] * 0.5]
    expl = (f"{side.upper()} {inst.display} ({sig.strategy}, {sig.timeframe}). Evidence: " + "; ".join(sig.reasons[:5]) +
            f". Entry ≈{sig.entry:.{inst.digits}f}, stop {sig.stop:.{inst.digits}f}, target {sig.targets[0]:.{inst.digits}f}"
            + (f" ({rr:.1f}R gross)" if rr else "") + f". Confidence {conf}/100 → {cls}."
            + (f" Weakest factors: {', '.join(weak)}." if weak else "") + (f" Risk flags: {'; '.join(flags)}." if flags else ""))
    return Evaluation(cls, conf, b, flags, expl, cls in ACTIONABLE, events)


def strategy_track_record(db: Session, strategy: str, min_trades: int = 30) -> tuple[int, str] | None:
    rows = db.execute(select(DecisionRow.outcome_r).where(DecisionRow.strategy == strategy, DecisionRow.executed.is_(True),
                                                          DecisionRow.outcome_r.is_not(None)).order_by(DecisionRow.id.desc()).limit(200)).scalars().all()
    if len(rows) < min_trades:
        return None
    exp = sum(rows) / len(rows)
    if exp < 0:
        return int(min(15, round(-exp * 20))), f"{strategy} expectancy {exp:+.2f}R over last {len(rows)} trades"
    return 0, f"{strategy} expectancy {exp:+.2f}R over last {len(rows)} trades"


def calibration(db: Session, buckets=((0, 45), (45, 60), (60, 75), (75, 101))) -> list[dict]:
    rows = db.execute(select(DecisionRow.confidence, DecisionRow.outcome, DecisionRow.outcome_r)
                      .where(DecisionRow.executed.is_(True), DecisionRow.outcome.is_not(None))).all()
    out = []
    for lo, hi in buckets:
        sel = [r for r in rows if lo <= r[0] < hi]
        n = len(sel)
        wins = sum(1 for r in sel if r[1] == "win")
        out.append({"bucket": f"{lo}-{min(hi, 100)}", "trades": n, "win_rate": round(wins / n * 100, 1) if n else None,
                    "avg_r": round(sum(r[2] or 0 for r in sel) / n, 3) if n else None, "note": "insufficient sample" if n < 20 else ""})
    return out
