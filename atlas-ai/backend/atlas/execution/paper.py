"""Paper-trading execution engine.

Realistic simulation against LIVE market quotes:
* market buys fill at the ASK plus modelled slippage (base + half-spread + impact); sells at the BID minus slippage
* fills are capped at ``max_participation_pct`` of the last closed 1-minute candle's quote volume per tick →
  large orders fill partially over several ticks; unfilled remainder is cancelled after ``ENTRY_TIMEOUT_S``
* take-profits are resting limit orders: they fill at the limit price only when the bid trades THROUGH it (maker fee)
* stops are triggered when the bid touches the stop and fill at the bid (gap-through aware) minus slippage (taker fee)
* duplicate orders are impossible: client_order_id is derived from (mode, symbol, strategy, signal candle) and unique in the DB
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..logging import get_logger
from ..marketdata.types import Quote
from ..models import Account, Decision, Execution, Order, Position
from ..trading_config import FeeModel
from . import costs
from .rules import Action, PosState, RuleParams, apply, manage

log = get_logger("atlas.paper")
ENTRY_TIMEOUT_S = 120
EPS = 1e-12


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ExecEvent:
    kind: str  # filled | partial | opened | cancelled | stop_moved | closed | exit_partial | duplicate
    position_id: int | None
    symbol: str
    message: str
    data: dict


class PaperExecutor:
    mode = "paper"
    venue = "paper"

    def __init__(self, fees: FeeModel, rules: RuleParams | None = None):
        self.fees = fees
        self.rules = rules or RuleParams()

    # ------------------------------------------------------------------ entry
    def client_order_id(self, symbol: str, strategy: str, candle_time: int, purpose: str = "entry") -> str:
        return f"{self.mode}-{symbol}-{strategy}-{candle_time}-{purpose}"

    def open_position(self, db: Session, acct: Account, *, symbol: str, strategy: str, qty: float, entry_ref: float, stop: float,
                      tp1: float, tp2: float | None, quote: Quote, minute_qv: float | None, candle_time: int,
                      decision_id: int | None, risk_amount: float, reason: str) -> tuple[Position | None, list[ExecEvent]]:
        coid = self.client_order_id(symbol, strategy, candle_time)
        if db.execute(select(Order.id).where(Order.client_order_id == coid)).first():
            return None, [ExecEvent("duplicate", None, symbol, f"duplicate order {coid} prevented", {"client_order_id": coid})]
        pos = Position(account_id=acct.id, mode=self.mode, symbol=symbol, strategy=strategy, status="pending", planned_qty=qty,
                       planned_entry=entry_ref, stop_price=stop, initial_stop=stop, tp1=tp1, tp2=tp2, risk_amount=risk_amount,
                       entry_reason=reason, decision_id=decision_id, stop_history=[{"ts": utcnow().isoformat(), "stop": stop, "reason": "initial stop"}])
        db.add(pos)
        db.flush()
        order = Order(client_order_id=coid, account_id=acct.id, mode=self.mode, position_id=pos.id, symbol=symbol, side="buy",
                      type="market", purpose="entry", qty=qty, status="new", reason=reason, venue=self.venue)
        try:
            with db.begin_nested():
                db.add(order)
                db.flush()
        except IntegrityError:
            pos.status = "cancelled"
            pos.exit_reason = "duplicate order rejected"
            return None, [ExecEvent("duplicate", None, symbol, f"duplicate order {coid} rejected by database", {"client_order_id": coid})]
        events = self._fill_entry(db, acct, pos, order, quote, minute_qv)
        return pos, events

    def _record_fill(self, db: Session, order: Order, qty: float, price: float, ref: float, taker: bool) -> Execution:
        notional = qty * price
        f = costs.fee(self.fees, notional, taker)
        slip_bps = abs(price / ref - 1) * 1e4 if ref else 0.0
        ex = Execution(order_id=order.id, qty=qty, price=price, reference_price=ref, fee=f, slippage_bps=round(slip_bps, 3),
                       slippage_cost=abs(price - ref) * qty, liquidity="taker" if taker else "maker")
        db.add(ex)
        prev = order.filled_qty
        order.filled_qty = prev + qty
        order.avg_fill_price = ((order.avg_fill_price or 0) * prev + price * qty) / order.filled_qty
        order.fees += f
        order.status = "filled" if order.filled_qty >= order.qty - EPS else "partially_filled"
        return ex

    def _fill_entry(self, db: Session, acct: Account, pos: Position, order: Order, quote: Quote, minute_qv: float | None) -> list[ExecEvent]:
        remaining = order.qty - order.filled_qty
        if remaining <= EPS:
            return []
        ref = quote.ask
        cap_notional = (minute_qv or 0) * self.fees.max_participation_pct / 100
        fill_qty = remaining if cap_notional <= 0 else min(remaining, cap_notional / ref)
        slip = costs.slippage_bps(self.fees, fill_qty * ref, minute_qv, quote.spread_bps)
        price = costs.apply_slippage(ref, slip, "buy")
        # never spend more cash than available (spot, no leverage)
        max_affordable = acct.cash / (price * (1 + self.fees.taker_fee_bps / 1e4))
        fill_qty = min(fill_qty, max_affordable)
        if fill_qty <= EPS:
            return [self._cancel_entry(db, pos, order, "insufficient cash")]
        ex = self._record_fill(db, order, fill_qty, price, ref, taker=True)
        acct.cash -= fill_qty * price + ex.fee
        prev_qty = pos.qty
        pos.qty = prev_qty + fill_qty
        pos.entry_price = (pos.entry_price * prev_qty + price * fill_qty) / pos.qty
        pos.initial_qty = pos.qty
        pos.fees_paid += ex.fee
        pos.slippage_cost += ex.slippage_cost
        pos.last_price = quote.bid
        events = [ExecEvent("partial" if order.status == "partially_filled" else "filled", pos.id, pos.symbol,
                            f"BUY {fill_qty:.8g} {pos.symbol} @ {price:.8g} (ref ask {ref:.8g}, slippage {ex.slippage_bps:.1f} bps, fee {ex.fee:.4f})",
                            {"qty": fill_qty, "price": price, "fee": ex.fee, "slippage_bps": ex.slippage_bps})]
        if order.status == "filled":
            events.append(self._activate(db, pos))
        return events

    def _cancel_entry(self, db: Session, pos: Position, order: Order, why: str) -> ExecEvent:
        order.status = "cancelled" if order.filled_qty <= EPS else "partially_filled_cancelled"
        order.reason = (order.reason or "") + f" | remainder cancelled: {why}"
        if pos.qty <= EPS:
            pos.status = "cancelled"
            pos.closed_at = utcnow()
            pos.exit_reason = f"entry not filled: {why}"
            return ExecEvent("cancelled", pos.id, pos.symbol, f"entry cancelled ({why})", {})
        return self._activate(db, pos, note=f"partial entry ({pos.qty:.8g} of {order.qty:.8g}); remainder cancelled: {why}")

    def _activate(self, db: Session, pos: Position, note: str = "") -> ExecEvent:
        pos.status = "open"
        pos.opened_at = utcnow()
        pos.initial_qty = pos.qty
        pos.max_favorable = pos.max_adverse = pos.entry_price
        # resting protective orders (records of what the engine enforces)
        db.add(Order(client_order_id=f"{pos.mode}-pos{pos.id}-stop-0", account_id=pos.account_id, mode=pos.mode, position_id=pos.id,
                     symbol=pos.symbol, side="sell", type="stop", purpose="stop", qty=pos.qty, stop_price=pos.stop_price, status="open", venue=self.venue))
        tp1_qty = pos.qty * (self.rules.tp1_fraction if pos.tp2 else 1.0)
        db.add(Order(client_order_id=f"{pos.mode}-pos{pos.id}-tp1", account_id=pos.account_id, mode=pos.mode, position_id=pos.id,
                     symbol=pos.symbol, side="sell", type="limit", purpose="tp1", qty=tp1_qty, limit_price=pos.tp1, status="open", venue=self.venue))
        if pos.tp2:
            db.add(Order(client_order_id=f"{pos.mode}-pos{pos.id}-tp2", account_id=pos.account_id, mode=pos.mode, position_id=pos.id,
                         symbol=pos.symbol, side="sell", type="limit", purpose="tp2", qty=pos.qty - tp1_qty, limit_price=pos.tp2, status="open", venue=self.venue))
        db.flush()
        return ExecEvent("opened", pos.id, pos.symbol,
                         f"position open: {pos.qty:.8g} {pos.symbol} avg {pos.entry_price:.8g}; stop {pos.stop_price:.8g}, TP1 {pos.tp1:.8g}"
                         + (f", TP2 {pos.tp2:.8g}" if pos.tp2 else "") + (f" — {note}" if note else ""), {"entry": pos.entry_price, "qty": pos.qty})

    # ------------------------------------------------------------- monitoring
    def _state(self, pos: Position) -> PosState:
        fee_unit = pos.entry_price * (self.fees.taker_fee_bps * 2) / 1e4
        st = PosState(entry=pos.entry_price, qty=pos.qty, initial_qty=pos.initial_qty, stop=pos.stop_price, initial_stop=pos.initial_stop,
                      tp1=pos.tp1, tp2=pos.tp2, opened_ts=(pos.opened_at or utcnow()).timestamp(), tp1_hit=pos.tp1_hit,
                      high_water=pos.max_favorable or pos.entry_price, fee_per_unit=fee_unit)
        st.breakeven_set = any(h.get("breakeven") for h in (pos.stop_history or []))
        return st

    def on_tick(self, db: Session, acct: Account, pos: Position, quote: Quote, minute_qv: float | None,
                now_ts: float | None = None) -> list[ExecEvent]:
        now_ts = now_ts or time.time()
        events: list[ExecEvent] = []
        if pos.status == "pending":
            order = db.execute(select(Order).where(Order.position_id == pos.id, Order.purpose == "entry")).scalar_one()
            if (now_ts - order.created_at.timestamp()) > ENTRY_TIMEOUT_S:
                return [self._cancel_entry(db, pos, order, f"not filled within {ENTRY_TIMEOUT_S}s")]
            return self._fill_entry(db, acct, pos, order, quote, minute_qv)
        if pos.status != "open":
            return events
        bid = quote.bid
        pos.last_price = bid
        pos.max_favorable = max(pos.max_favorable or bid, bid)
        pos.max_adverse = min(pos.max_adverse or bid, bid)
        st = self._state(pos)
        for act in manage(st, bid, bid, bid, now_ts, self.rules):
            events.extend(self._execute(db, acct, pos, st, act, quote, minute_qv))
            if pos.status == "closed":
                break
        return events

    def _execute(self, db: Session, acct: Account, pos: Position, st: PosState, act: Action, quote: Quote, minute_qv) -> list[ExecEvent]:
        if act.kind == "move_stop":
            apply(st, act)
            old = pos.stop_price
            pos.stop_price = st.stop
            pos.stop_history = list(pos.stop_history or []) + [{"ts": utcnow().isoformat(), "stop": st.stop, "reason": act.reason,
                                                                 "breakeven": bool(act.meta.get("breakeven"))}]
            so = self._open_order(db, pos, "stop")
            if so:
                so.stop_price = st.stop
            return [ExecEvent("stop_moved", pos.id, pos.symbol, f"stop {old:.8g} → {st.stop:.8g}: {act.reason}", {"old": old, "new": st.stop})]
        qty = pos.qty if act.fraction >= 1 else pos.qty * act.fraction
        purpose = {"stop": "stop", "tp1": "tp1", "tp2": "tp2"}.get(act.kind, "exit")
        if act.kind in ("tp1", "tp2"):
            price, ref, taker = act.price, act.price, False  # resting limit filled at its price
        else:
            ref = quote.bid
            trigger = min(act.price, ref) if act.kind == "stop" else ref
            slip = costs.slippage_bps(self.fees, qty * trigger, minute_qv, quote.spread_bps) + (self.fees.base_slippage_bps if act.kind == "stop" else 0)
            price = costs.apply_slippage(trigger, slip, "sell")
            taker = True
        order = self._open_order(db, pos, purpose)
        if order is None:
            order = Order(client_order_id=f"{pos.mode}-pos{pos.id}-{purpose}-{int(time.time() * 1000)}", account_id=pos.account_id, mode=pos.mode,
                          position_id=pos.id, symbol=pos.symbol, side="sell", type="market", purpose=purpose, qty=qty, status="new", venue=self.venue)
            db.add(order)
            db.flush()
        order.qty = max(order.qty, qty)
        ex = self._record_fill(db, order, qty, price, ref if act.kind in ("tp1", "tp2") else quote.bid, taker)
        order.status = "filled"
        order.reason = act.reason
        acct.cash += qty * price - ex.fee
        pos.fees_paid += ex.fee
        pos.slippage_cost += ex.slippage_cost
        pos.exit_value += qty * price
        pos.exit_qty += qty
        pos.qty = max(0.0, pos.qty - qty)
        apply(st, act, qty)
        if act.kind == "tp1":
            pos.tp1_hit = True
        events = [ExecEvent("exit_partial" if pos.qty > EPS else "closed", pos.id, pos.symbol,
                            f"SELL {qty:.8g} {pos.symbol} @ {price:.8g} — {act.reason}", {"qty": qty, "price": price, "fee": ex.fee, "kind": act.kind})]
        if pos.qty <= EPS:
            self._finalize(db, pos, act.reason)
        else:
            so = self._open_order(db, pos, "stop")
            if so:
                so.qty = pos.qty
        return events

    def _open_order(self, db: Session, pos: Position, purpose: str) -> Order | None:
        return db.execute(select(Order).where(Order.position_id == pos.id, Order.purpose == purpose, Order.status == "open")).scalars().first()

    def _finalize(self, db: Session, pos: Position, reason: str) -> None:
        pos.status = "closed"
        pos.closed_at = utcnow()
        pos.qty = 0.0
        pos.exit_reason = reason
        pos.exit_price = pos.exit_value / pos.exit_qty if pos.exit_qty > 0 else None
        pos.gross_pnl = pos.exit_value - pos.entry_price * pos.exit_qty
        pos.net_pnl = pos.gross_pnl - pos.fees_paid
        for o in db.execute(select(Order).where(Order.position_id == pos.id, Order.status == "open")).scalars():
            o.status = "cancelled"
            o.reason = "position closed"
        if pos.decision_id:
            d = db.get(Decision, pos.decision_id)
            if d is not None:
                d.outcome = "win" if pos.net_pnl > 0 else ("loss" if pos.net_pnl < 0 else "flat")
                d.outcome_r = round(pos.net_pnl / pos.risk_amount, 4) if pos.risk_amount > 0 else None

    def close_position(self, db: Session, acct: Account, pos: Position, quote: Quote, minute_qv, reason: str) -> list[ExecEvent]:
        if pos.status == "pending":
            order = db.execute(select(Order).where(Order.position_id == pos.id, Order.purpose == "entry")).scalar_one()
            ev = [self._cancel_entry(db, pos, order, reason)]
            if pos.status != "open":
                return ev
        if pos.status != "open" or pos.qty <= EPS:
            return []
        st = self._state(pos)
        return self._execute(db, acct, pos, st, Action("time_exit", quote.bid, 1.0, reason), quote, minute_qv)
