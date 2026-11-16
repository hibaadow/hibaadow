"""Paper-trading broker for gold & forex (default mode).

Simulated against LIVE quotes from the configured data source:
* BUY market orders fill at the ASK + modelled slippage; SELL at the BID − slippage. Positions are
  closed on the opposite side (longs at the bid, shorts at the ask), so the spread is always paid.
* Commission per lot per side (configurable). Balance changes only by realised P&L and commission
  (margin account) — notional is never deducted from cash.
* Stops trigger when the closing-side price touches them and fill at that price (gap-aware) minus stop
  slippage; take-profits are resting limits that fill at their price only when traded through.
* P&L is converted to USD with live rates at the time of each fill.
* Duplicate orders are impossible: client_order_id = (mode, symbol, strategy, signal candle) is unique.
* Retail-sized FX/gold orders are assumed to fill completely (no partial fills are simulated).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..instruments import INSTRUMENTS, pip_value_usd, to_usd_rate
from ..marketdata.types import Quote
from ..models import Account, Decision, Execution, Order, Position
from ..trading_config import CostModel
from . import costs
from .rules import Action, PosState, RuleParams, apply, manage

EPS = 1e-9


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ExecEvent:
    kind: str  # opened | stop_moved | exit_partial | closed | duplicate | rejected
    position_id: int | None
    symbol: str
    message: str
    data: dict


def close_price(q: Quote, side: str) -> float:
    return q.bid if side == "buy" else q.ask


def unrealized_usd(pos: Position, q: Quote | None, mids: dict[str, float]) -> float:
    if q is None or pos.status != "open":
        return 0.0
    inst = INSTRUMENTS[pos.symbol]
    rate = to_usd_rate(inst.quote, mids) or 0.0
    sg = 1 if pos.side == "buy" else -1
    return sg * (close_price(q, pos.side) - pos.entry_price) * pos.qty * inst.contract_size * rate


class PaperExecutor:
    mode = "paper"
    venue = "paper"

    def __init__(self, cm: CostModel, rules: RuleParams | None = None):
        self.cm = cm
        self.rules = rules or RuleParams()

    def client_order_id(self, symbol: str, strategy: str, candle_time: int, purpose: str = "entry") -> str:
        return f"{self.mode}-{symbol}-{strategy}-{candle_time}-{purpose}"

    def open_position(self, db: Session, acct: Account, *, symbol: str, side: str, strategy: str, lots: float, stop: float, tp1: float,
                      tp2: float | None, quote: Quote, mids: dict[str, float], candle_time: int, decision_id: int | None,
                      risk_amount: float, reason: str, news: bool = False) -> tuple[Position | None, list[ExecEvent]]:
        inst = INSTRUMENTS[symbol]
        coid = self.client_order_id(symbol, strategy, candle_time)
        if db.execute(select(Order.id).where(Order.client_order_id == coid)).first():
            return None, [ExecEvent("duplicate", None, symbol, f"duplicate order {coid} prevented", {"client_order_id": coid})]
        ref = quote.ask if side == "buy" else quote.bid
        slip = costs.slippage_pips(inst, self.cm, news)
        price = inst.round_price(costs.apply_slippage(ref, slip, inst, side))
        pv = pip_value_usd(inst, mids) or 0.0
        pos = Position(account_id=acct.id, mode=self.mode, symbol=symbol, strategy=strategy, side=side, status="open", opened_at=utcnow(),
                       qty=lots, initial_qty=lots, planned_qty=lots, entry_price=price, planned_entry=ref, stop_price=stop, initial_stop=stop,
                       tp1=tp1, tp2=tp2, risk_amount=risk_amount, entry_reason=reason, decision_id=decision_id, pip_value_usd=pv,
                       max_favorable=price, max_adverse=price, last_price=close_price(quote, side),
                       stop_history=[{"ts": utcnow().isoformat(), "stop": stop, "reason": "initial stop"}])
        db.add(pos)
        db.flush()
        order = Order(client_order_id=coid, account_id=acct.id, mode=self.mode, position_id=pos.id, symbol=symbol, side=side, type="market",
                      purpose="entry", qty=lots, status="new", reason=reason, venue=self.venue)
        try:
            with db.begin_nested():
                db.add(order)
                db.flush()
        except IntegrityError:
            pos.status = "cancelled"
            pos.exit_reason = "duplicate order rejected"
            return None, [ExecEvent("duplicate", None, symbol, f"duplicate order {coid} rejected by database", {})]
        comm = costs.commission_per_side(inst, lots, self.cm)
        slip_usd = slip * pv * lots
        self._fill(db, order, lots, price, ref, comm, slip_usd, True)
        acct.cash -= comm
        pos.fees_paid += comm
        pos.commission += comm
        pos.slippage_cost += slip_usd
        self._protective_orders(db, pos)
        return pos, [ExecEvent("opened", pos.id, symbol,
                               f"{side.upper()} {lots:.2f} lots {inst.display} @ {price:.{inst.digits}f} (ref {ref:.{inst.digits}f}, slippage {slip:.1f} pips, "
                               f"commission ${comm:.2f}); SL {stop:.{inst.digits}f}, TP1 {tp1:.{inst.digits}f}" + (f", TP2 {tp2:.{inst.digits}f}" if tp2 else ""),
                               {"lots": lots, "price": price, "side": side})]

    def _fill(self, db, order: Order, lots, price, ref, fee, slip_usd, taker) -> Execution:
        inst = INSTRUMENTS[order.symbol]
        ex = Execution(order_id=order.id, qty=lots, price=price, reference_price=ref, fee=fee,
                       slippage_bps=round(inst.to_pips(abs(price - ref)), 3), slippage_cost=slip_usd, liquidity="taker" if taker else "maker")
        db.add(ex)
        prev = order.filled_qty
        order.filled_qty = prev + lots
        order.avg_fill_price = ((order.avg_fill_price or 0) * prev + price * lots) / order.filled_qty
        order.fees += fee
        order.status = "filled"
        return ex

    def _protective_orders(self, db: Session, pos: Position) -> None:
        close_side = "sell" if pos.side == "buy" else "buy"
        tp1_lots = round(pos.qty * (self.rules.tp1_fraction if pos.tp2 else 1.0), 2)
        rows = [("stop", "stop", pos.qty, None, pos.stop_price), ("tp1", "limit", tp1_lots, pos.tp1, None)]
        if pos.tp2:
            rows.append(("tp2", "limit", round(pos.qty - tp1_lots, 2), pos.tp2, None))
        for purpose, typ, q, lim, stp in rows:
            db.add(Order(client_order_id=f"{pos.mode}-pos{pos.id}-{purpose}", account_id=pos.account_id, mode=pos.mode, position_id=pos.id,
                         symbol=pos.symbol, side=close_side, type=typ, purpose=purpose, qty=q, limit_price=lim, stop_price=stp, status="open",
                         venue=self.venue))
        db.flush()

    def state(self, pos: Position) -> PosState:
        inst = INSTRUMENTS[pos.symbol]
        comm_unit = 2 * costs.commission_per_side(inst, 1.0, self.cm) / (pos.pip_value_usd or 1) * inst.pip_size
        st = PosState(pos.entry_price, pos.qty, pos.initial_qty, pos.stop_price, pos.initial_stop, pos.tp1, pos.tp2,
                      (pos.opened_at or utcnow()).timestamp(), pos.side, pos.tp1_hit, pos.max_favorable or pos.entry_price,
                      cost_per_unit=comm_unit + inst.pip_size * inst.slippage_pips, through=inst.pip_size * 0.1)
        st.breakeven_set = any(h.get("breakeven") for h in (pos.stop_history or []))
        return st

    def on_tick(self, db: Session, acct: Account, pos: Position, quote: Quote, mids: dict[str, float], now_ts: float | None = None,
                news: bool = False) -> list[ExecEvent]:
        if pos.status != "open":
            return []
        now_ts = now_ts or time.time()
        px = close_price(quote, pos.side)
        sg = 1 if pos.side == "buy" else -1
        pos.last_price = px
        pos.max_favorable = px if sg * (px - (pos.max_favorable or px)) > 0 else (pos.max_favorable or px)
        pos.max_adverse = px if sg * (px - (pos.max_adverse or px)) < 0 else (pos.max_adverse or px)
        st = self.state(pos)
        events: list[ExecEvent] = []
        for act in manage(st, px, px, px, now_ts, self.rules):
            events.extend(self.execute(db, acct, pos, st, act, quote, mids, news))
            if pos.status == "closed":
                break
        return events

    def execute(self, db, acct, pos: Position, st: PosState, act: Action, quote: Quote, mids, news=False) -> list[ExecEvent]:
        inst = INSTRUMENTS[pos.symbol]
        if act.kind == "move_stop":
            apply(st, act)
            old = pos.stop_price
            pos.stop_price = inst.round_price(st.stop)
            pos.stop_history = list(pos.stop_history or []) + [{"ts": utcnow().isoformat(), "stop": pos.stop_price, "reason": act.reason,
                                                                 "breakeven": bool(act.meta.get("breakeven"))}]
            so = self._open_order(db, pos, "stop")
            if so:
                so.stop_price = pos.stop_price
            return [ExecEvent("stop_moved", pos.id, pos.symbol, f"{inst.display} stop {old:.{inst.digits}f} → {pos.stop_price:.{inst.digits}f}: {act.reason}",
                              {"old": old, "new": pos.stop_price})]
        lots = round(pos.qty if act.fraction >= 1 else pos.qty * act.fraction, 2)
        lots = min(lots, pos.qty)
        close_side = "sell" if pos.side == "buy" else "buy"
        ref = close_price(quote, pos.side)
        sg = 1 if pos.side == "buy" else -1
        if act.kind in ("tp1", "tp2"):
            price, slip, taker = act.price, 0.0, False
        else:
            slip = costs.slippage_pips(inst, self.cm, news, stop=act.kind == "stop")
            trigger = act.price if act.kind == "stop" and sg * (ref - act.price) > 0 else ref  # gap → worse of stop/market
            price = inst.round_price(costs.apply_slippage(trigger, slip, inst, close_side))
            taker = True
        purpose = act.kind if act.kind in ("stop", "tp1", "tp2") else "exit"
        order = self._open_order(db, pos, purpose)
        if order is None:
            order = Order(client_order_id=f"{pos.mode}-pos{pos.id}-{purpose}-{int(time.time() * 1000)}", account_id=pos.account_id, mode=pos.mode,
                          position_id=pos.id, symbol=pos.symbol, side=close_side, type="market", purpose=purpose, qty=lots, status="new", venue=self.venue)
            db.add(order)
            db.flush()
        order.qty = lots
        pv = pip_value_usd(inst, mids) or pos.pip_value_usd
        comm = costs.commission_per_side(inst, lots, self.cm)
        slip_usd = slip * pv * lots
        self._fill(db, order, lots, price, ref, comm, slip_usd, taker)
        order.reason = act.reason
        rate = to_usd_rate(inst.quote, mids) or (pv / inst.pip_value_quote)
        gross = sg * (price - pos.entry_price) * lots * inst.contract_size * rate
        acct.cash += gross - comm
        pos.gross_pnl += gross
        pos.fees_paid += comm
        pos.commission += comm
        pos.slippage_cost += slip_usd
        pos.exit_value += price * lots
        pos.exit_qty += lots
        pos.qty = round(max(0.0, pos.qty - lots), 2)
        apply(st, act, lots)
        if act.kind == "tp1":
            pos.tp1_hit = True
        msg = f"{close_side.upper()} {lots:.2f} lots {inst.display} @ {price:.{inst.digits}f} — {act.reason} (P&L ${gross:+,.2f})"
        if pos.qty <= EPS:
            self._finalize(db, pos, act.reason)
            return [ExecEvent("closed", pos.id, pos.symbol, msg, {"lots": lots, "price": price, "kind": act.kind, "net_pnl": pos.net_pnl})]
        so = self._open_order(db, pos, "stop")
        if so:
            so.qty = pos.qty
        return [ExecEvent("exit_partial", pos.id, pos.symbol, msg, {"lots": lots, "price": price, "kind": act.kind})]

    def _open_order(self, db: Session, pos: Position, purpose: str) -> Order | None:
        return db.execute(select(Order).where(Order.position_id == pos.id, Order.purpose == purpose, Order.status == "open")).scalars().first()

    def _finalize(self, db: Session, pos: Position, reason: str) -> None:
        pos.status = "closed"
        pos.closed_at = utcnow()
        pos.qty = 0.0
        pos.exit_reason = reason
        pos.exit_price = pos.exit_value / pos.exit_qty if pos.exit_qty > 0 else None
        pos.net_pnl = pos.gross_pnl - pos.fees_paid - pos.swap
        for o in db.execute(select(Order).where(Order.position_id == pos.id, Order.status == "open")).scalars():
            o.status = "cancelled"
            o.reason = "position closed"
        if pos.decision_id:
            d = db.get(Decision, pos.decision_id)
            if d is not None:
                d.outcome = "win" if pos.net_pnl > 0 else ("loss" if pos.net_pnl < 0 else "flat")
                d.outcome_r = round(pos.net_pnl / pos.risk_amount, 4) if pos.risk_amount > 0 else None

    def close_position(self, db: Session, acct: Account, pos: Position, quote: Quote, mids, reason: str) -> list[ExecEvent]:
        if pos.status != "open" or pos.qty <= EPS:
            return []
        st = self.state(pos)
        return self.execute(db, acct, pos, st, Action("time_exit", close_price(quote, pos.side), 1.0, reason), quote, mids)
