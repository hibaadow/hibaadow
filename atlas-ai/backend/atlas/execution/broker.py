"""Broker execution (OANDA / MT5) for demo and live accounts.

* Entry: market order with the stop-loss (and final take-profit) attached at the broker, so the
  position stays protected even if ATLAS stops running. A deterministic client id prevents duplicates.
* Management: TP1 partial close, breakeven / +1R stop moves and time stops are applied by modifying or
  partially closing the broker trade (same rules as paper and backtests).
* Reconciliation: each cycle, local open positions are compared with the broker's open trades; trades
  closed at the broker (SL/TP hit, manual close) are finalised locally with the broker's close price and P&L.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..brokers.base import BrokerError
from ..instruments import INSTRUMENTS, pip_value_usd
from ..logging import get_logger
from ..marketdata.types import Quote
from ..models import Account, Execution, Order, Position
from ..trading_config import CostModel
from .paper import ExecEvent, PaperExecutor, close_price
from .rules import RuleParams, apply, manage

log = get_logger("atlas.broker_exec")


def utcnow():
    return datetime.now(timezone.utc)


class BrokerExecutor:
    def __init__(self, broker, mode: str, cm: CostModel, rules: RuleParams | None = None):
        self.broker = broker
        self.mode = mode  # demo | live
        self.helper = PaperExecutor(cm, rules)  # reuse state/rule plumbing
        self.helper.mode = mode
        self.rules = self.helper.rules

    def client_order_id(self, symbol, strategy, candle_time) -> str:
        return f"atlas-{self.mode}-{symbol}-{strategy[:6]}-{candle_time // 1000}"

    async def open_position(self, db: Session, acct: Account, *, symbol, side, strategy, lots, stop, tp1, tp2, quote: Quote, mids,
                            candle_time, decision_id, risk_amount, reason, max_slippage_pips) -> tuple[Position | None, list[ExecEvent]]:
        inst = INSTRUMENTS[symbol]
        coid = self.client_order_id(symbol, strategy, candle_time)
        if db.execute(select(Order.id).where(Order.client_order_id == coid)).first():
            return None, [ExecEvent("duplicate", None, symbol, f"duplicate order {coid} prevented", {})]
        ref = quote.ask if side == "buy" else quote.bid
        bound = ref + (1 if side == "buy" else -1) * max_slippage_pips * inst.pip_size
        pos = Position(account_id=acct.id, mode=self.mode, symbol=symbol, strategy=strategy, side=side, status="pending", planned_qty=lots,
                       planned_entry=ref, stop_price=stop, initial_stop=stop, tp1=tp1, tp2=tp2, risk_amount=risk_amount, entry_reason=reason,
                       decision_id=decision_id, pip_value_usd=pip_value_usd(inst, mids) or 0.0,
                       stop_history=[{"ts": utcnow().isoformat(), "stop": stop, "reason": "initial stop (held at broker)"}])
        db.add(pos)
        db.flush()
        order = Order(client_order_id=coid, account_id=acct.id, mode=self.mode, position_id=pos.id, symbol=symbol, side=side, type="market",
                      purpose="entry", qty=lots, status="submitted", reason=reason, venue=self.broker.name)
        db.add(order)
        db.commit()  # persisted BEFORE sending: a crash can never cause a blind resend
        try:
            fill = await self.broker.market_order(symbol, side, lots, stop, tp2 or tp1, coid, bound, max_slippage_pips)
        except BrokerError as e:
            order.status, order.reason = "rejected", str(e)[:300]
            pos.status, pos.exit_reason = "cancelled", f"broker rejected: {str(e)[:200]}"
            return None, [ExecEvent("rejected", pos.id, symbol, f"{inst.display} order rejected by {self.broker.name}: {str(e)[:200]}", {})]
        order.status, order.external_id, order.filled_qty, order.avg_fill_price = "filled", fill.order_id, fill.lots, fill.price
        order.fees = fill.commission
        db.add(Execution(order_id=order.id, qty=fill.lots, price=fill.price, reference_price=ref, fee=fill.commission,
                         slippage_bps=round(inst.to_pips(abs(fill.price - ref)), 3), slippage_cost=0.0, liquidity="taker", tx_signature=fill.order_id))
        pos.status, pos.broker_id, pos.opened_at = "open", fill.broker_id, utcnow()
        pos.qty = pos.initial_qty = fill.lots
        pos.entry_price = fill.price
        pos.max_favorable = pos.max_adverse = fill.price
        pos.fees_paid = pos.commission = fill.commission
        return pos, [ExecEvent("opened", pos.id, symbol, f"{self.broker.name.upper()} {self.mode}: {side.upper()} {fill.lots:.2f} lots {inst.display} @ "
                               f"{fill.price:.{inst.digits}f} (trade {fill.broker_id}); SL {stop:.{inst.digits}f} held at broker", {"broker_id": fill.broker_id})]

    async def on_tick(self, db: Session, acct: Account, pos: Position, quote: Quote, mids) -> list[ExecEvent]:
        if pos.status != "open" or not pos.broker_id:
            return []
        inst = INSTRUMENTS[pos.symbol]
        px = close_price(quote, pos.side)
        pos.last_price = px
        st = self.helper.state(pos)
        events = []
        for act in manage(st, px, px, px, time.time(), self.rules):
            if act.kind == "stop":
                continue  # the broker-side stop executes it; reconciliation records the result
            try:
                if act.kind == "move_stop":
                    await self.broker.modify_stop(pos.broker_id, pos.symbol, act.price, pos.tp2)
                    apply(st, act)
                    pos.stop_price = inst.round_price(st.stop)
                    pos.stop_history = list(pos.stop_history or []) + [{"ts": utcnow().isoformat(), "stop": pos.stop_price, "reason": act.reason,
                                                                         "breakeven": bool(act.meta.get("breakeven"))}]
                    events.append(ExecEvent("stop_moved", pos.id, pos.symbol, f"{inst.display} broker stop → {pos.stop_price}: {act.reason}", {}))
                    continue
                lots = None if act.fraction >= 1 else round(pos.qty * act.fraction, 2)
                fill = await self.broker.close_trade(pos.broker_id, pos.symbol, lots)
                closed = fill.lots
                pos.gross_pnl += fill.realized_pnl
                pos.fees_paid += fill.commission
                pos.commission += fill.commission
                pos.swap += -fill.financing
                pos.exit_value += fill.price * closed
                pos.exit_qty += closed
                pos.qty = round(max(0.0, pos.qty - closed), 2)
                apply(st, act, closed)
                if act.kind == "tp1":
                    pos.tp1_hit = True
                if pos.qty <= 1e-9:
                    self.helper._finalize(db, pos, act.reason)
                events.append(ExecEvent("closed" if pos.status == "closed" else "exit_partial", pos.id, pos.symbol,
                                        f"{inst.display}: closed {closed:.2f} lots @ {fill.price} — {act.reason}", {}))
            except BrokerError as e:
                events.append(ExecEvent("rejected", pos.id, pos.symbol, f"broker action failed ({act.kind}): {str(e)[:200]}", {}))
            if pos.status == "closed":
                break
        return events

    async def reconcile(self, db: Session, acct: Account, positions: list[Position]) -> list[ExecEvent]:
        try:
            live = {t.broker_id: t for t in await self.broker.open_trades()}
        except BrokerError as e:
            return [ExecEvent("rejected", None, "", f"reconciliation failed: {e}", {})]
        events = []
        for pos in positions:
            if pos.status != "open" or not pos.broker_id:
                continue
            t = live.get(pos.broker_id)
            if t is not None:
                pos.qty = t.lots
                if t.stop_loss:
                    pos.stop_price = t.stop_loss
                continue
            try:
                det = await self.broker.trade_details(pos.broker_id)
            except Exception as e:  # noqa: BLE001
                events.append(ExecEvent("rejected", pos.id, pos.symbol, f"could not fetch closed trade {pos.broker_id}: {str(e)[:120]}", {}))
                continue
            if det.get("state") != "CLOSED":
                continue
            pos.gross_pnl = det.get("realized_pnl", 0.0)
            pos.swap = -det.get("financing", 0.0)
            pos.fees_paid += det.get("commission", 0.0) or 0.0
            if det.get("close_price"):
                pos.exit_value += det["close_price"] * pos.qty
                pos.exit_qty += pos.qty
            self.helper._finalize(db, pos, "closed at broker (stop-loss / take-profit / manual)")
            pos.net_pnl = pos.gross_pnl - pos.fees_paid - pos.swap
            events.append(ExecEvent("closed", pos.id, pos.symbol, f"{INSTRUMENTS[pos.symbol].display} trade {pos.broker_id} closed at broker, "
                                    f"net ${pos.net_pnl:+,.2f}", {}))
        return events

    async def close_position(self, db, acct, pos: Position, reason: str) -> list[ExecEvent]:
        if pos.status != "open" or not pos.broker_id:
            return []
        try:
            fill = await self.broker.close_trade(pos.broker_id, pos.symbol, None)
        except BrokerError as e:
            return [ExecEvent("rejected", pos.id, pos.symbol, f"close failed: {e}", {})]
        pos.gross_pnl += fill.realized_pnl
        pos.fees_paid += fill.commission
        pos.exit_value += fill.price * fill.lots
        pos.exit_qty += fill.lots
        self.helper._finalize(db, pos, reason)
        return [ExecEvent("closed", pos.id, pos.symbol, f"{INSTRUMENTS[pos.symbol].display} closed at broker @ {fill.price} — {reason}", {})]
