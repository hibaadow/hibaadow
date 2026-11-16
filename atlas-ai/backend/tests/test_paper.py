import time

import pytest
from sqlalchemy import select

from atlas.execution.paper import ENTRY_TIMEOUT_S, PaperExecutor
from atlas.marketdata.types import Quote
from atlas.models import Decision, Execution, Order, Position
from atlas.portfolio import get_account, mark, overview, risk_context, snapshot
from atlas.trading_config import FeeModel

FEES = FeeModel(taker_fee_bps=10, maker_fee_bps=5, base_slippage_bps=2, impact_coefficient=0.1, max_participation_pct=10)


def q(bid, ask=None):
    return Quote("SOLUSDC", "test", bid, ask or bid * 1.0002, (bid + (ask or bid)) / 2)


def open_pos(db, ex, acct, qty=10.0, candle=1, mqv=10_000_000, stop=98.0, tp1=104.0, tp2=106.0, decision_id=None):
    return ex.open_position(db, acct, symbol="SOLUSDC", strategy="momentum", qty=qty, entry_ref=100.02, stop=stop, tp1=tp1, tp2=tp2,
                            quote=q(100.0, 100.02), minute_qv=mqv, candle_time=candle, decision_id=decision_id, risk_amount=20.0,
                            reason="test entry")


def test_market_entry_fills_at_ask_plus_slippage_and_fees(db):
    ex = PaperExecutor(FEES)
    acct = get_account(db, "paper", 10_000)
    pos, events = open_pos(db, ex, acct)
    assert pos.status == "open" and [e.kind for e in events] == ["filled", "opened"]
    fill = db.execute(select(Execution)).scalar_one()
    assert fill.price > 100.02  # never better than the ask
    assert fill.fee == pytest.approx(fill.qty * fill.price * 10 / 1e4)
    assert acct.cash == pytest.approx(10_000 - fill.qty * fill.price - fill.fee)
    orders = {o.purpose: o for o in db.execute(select(Order).where(Order.position_id == pos.id)).scalars()}
    assert set(orders) == {"entry", "stop", "tp1", "tp2"}
    assert orders["stop"].stop_price == 98.0 and orders["tp1"].qty == pytest.approx(5.0)


def test_duplicate_order_prevention(db):
    ex = PaperExecutor(FEES)
    acct = get_account(db, "paper", 10_000)
    p1, _ = open_pos(db, ex, acct, candle=42)
    p2, ev = open_pos(db, ex, acct, candle=42)
    assert p1 is not None and p2 is None and ev[0].kind == "duplicate"
    assert db.execute(select(Position)).scalars().all().__len__() == 1


def test_partial_fills_on_thin_volume_then_timeout(db):
    ex = PaperExecutor(FEES)
    acct = get_account(db, "paper", 10_000)
    # 1-min volume $2,000 → max 10% = $200 per tick, order is ~$1,000
    pos, ev = open_pos(db, ex, acct, mqv=2_000)
    assert pos.status == "pending" and ev[0].kind == "partial"
    assert pos.qty == pytest.approx(200 / 100.02, rel=0.01)
    ev = ex.on_tick(db, acct, pos, q(100.0, 100.02), 2_000)
    assert pos.qty == pytest.approx(400 / 100.02, rel=0.01)
    order = db.execute(select(Order).where(Order.position_id == pos.id, Order.purpose == "entry")).scalar_one()
    ev = ex.on_tick(db, acct, pos, q(100.0, 100.02), 2_000, now_ts=order.created_at.timestamp() + ENTRY_TIMEOUT_S + 1)
    assert pos.status == "open" and order.status == "partially_filled_cancelled"
    assert pos.initial_qty == pytest.approx(pos.qty)


def test_stop_loss_closes_with_correct_pnl_and_decision_outcome(db):
    ex = PaperExecutor(FEES)
    acct = get_account(db, "paper", 10_000)
    d = Decision(symbol="SOLUSDC", strategy="momentum", classification="BUY CANDIDATE", confidence=65, explanation="x")
    db.add(d)
    db.flush()
    pos, _ = open_pos(db, ex, acct, decision_id=d.id)
    entry_cost = pos.entry_price * pos.qty
    ev = ex.on_tick(db, acct, pos, q(97.9, 97.92), 10_000_000)
    assert pos.status == "closed" and ev[-1].kind == "closed"
    assert pos.exit_price < 97.9  # bid minus slippage
    assert pos.gross_pnl == pytest.approx(pos.exit_value - entry_cost)
    assert pos.net_pnl == pytest.approx(pos.gross_pnl - pos.fees_paid)
    assert acct.cash == pytest.approx(10_000 + pos.net_pnl)
    assert d.outcome == "loss" and d.outcome_r == pytest.approx(pos.net_pnl / 20.0, rel=1e-3)
    assert all(o.status in ("filled", "cancelled") for o in db.execute(select(Order)).scalars())


def test_take_profits_and_stop_adjustments(db):
    ex = PaperExecutor(FEES)
    acct = get_account(db, "paper", 10_000)
    pos, _ = open_pos(db, ex, acct)
    ex.on_tick(db, acct, pos, q(102.5), 1e7)  # +1R → breakeven
    assert pos.stop_price > pos.entry_price
    ev = ex.on_tick(db, acct, pos, q(104.1), 1e7)  # TP1
    assert pos.tp1_hit and pos.qty == pytest.approx(pos.initial_qty / 2)
    assert pos.stop_price == pytest.approx(pos.entry_price + (pos.entry_price - pos.initial_stop))
    ev = ex.on_tick(db, acct, pos, q(106.1), 1e7)
    assert pos.status == "closed" and pos.net_pnl > 0
    assert len(pos.stop_history) >= 3


def test_manual_close_and_portfolio_accounting(db):
    ex = PaperExecutor(FEES)
    acct = get_account(db, "paper", 10_000)
    pos, _ = open_pos(db, ex, acct)
    m = mark(db, acct, {"SOLUSDC": 101.0})
    assert m["equity"] == pytest.approx(acct.cash + pos.qty * 101.0)
    snapshot(db, acct, {"SOLUSDC": 101.0})
    ex.close_position(db, acct, pos, q(101.0), 1e7, "manual")
    assert pos.status == "closed" and pos.exit_reason == "manual"
    ov = overview(db, acct, {})
    assert ov["total_trades"] == 1 and ov["equity"] == pytest.approx(acct.cash)
    assert ov["realized_pnl"] == pytest.approx(pos.net_pnl, abs=1e-3)


def test_risk_context_consecutive_losses(db):
    ex = PaperExecutor(FEES)
    acct = get_account(db, "paper", 10_000)
    for i in range(3):
        pos, _ = open_pos(db, ex, acct, candle=100 + i)
        ex.on_tick(db, acct, pos, q(97.0), 1e7)
    rc = risk_context(db, acct, {})
    assert rc.consecutive_losses == 3 and rc.trades_today == 3 and rc.last_loss_at is not None
