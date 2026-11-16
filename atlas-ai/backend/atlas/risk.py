"""Risk management engine — the final authority on whether a new gold/forex trade may open.

Hard rules (cannot be overridden by strategies, the AI analyst or commentary):
* kill switch, global trading switch, market hours, allowed sessions, rollover window
* daily / weekly loss limits on equity (unrealised P&L included)
* cooldown after consecutive losses; max open positions; max daily trades; one position per instrument
* high-impact economic events & central-bank decisions (news blackout)
* mandatory stop; minimum NET reward:risk (after spread, commission and slippage)
* spread and expected-slippage limits per instrument (in pips)
* position size from pip value × stop distance (+ costs), floored to the broker lot step;
  NEVER increased after losses (risk is halved after two consecutive losses) — no martingale
* margin: required margin, post-trade margin level and total effective leverage limits
* directional currency exposure (e.g. several trades that are all short USD) is capped
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .econ import EconEvent
from .execution import costs
from .instruments import INSTRUMENTS, Instrument, floor_lots, notional_usd, pip_value_usd
from .sessions import SessionInfo
from .trading_config import TradingConfig


@dataclass
class OpenExposure:
    symbol: str
    side: str
    lots: float
    notional_usd: float
    risk_usd: float
    margin_usd: float


@dataclass
class RiskContext:
    equity: float
    balance: float
    margin_used: float
    start_of_day_equity: float
    start_of_week_equity: float
    open_positions: list[OpenExposure]
    trades_today: int
    consecutive_losses: int
    last_loss_at: datetime | None
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def day_pnl_pct(self) -> float:
        return (self.equity / self.start_of_day_equity - 1) * 100 if self.start_of_day_equity > 0 else 0.0

    @property
    def week_pnl_pct(self) -> float:
        return (self.equity / self.start_of_week_equity - 1) * 100 if self.start_of_week_equity > 0 else 0.0

    @property
    def notional(self) -> float:
        return sum(p.notional_usd for p in self.open_positions)

    def currency_risk(self) -> dict[str, float]:
        """Net directional risk per currency (+ = long the currency)."""
        out: dict[str, float] = {}
        for p in self.open_positions:
            inst = INSTRUMENTS[p.symbol]
            sg = 1 if p.side == "buy" else -1
            out[inst.base] = out.get(inst.base, 0) + sg * p.risk_usd
            out[inst.quote] = out.get(inst.quote, 0) - sg * p.risk_usd
        return out


@dataclass
class TradeRequest:
    symbol: str
    side: str  # buy | sell
    entry: float  # executable price: ask for buys, bid for sells
    stop: float
    target: float
    spread_price: float
    mids: dict[str, float]
    session: SessionInfo
    news_event: EconEvent | None = None
    opposing_level: float | None = None
    data_ready: bool = True
    data_issues: list[str] = field(default_factory=list)


@dataclass
class Sizing:
    lots: float
    risk_amount: float
    loss_per_lot: float
    target: float
    net_rr: float
    notional_usd: float
    margin_usd: float
    pip_value_usd: float
    stop_pips: float
    costs: dict
    notes: list[str] = field(default_factory=list)


@dataclass
class RiskDecision:
    approved: bool
    sizing: Sizing | None = None
    checks: list[dict] = field(default_factory=list)
    blocking: list[str] = field(default_factory=list)
    halt: str | None = None

    def add(self, name: str, passed, detail: str) -> None:
        passed = bool(passed)
        self.checks.append({"name": name, "passed": passed, "detail": detail})
        if not passed:
            self.blocking.append(f"{name}: {detail}")

    @property
    def lots(self) -> float:
        return self.sizing.lots if self.sizing else 0.0


def gate_status(cfg: TradingConfig, ctx: RiskContext) -> RiskDecision:
    d = RiskDecision(approved=True)
    r = cfg.risk
    d.add("kill_switch", not cfg.kill_switch, "emergency stop engaged" if cfg.kill_switch else "off")
    d.add("trading_enabled", cfg.trading_enabled, "global trading switch " + ("on" if cfg.trading_enabled else "OFF"))
    day_ok = ctx.day_pnl_pct > -r.max_daily_loss_pct
    d.add("daily_loss_limit", day_ok, f"day P&L {ctx.day_pnl_pct:+.2f}% vs limit -{r.max_daily_loss_pct}%")
    week_ok = ctx.week_pnl_pct > -r.max_weekly_loss_pct
    d.add("weekly_loss_limit", week_ok, f"week P&L {ctx.week_pnl_pct:+.2f}% vs limit -{r.max_weekly_loss_pct}%")
    d.halt = None if day_ok and week_ok else ("daily_loss_limit" if not day_ok else "weekly_loss_limit")
    cooling = (ctx.consecutive_losses >= r.consecutive_loss_cooldown and ctx.last_loss_at is not None
               and ctx.now - ctx.last_loss_at < timedelta(minutes=r.cooldown_minutes))
    detail = f"{ctx.consecutive_losses} consecutive losses"
    if cooling:
        left = timedelta(minutes=r.cooldown_minutes) - (ctx.now - ctx.last_loss_at)
        detail += f" — cooldown {int(left.total_seconds() // 60)} min remaining"
    d.add("loss_cooldown", not cooling, detail)
    d.add("max_open_positions", len(ctx.open_positions) < r.max_open_positions, f"{len(ctx.open_positions)}/{r.max_open_positions} open")
    d.add("max_daily_trades", ctx.trades_today < r.max_daily_trades, f"{ctx.trades_today}/{r.max_daily_trades} trades today")
    d.approved = not d.blocking
    return d


def effective_margin_rate(cfg: TradingConfig, inst: Instrument) -> float:
    """Broker margin rate, never looser than the configured account leverage."""
    return max(inst.margin_rate, 1.0 / cfg.paper_leverage)


def size_position(cfg: TradingConfig, inst: Instrument, side: str, equity: float, margin_used: float, open_notional: float,
                  consecutive_losses: int, entry: float, stop: float, target: float, spread_price: float, mids: dict[str, float],
                  news: bool = False) -> Sizing | None:
    r, cm = cfg.risk, cfg.costs
    pv = pip_value_usd(inst, mids)
    if pv is None:
        return None
    sg = 1 if side == "buy" else -1
    notes: list[str] = []
    risk_pct = r.risk_per_trade_pct
    if consecutive_losses >= 2:
        risk_pct /= 2
        notes.append(f"risk halved to {risk_pct}% after {consecutive_losses} consecutive losses (never increased to recover)")
    risk_budget = max(equity, 0.0) * risk_pct / 100
    stop_pips = inst.to_pips((entry - stop) * sg)
    stop_slip = costs.slippage_pips(inst, cm, news, stop=True)
    comm_rt_per_lot = 2 * costs.commission_per_side(inst, 1.0, cm)
    loss_per_lot = (stop_pips + stop_slip) * pv + comm_rt_per_lot
    lots = floor_lots(inst, risk_budget / loss_per_lot) if loss_per_lot > 0 else 0.0
    rate = effective_margin_rate(cfg, inst)
    unit_notional = notional_usd(inst, 1.0, entry, mids) or 0.0
    caps = {}
    if unit_notional > 0:
        caps["effective leverage"] = (r.max_effective_leverage * equity - open_notional) / unit_notional
        max_margin_total = equity / (r.min_margin_level_pct / 100)
        caps["margin level"] = (max_margin_total - margin_used) / (unit_notional * rate)
    for name, cap in caps.items():
        capped = floor_lots(inst, max(cap, 0.0))
        if capped < lots:
            lots = capped
            notes.append(f"size capped by {name} limit")
    need_pips = (r.min_risk_reward * loss_per_lot + comm_rt_per_lot) / pv
    needed = entry + sg * need_pips * inst.pip_size
    tgt = target if sg * (target - needed) >= 0 else needed
    if tgt != target:
        notes.append(f"TP1 moved {inst.round_price(target)} → {inst.round_price(tgt)} so net R:R ≥ {r.min_risk_reward} after costs")
    tgt = inst.round_price(tgt + sg * inst.pip_size / 10)  # round away from entry, never below the requirement
    reward_per_lot = inst.to_pips((tgt - entry) * sg) * pv - comm_rt_per_lot
    net_rr = reward_per_lot / loss_per_lot if loss_per_lot > 0 else 0.0
    ce = costs.estimate(inst, lots, spread_price, mids, cm, news)
    return Sizing(lots, lots * loss_per_lot, loss_per_lot, tgt, net_rr, lots * unit_notional, lots * unit_notional * rate,
                  pv, round(stop_pips, 2), ce.to_dict() if ce else {}, notes)


def evaluate_trade(cfg: TradingConfig, ctx: RiskContext, req: TradeRequest) -> RiskDecision:
    d = gate_status(cfg, ctx)
    inst = INSTRUMENTS[req.symbol]
    r = cfg.risk
    sg = 1 if req.side == "buy" else -1
    d.add("market_data", req.data_ready, "fresh and complete" if req.data_ready else "; ".join(req.data_issues)[:300])
    d.add("market_open", req.session.market_open, "market open" if req.session.market_open else "market closed")
    allowed = set(cfg.sessions.allowed_sessions)
    if cfg.sessions.allow_asia_for_asia_pairs and ({inst.base, inst.quote} & {"JPY", "AUD", "NZD"}):
        allowed |= {"Tokyo", "Sydney"}
    in_session = bool(set(req.session.active) & allowed)
    d.add("trading_session", in_session, f"active: {req.session.label}; allowed: {', '.join(sorted(allowed))}")
    if cfg.sessions.avoid_rollover:
        d.add("rollover_window", not req.session.rollover, "inside the daily rollover window (wide spreads)" if req.session.rollover else "clear")
    if cfg.news.enabled:
        e = req.news_event
        d.add("news_blackout", e is None,
              f"{e.currency} {e.title} at {e.time:%H:%M} UTC ({'central bank' if e.central_bank else 'high impact'})" if e else "no high-impact event in window")
    d.add("one_position_per_instrument", all(p.symbol != req.symbol for p in ctx.open_positions), f"no existing {inst.display} position")
    stop_ok = req.stop is not None and req.stop > 0 and sg * (req.entry - req.stop) > 0
    d.add("mandatory_stop", stop_ok, f"stop {req.stop} on the protective side of entry {req.entry}" if stop_ok else "missing/invalid stop-loss")
    if not stop_ok:
        d.approved = False
        return d
    spread_pips = inst.to_pips(req.spread_price)
    lim = r.spread_limits_pips.get(req.symbol, inst.max_spread_pips)
    d.add("spread", spread_pips <= lim, f"{spread_pips:.1f} pips vs max {lim}")
    news = req.news_event is not None
    exp_slip = costs.slippage_pips(inst, cfg.costs, news)
    slim = r.max_slippage_pips.get(req.symbol, inst.slippage_pips * 4)
    d.add("slippage", exp_slip <= slim, f"expected {exp_slip:.1f} pips vs max {slim}")
    sz = size_position(cfg, inst, req.side, ctx.equity, ctx.margin_used, ctx.notional, ctx.consecutive_losses, req.entry, req.stop,
                       req.target, req.spread_price, req.mids, news)
    if sz is None:
        d.add("pip_value", False, f"no live conversion rate for {inst.quote}→USD")
        d.approved = False
        return d
    d.sizing = sz
    for n in sz.notes:
        d.checks.append({"name": "sizing", "passed": True, "detail": n})
    d.add("min_lot", sz.lots >= inst.min_lot - 1e-9,
          f"{sz.lots:.2f} lots (broker minimum {inst.min_lot}); stop {sz.stop_pips:.1f} pips × ${sz.pip_value_usd:.2f}/pip/lot")
    d.add("risk_reward", sz.net_rr >= r.min_risk_reward - 1e-6, f"net R:R {sz.net_rr:.2f} after spread, commission and slippage (min {r.min_risk_reward})")
    if req.opposing_level is not None and sg * (req.opposing_level - sz.target) < 0:
        d.add("room_to_target", False, f"opposing level {req.opposing_level:.6g} sits before the required target {sz.target:.6g}")
    d.add("risk_budget", sz.risk_amount <= ctx.equity * r.risk_per_trade_pct / 100 * 1.0001,
          f"${sz.risk_amount:,.2f} at risk ({sz.risk_amount / ctx.equity * 100 if ctx.equity else 0:.3f}% of equity)")
    margin_after = ctx.margin_used + sz.margin_usd
    level = ctx.equity / margin_after * 100 if margin_after > 0 else float("inf")
    d.add("margin_level", level >= r.min_margin_level_pct, f"margin level after trade {level:,.0f}% (min {r.min_margin_level_pct:.0f}%)")
    lev = (ctx.notional + sz.notional_usd) / ctx.equity if ctx.equity > 0 else float("inf")
    d.add("effective_leverage", lev <= r.max_effective_leverage + 1e-9, f"{lev:.2f}:1 total exposure (max {r.max_effective_leverage}:1)")
    cr = ctx.currency_risk()
    base_new = cr.get(inst.base, 0) + sg * sz.risk_amount
    quote_new = cr.get(inst.quote, 0) - sg * sz.risk_amount
    lim_c = ctx.equity * r.max_risk_per_currency_pct / 100
    d.add("currency_exposure", max(abs(base_new), abs(quote_new)) <= lim_c + 1e-6,
          f"net {inst.base} ${base_new:+,.0f} / {inst.quote} ${quote_new:+,.0f} risk (limit ${lim_c:,.0f} per currency)")
    d.approved = not d.blocking
    return d
