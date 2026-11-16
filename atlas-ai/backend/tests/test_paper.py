import pytest
from sqlalchemy import select

from atlas.execution.paper import PaperExecutor, unrealized_usd
from atlas.marketdata.types import Quote
from atlas.models import Decision, Execution, Order, Position
from atlas.portfolio import get_account, mark, overview, risk_context
from atlas.trading_config import CostModel

CM = CostModel(commission_per_lot_side_usd=3.5, gold_commission_per_lot_side_usd=3.5)
MIDS = {"EURUSD": 1.10, "GBPUSD": 1.27, "USDJPY": 150.0, "XAUUSD": 3800.0, "AUDUSD": 0.65, "NZDUSD": 0.6, "USDCAD": 1.37, "USDCHF": 0.88}


def q(sym, bid, ask):
    return Quote(sym, "test", bid, ask, (bid + ask) / 2)


def open_pos(db, ex, acct, sym="EURUSD", side="buy", lots=0.5, bid=1.09990, ask=1.10000, stop=1.09800, tp1=1.10400, tp2=1.10600, candle=1, decision_id=None):
    return ex.open_position(db, acct, symbol=sym, side=side, strategy="trend_pullback", lots=lots, stop=stop, tp1=tp1, tp2=tp2, quote=q(sym, bid, ask),
                            mids=MIDS, candle_time=candle, decision_id=decision_id, risk_amount=100.0, reason="test")


def test_buy_fills_at_ask_plus_slippage_and_commission(db):
    ex = PaperExecutor(CM)
    acct = get_account(db, "paper", 10_000)
    pos, ev = open_pos(db, ex, acct)
    assert pos.status == "open" and pos.side == "buy"
    assert pos.entry_price == pytest.approx(1.10002)  # ask + 0.2 pip
    assert acct.cash == pytest.approx(10_000 - 0.5 * 3.5)  # margin account: only commission leaves cash
    orders = {o.purpose: o for o in db.execute(select(Order).where(Order.position_id == pos.id)).scalars()}
    assert set(orders) == {"entry", "stop", "tp1", "tp2"} and orders["stop"].side == "sell" and orders["tp1"].qty == pytest.approx(0.25)


def test_sell_fills_at_bid_and_unrealized(db):
    ex = PaperExecutor(CM)
    acct = get_account(db, "paper", 10_000)
    pos, _ = open_pos(db, ex, acct, side="sell", stop=1.10200, tp1=1.09600, tp2=1.09400)
    assert pos.entry_price == pytest.approx(1.09988)
    # short gains when the ASK falls: closes at ask 1.09888 → 10 pips × $10 × 0.5 lots = $50
    assert unrealized_usd(pos, q("EURUSD", 1.09878, 1.09888), MIDS) == pytest.approx(50.0)


def test_duplicate_prevention(db):
    ex = PaperExecutor(CM)
    acct = get_account(db, "paper", 10_000)
    a, _ = open_pos(db, ex, acct, candle=7)
    b, ev = open_pos(db, ex, acct, candle=7)
    assert a is not None and b is None and ev[0].kind == "duplicate"


def test_stop_loss_pnl_in_usd_and_decision_outcome(db):
    ex = PaperExecutor(CM)
    acct = get_account(db, "paper", 10_000)
    d = Decision(symbol="EURUSD", strategy="trend_pullback", classification="BUY CANDIDATE", confidence=66, explanation="x")
    db.add(d)
    db.flush()
    pos, _ = open_pos(db, ex, acct, decision_id=d.id)
    ev = ex.on_tick(db, acct, pos, q("EURUSD", 1.09800, 1.09810), MIDS)
    assert pos.status == "closed" and ev[-1].kind == "closed"
    # exit at stop 1.09800 − 0.4 pip stop slippage = 1.09796; loss = 20.6 pips × $10 × 0.5
    assert pos.gross_pnl == pytest.approx(-(1.10002 - 1.09796) * 50_000, abs=0.01)
    assert pos.net_pnl == pytest.approx(pos.gross_pnl - 3.5, abs=1e-6)
    assert acct.cash == pytest.approx(10_000 + pos.net_pnl)
    assert d.outcome == "loss"


def test_usdjpy_pnl_converted_to_usd(db):
    ex = PaperExecutor(CM)
    acct = get_account(db, "paper", 10_000)
    pos, _ = open_pos(db, ex, acct, sym="USDJPY", lots=1.0, bid=149.990, ask=150.000, stop=149.700, tp1=150.400, tp2=150.700)
    mids = {**MIDS, "USDJPY": 150.5}
    ex.on_tick(db, acct, pos, q("USDJPY", 150.420, 150.430), mids)  # through TP1 → 0.5 lots closed at 150.400
    assert pos.tp1_hit and pos.qty == pytest.approx(0.5)
    expected = (150.400 - 150.003) * 0.5 * 100_000 / 150.5
    assert pos.gross_pnl == pytest.approx(expected, rel=1e-6)


def test_gold_short_tp_and_stop_moves(db):
    ex = PaperExecutor(CM)
    acct = get_account(db, "paper", 10_000)
    pos, _ = open_pos(db, ex, acct, sym="XAUUSD", side="sell", lots=0.1, bid=3800.00, ask=3800.35, stop=3810.00, tp1=3780.00, tp2=3770.00)
    ex.on_tick(db, acct, pos, q("XAUUSD", 3789.0, 3789.35), MIDS)  # +1R (entry 3799.85, R 10.15) → breakeven
    assert pos.stop_price < 3810.0
    ex.on_tick(db, acct, pos, q("XAUUSD", 3779.0, 3779.35), MIDS)  # TP1
    assert pos.tp1_hit and pos.qty == pytest.approx(0.05)
    ex.on_tick(db, acct, pos, q("XAUUSD", 3768.5, 3768.85), MIDS)  # TP2
    assert pos.status == "closed" and pos.net_pnl > 0


def test_portfolio_mark_and_risk_context(db):
    ex = PaperExecutor(CM)
    acct = get_account(db, "paper", 10_000)
    pos, _ = open_pos(db, ex, acct)
    quotes = {"EURUSD": q("EURUSD", 1.10102, 1.10112)}
    m = mark(db, acct, quotes)
    assert m["unrealized"] == pytest.approx((1.10102 - 1.10002) * 50_000)
    assert m["margin_used"] == pytest.approx(0.5 * 100_000 * 1.10107 / 30, rel=1e-4)
    rc = risk_context(db, acct, quotes)
    assert rc.open_positions[0].side == "buy" and rc.currency_risk()["USD"] == pytest.approx(-100.0)
    ex.close_position(db, acct, pos, quotes["EURUSD"], MIDS, "manual")
    ov = overview(db, acct, quotes)
    assert ov["total_trades"] == 1 and ov["equity"] == pytest.approx(acct.cash)
