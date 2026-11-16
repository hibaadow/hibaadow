"""Risk management engine — the final authority on whether a new trade may open.

Hard rules (cannot be overridden by strategies, AI scoring or commentary):
* kill switch / global disable / trading hours
* daily and weekly loss limits (equity based, includes unrealised P&L)
* cooldown after consecutive losses
* max open positions, max daily trades, one position per symbol
* mandatory stop below entry; minimum reward:risk after costs
* spread / slippage / liquidity / volume limits
* stale or inconsistent market data blocks trading
* position sizing from stop distance; size is never increased after losses
  (risk is a fixed fraction of CURRENT equity and is halved after 2 consecutive losses)
* spot only — notional can never exceed available cash (no leverage)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .execution import costs
from .trading_config import TradingConfig

MIN_NOTIONAL = 10.0


@dataclass
class OpenExposure:
    symbol: str
    value: float
    risk: float


@dataclass
class RiskContext:
    equity: float
    cash: float
    start_of_day_equity: float
    start_of_week_equity: float
    open_positions: list[OpenExposure]
    trades_today: int
    consecutive_losses: int
    last_loss_at: datetime | None
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def exposure(self) -> float:
        return sum(p.value for p in self.open_positions)

    @property
    def day_pnl_pct(self) -> float:
        return (self.equity / self.start_of_day_equity - 1) * 100 if self.start_of_day_equity > 0 else 0.0

    @property
    def week_pnl_pct(self) -> float:
        return (self.equity / self.start_of_week_equity - 1) * 100 if self.start_of_week_equity > 0 else 0.0


@dataclass
class TradeRequest:
    symbol: str
    entry: float  # reference price (ask for buys)
    stop: float
    target: float
    spread_bps: float
    minute_quote_volume: float | None
    liquidity_usd: float | None
    volume_24h_usd: float | None
    resistance: float | None = None
    data_ready: bool = True
    data_issues: list[str] = field(default_factory=list)


@dataclass
class RiskDecision:
    approved: bool
    qty: float = 0.0
    notional: float = 0.0
    risk_amount: float = 0.0
    est_slippage_bps: float = 0.0
    net_rr: float | None = None
    target: float | None = None
    checks: list[dict] = field(default_factory=list)
    blocking: list[str] = field(default_factory=list)
    halt: str | None = None  # set when a portfolio-level limit trips (daily/weekly loss)

    def add(self, name: str, passed: bool, detail: str) -> None:
        passed = bool(passed)
        self.checks.append({"name": name, "passed": passed, "detail": detail})
        if not passed:
            self.blocking.append(f"{name}: {detail}")


def gate_status(cfg: TradingConfig, ctx: RiskContext) -> RiskDecision:
    """Portfolio-level gates that apply before any individual trade is considered."""
    d = RiskDecision(approved=True)
    r = cfg.risk
    d.add("kill_switch", not cfg.kill_switch, "emergency kill switch engaged" if cfg.kill_switch else "off")
    d.add("trading_enabled", cfg.trading_enabled, "global trading switch" + (" on" if cfg.trading_enabled else " OFF"))
    if cfg.hours.enabled:
        ok = ctx.now.weekday() in cfg.hours.weekdays and cfg.hours.start_hour_utc <= ctx.now.hour < cfg.hours.end_hour_utc
        d.add("trading_hours", ok, f"window {cfg.hours.start_hour_utc:02d}:00–{cfg.hours.end_hour_utc:02d}:00 UTC")
    day_ok = ctx.day_pnl_pct > -r.max_daily_loss_pct
    d.add("daily_loss_limit", day_ok, f"day P&L {ctx.day_pnl_pct:+.2f}% vs limit -{r.max_daily_loss_pct}%")
    if not day_ok:
        d.halt = "daily_loss_limit"
    week_ok = ctx.week_pnl_pct > -r.max_weekly_loss_pct
    d.add("weekly_loss_limit", week_ok, f"week P&L {ctx.week_pnl_pct:+.2f}% vs limit -{r.max_weekly_loss_pct}%")
    if not week_ok:
        d.halt = d.halt or "weekly_loss_limit"
    cooling = (ctx.consecutive_losses >= r.consecutive_loss_cooldown and ctx.last_loss_at is not None
               and ctx.now - ctx.last_loss_at < timedelta(minutes=r.cooldown_minutes))
    detail = f"{ctx.consecutive_losses} consecutive losses"
    if cooling:
        remaining = timedelta(minutes=r.cooldown_minutes) - (ctx.now - ctx.last_loss_at)
        detail += f" — cooldown {int(remaining.total_seconds() // 60)} min remaining"
    d.add("loss_cooldown", not cooling, detail)
    d.add("max_open_positions", len(ctx.open_positions) < r.max_open_positions, f"{len(ctx.open_positions)}/{r.max_open_positions} open")
    d.add("max_daily_trades", ctx.trades_today < r.max_daily_trades, f"{ctx.trades_today}/{r.max_daily_trades} trades today")
    d.approved = not d.blocking
    return d


def evaluate_trade(cfg: TradingConfig, ctx: RiskContext, req: TradeRequest) -> RiskDecision:
    d = gate_status(cfg, ctx)
    r = cfg.risk
    fees = cfg.fees
    d.add("market_data", req.data_ready, "fresh and complete" if req.data_ready else "; ".join(req.data_issues)[:300])
    d.add("one_position_per_symbol", all(p.symbol != req.symbol for p in ctx.open_positions), f"no existing {req.symbol} position")
    stop_ok = req.stop is not None and 0 < req.stop < req.entry
    d.add("mandatory_stop", stop_ok, f"stop {req.stop} below entry {req.entry}" if stop_ok else "missing/invalid stop-loss")
    if not stop_ok:
        d.approved = False
        return d
    d.add("spread", req.spread_bps <= r.max_spread_bps, f"{req.spread_bps:.1f} bps vs max {r.max_spread_bps}")
    if req.liquidity_usd is not None:
        d.add("liquidity", req.liquidity_usd >= cfg.min_liquidity_usd, f"±1% depth ${req.liquidity_usd:,.0f} vs min ${cfg.min_liquidity_usd:,.0f}")
    else:
        d.add("liquidity", False, "order-book depth unavailable")
    if req.volume_24h_usd is not None:
        d.add("volume_24h", req.volume_24h_usd >= cfg.min_volume_24h_usd, f"${req.volume_24h_usd:,.0f} vs min ${cfg.min_volume_24h_usd:,.0f}")
    else:
        d.add("volume_24h", False, "24h volume unavailable")

    sz = size_position(cfg, ctx.equity, ctx.cash, ctx.exposure, ctx.consecutive_losses, req.entry, req.stop, req.target,
                       req.spread_bps, req.minute_quote_volume)
    for note in sz.notes:
        d.checks.append({"name": "sizing", "passed": True, "detail": note})
    d.est_slippage_bps = round(sz.slippage_bps, 2)
    d.add("slippage", sz.slippage_bps <= r.max_slippage_bps, f"estimated {sz.slippage_bps:.1f} bps vs max {r.max_slippage_bps}")
    if req.resistance is not None and req.resistance < sz.target:
        d.add("room_to_target", False, f"resistance {req.resistance:.8g} sits below required target {sz.target:.8g}")
    d.net_rr = round(sz.net_rr, 3)
    d.target = sz.target
    d.add("risk_reward", sz.net_rr >= r.min_risk_reward - 1e-9, f"net R:R {sz.net_rr:.2f} after fees+slippage (min {r.min_risk_reward})")
    qty, notional = sz.qty, sz.notional
    d.add("min_notional", notional >= MIN_NOTIONAL, f"${notional:,.2f} (min ${MIN_NOTIONAL})")
    d.qty = qty
    d.notional = notional
    d.risk_amount = sz.risk_amount
    d.add("risk_budget", d.risk_amount <= ctx.equity * r.risk_per_trade_pct / 100 * 1.0001,
          f"${d.risk_amount:,.2f} at risk ({d.risk_amount / ctx.equity * 100 if ctx.equity else 0:.3f}% of equity)")
    d.approved = not d.blocking
    return d


@dataclass
class Sizing:
    qty: float
    notional: float
    risk_amount: float
    slippage_bps: float
    target: float
    net_rr: float
    notes: list[str] = field(default_factory=list)


def size_position(cfg: TradingConfig, equity: float, cash: float, exposure: float, consecutive_losses: int, entry: float,
                  stop: float, target: float, spread_bps: float, minute_qv: float | None) -> Sizing:
    """Fixed-fractional sizing from the stop distance, including fees and modelled slippage.

    Size never increases after losses: risk is a fraction of CURRENT equity and is halved after
    two consecutive losses. Notional is capped by per-position exposure, remaining portfolio
    exposure and available cash (spot only — no leverage).
    """
    r, fees = cfg.risk, cfg.fees
    notes: list[str] = []
    risk_pct = r.risk_per_trade_pct
    if consecutive_losses >= 2:
        risk_pct /= 2
        notes.append(f"risk halved to {risk_pct}% after {consecutive_losses} consecutive losses")
    risk_amount = max(equity, 0) * risk_pct / 100
    qty = risk_amount / (entry - stop)
    for _ in range(3):  # iterate: slippage depends on size
        slip = costs.slippage_bps(fees, qty * entry, minute_qv, spread_bps)
        ef = costs.apply_slippage(entry, slip, "buy")
        sf = costs.apply_slippage(stop, slip + fees.base_slippage_bps, "sell")
        eff = ef * (1 + fees.taker_fee_bps / 1e4) - sf * (1 - fees.taker_fee_bps / 1e4)
        qty = risk_amount / eff if eff > 0 else 0.0
    notional = qty * entry
    caps = {"position exposure": equity * r.max_position_exposure_pct / 100,
            "portfolio exposure": max(0.0, equity * r.max_portfolio_exposure_pct / 100 - exposure),
            "available cash": max(0.0, cash * 0.98)}
    cap_name, cap = min(caps.items(), key=lambda kv: kv[1])
    if notional > cap:
        qty, notional = cap / entry, cap
        notes.append(f"size capped by {cap_name} (${cap:,.2f})")
    slip = costs.slippage_bps(fees, notional, minute_qv, spread_bps)
    ef = costs.apply_slippage(entry, slip, "buy")
    sf = costs.apply_slippage(stop, slip + fees.base_slippage_bps, "sell")
    buy_unit = ef * (1 + fees.taker_fee_bps / 1e4)
    risk_unit = buy_unit - sf * (1 - fees.taker_fee_bps / 1e4)
    needed = (buy_unit + r.min_risk_reward * risk_unit) / (1 - fees.maker_fee_bps / 1e4)
    tgt = max(target, needed)
    if tgt > target:
        notes.append(f"TP1 raised {target:.8g} → {tgt:.8g} so net R:R ≥ {r.min_risk_reward} after costs")
    net_rr = (tgt * (1 - fees.maker_fee_bps / 1e4) - buy_unit) / risk_unit if risk_unit > 0 else 0.0
    return Sizing(qty, notional, qty * risk_unit, slip, tgt, net_rr, notes)
