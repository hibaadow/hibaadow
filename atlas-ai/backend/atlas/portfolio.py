"""Portfolio accounting and performance metrics (per mode: paper / live are never mixed)."""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Account, Position, PortfolioSnapshot
from .risk import OpenExposure, RiskContext


def get_account(db: Session, mode: str, starting_capital: float = 10_000.0) -> Account:
    acct = db.execute(select(Account).where(Account.mode == mode)).scalar_one_or_none()
    if acct is None:
        cap = starting_capital if mode == "paper" else 0.0
        acct = Account(mode=mode, starting_capital=cap, cash=cap)
        db.add(acct)
        db.flush()
    return acct


def open_positions(db: Session, acct: Account) -> list[Position]:
    return list(db.execute(select(Position).where(Position.account_id == acct.id, Position.status.in_(("pending", "open")))
                           .order_by(Position.id)).scalars())


def mark(db: Session, acct: Account, prices: dict[str, float]) -> dict:
    """Mark-to-market using the provided prices (bid for longs). Missing price → last known."""
    pos = open_positions(db, acct)
    value = unreal = 0.0
    for p in pos:
        px = prices.get(p.symbol) or p.last_price or p.entry_price
        value += p.qty * px
        unreal += p.qty * (px - p.entry_price)
    realized = db.execute(select(func.coalesce(func.sum(Position.net_pnl), 0.0)).where(
        Position.account_id == acct.id, Position.status == "closed")).scalar_one()
    # fees of partial exits/entries on open positions are already in cash; report realized from closed trades
    return {"equity": acct.cash + value, "cash": acct.cash, "positions_value": value, "unrealized": unreal,
            "realized_total": float(realized), "open_count": len(pos)}


def snapshot(db: Session, acct: Account, prices: dict[str, float]) -> PortfolioSnapshot:
    m = mark(db, acct, prices)
    s = PortfolioSnapshot(account_id=acct.id, equity=m["equity"], cash=m["cash"], positions_value=m["positions_value"],
                          unrealized=m["unrealized"], realized_total=m["realized_total"])
    db.add(s)
    db.flush()
    return s


def _period_start(now: datetime, period: str) -> datetime:
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "day":
        return day
    if period == "week":
        return day - timedelta(days=day.weekday())
    if period == "month":
        return day.replace(day=1)
    raise ValueError(period)


def equity_at(db: Session, acct: Account, when: datetime, fallback: float) -> float:
    """Equity at the first snapshot at/after ``when`` (or last before it)."""
    first_after = db.execute(select(PortfolioSnapshot.equity).where(PortfolioSnapshot.account_id == acct.id, PortfolioSnapshot.ts >= when)
                             .order_by(PortfolioSnapshot.ts).limit(1)).scalar_one_or_none()
    last_before = db.execute(select(PortfolioSnapshot.equity).where(PortfolioSnapshot.account_id == acct.id, PortfolioSnapshot.ts < when)
                             .order_by(PortfolioSnapshot.ts.desc()).limit(1)).scalar_one_or_none()
    if last_before is not None:
        return float(last_before)
    if first_after is not None:
        return float(first_after)
    return fallback


def risk_context(db: Session, acct: Account, prices: dict[str, float], now: datetime | None = None) -> RiskContext:
    now = now or datetime.now(timezone.utc)
    m = mark(db, acct, prices)
    eq = m["equity"]
    pos = open_positions(db, acct)
    exposures = [OpenExposure(p.symbol, p.qty * (prices.get(p.symbol) or p.last_price or p.entry_price) if p.status == "open" else p.planned_qty * p.planned_entry,
                              p.risk_amount) for p in pos]
    day0 = _period_start(now, "day")
    trades_today = db.execute(select(func.count(Position.id)).where(Position.account_id == acct.id, Position.created_at >= day0,
                                                                    Position.status != "cancelled")).scalar_one()
    closed = db.execute(select(Position.net_pnl, Position.closed_at).where(Position.account_id == acct.id, Position.status == "closed")
                        .order_by(Position.closed_at.desc()).limit(50)).all()
    streak, last_loss = 0, None
    for pnl, ts in closed:
        if pnl < 0:
            streak += 1
            last_loss = last_loss or ts
        else:
            break
    if last_loss is not None and last_loss.tzinfo is None:
        last_loss = last_loss.replace(tzinfo=timezone.utc)
    return RiskContext(equity=eq, cash=acct.cash, start_of_day_equity=equity_at(db, acct, day0, eq),
                       start_of_week_equity=equity_at(db, acct, _period_start(now, "week"), eq), open_positions=exposures,
                       trades_today=int(trades_today), consecutive_losses=streak, last_loss_at=last_loss, now=now)


def trade_metrics(pnls: list[float], risks: list[float] | None = None) -> dict:
    n = len(pnls)
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x <= 0]
    gp, gl = sum(wins), -sum(losses)
    out = {
        "total_trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / n * 100, 2) if n else None,
        "profit_factor": round(gp / gl, 3) if gl > 0 else (None if not wins else math.inf),
        "avg_win": round(gp / len(wins), 4) if wins else None,
        "avg_loss": round(-gl / len(losses), 4) if losses else None,
        "net_pnl": round(sum(pnls), 4),
        "expectancy": round(sum(pnls) / n, 4) if n else None,
    }
    if risks and len(risks) == n:
        rs = [p / r for p, r in zip(pnls, risks) if r > 0]
        out["expectancy_r"] = round(sum(rs) / len(rs), 4) if rs else None
    if out["profit_factor"] == math.inf:
        out["profit_factor"] = None
        out["profit_factor_note"] = "no losing trades yet"
    return out


def max_drawdown(equity: list[float]) -> tuple[float, list[float]]:
    peak, mdd, dd_series = -math.inf, 0.0, []
    for e in equity:
        peak = max(peak, e)
        dd = (e / peak - 1) * 100 if peak > 0 else 0.0
        dd_series.append(dd)
        mdd = min(mdd, dd)
    return round(mdd, 4), dd_series


def overview(db: Session, acct: Account, prices: dict[str, float]) -> dict:
    now = datetime.now(timezone.utc)
    m = mark(db, acct, prices)
    closed = list(db.execute(select(Position).where(Position.account_id == acct.id, Position.status == "closed")).scalars())
    tm = trade_metrics([p.net_pnl for p in closed], [p.risk_amount for p in closed])
    eqs = [e for (e,) in db.execute(select(PortfolioSnapshot.equity).where(PortfolioSnapshot.account_id == acct.id)
                                    .order_by(PortfolioSnapshot.ts)).all()]
    mdd, _ = max_drawdown(eqs + [m["equity"]]) if eqs else (0.0, [])
    periods = {}
    for period in ("day", "week", "month"):
        start_eq = equity_at(db, acct, _period_start(now, period), acct.starting_capital)
        periods[f"{period}_pnl"] = round(m["equity"] - start_eq, 4)
        periods[f"{period}_pnl_pct"] = round((m["equity"] / start_eq - 1) * 100, 4) if start_eq else 0.0
    return {"mode": acct.mode, "starting_capital": acct.starting_capital, "equity": round(m["equity"], 4),
            "cash": round(m["cash"], 4), "available_capital": round(m["cash"], 4), "positions_value": round(m["positions_value"], 4),
            "unrealized_pnl": round(m["unrealized"], 4), "realized_pnl": round(m["realized_total"], 4),
            "open_positions": m["open_count"], "max_drawdown_pct": mdd, **periods, **tm,
            "fees_paid": round(sum(p.fees_paid for p in closed), 4), "slippage_cost": round(sum(p.slippage_cost for p in closed), 4)}


def session_of(ts: datetime) -> str:
    h = ts.hour
    if 0 <= h < 8:
        return "Asia (00–08 UTC)"
    if 8 <= h < 13:
        return "Europe (08–13 UTC)"
    if 13 <= h < 21:
        return "US (13–21 UTC)"
    return "Late US (21–24 UTC)"


def analytics(db: Session, acct: Account) -> dict:
    snaps = db.execute(select(PortfolioSnapshot.ts, PortfolioSnapshot.equity).where(PortfolioSnapshot.account_id == acct.id)
                       .order_by(PortfolioSnapshot.ts)).all()
    closed = list(db.execute(select(Position).where(Position.account_id == acct.id, Position.status == "closed")
                             .order_by(Position.closed_at)).scalars())

    def resample(fmt):
        out = {}
        for ts, eq in snaps:
            out[fmt(ts)] = eq  # last value in the bucket
        return [{"t": k, "equity": round(v, 4)} for k, v in out.items()]

    daily = resample(lambda t: t.strftime("%Y-%m-%d"))
    weekly = resample(lambda t: (t - timedelta(days=t.weekday())).strftime("%Y-%m-%d"))
    monthly = resample(lambda t: t.strftime("%Y-%m"))
    intraday = [{"t": ts.isoformat(), "equity": round(eq, 4)} for ts, eq in snaps[-2000:]]
    mdd, dd = max_drawdown([eq for _, eq in snaps])
    by = lambda key: defaultdict(list)  # noqa: E731
    groups = {"strategy": by(0), "asset": by(0), "session": by(0)}
    for p in closed:
        groups["strategy"][p.strategy].append(p)
        groups["asset"][p.symbol].append(p)
        groups["session"][session_of(p.opened_at or p.created_at)].append(p)

    def summarize(g):
        rows = []
        for k, ps in g.items():
            m = trade_metrics([p.net_pnl for p in ps], [p.risk_amount for p in ps])
            m.update(key=k, fees=round(sum(p.fees_paid for p in ps), 4), slippage=round(sum(p.slippage_cost for p in ps), 4))
            rows.append(m)
        return sorted(rows, key=lambda r: -r["net_pnl"])

    dist = [round(p.net_pnl / p.risk_amount, 3) for p in closed if p.risk_amount > 0]
    return {"mode": acct.mode, "equity_intraday": intraday, "equity_daily": daily, "equity_weekly": weekly, "equity_monthly": monthly,
            "drawdown": [{"t": ts.isoformat(), "dd": round(d, 4)} for (ts, _), d in zip(snaps[-2000:], dd[-2000:])],
            "max_drawdown_pct": mdd, "by_strategy": summarize(groups["strategy"]), "by_asset": summarize(groups["asset"]),
            "by_session": summarize(groups["session"]), "r_distribution": dist,
            "fees_total": round(sum(p.fees_paid for p in closed), 4), "slippage_total": round(sum(p.slippage_cost for p in closed), 4),
            "totals": trade_metrics([p.net_pnl for p in closed], [p.risk_amount for p in closed])}
