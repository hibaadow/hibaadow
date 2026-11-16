import pytest

from atlas.execution import costs
from atlas.execution.rules import PosState, RuleParams, apply, manage
from atlas.trading_config import FeeModel


def test_fee_and_slippage_math():
    f = FeeModel(taker_fee_bps=10, maker_fee_bps=5, base_slippage_bps=2, impact_coefficient=0.1)
    assert costs.fee(f, 10_000) == pytest.approx(10.0)
    assert costs.fee(f, 10_000, taker=False) == pytest.approx(5.0)
    # 10k notional vs 100k/min volume = 10% participation → 1 bps impact + 2 base + 1 half-spread(2bps)
    assert costs.slippage_bps(f, 10_000, 100_000, 2.0) == pytest.approx(4.0)
    assert costs.apply_slippage(100, 10, "buy") == pytest.approx(100.1)
    assert costs.apply_slippage(100, 10, "sell") == pytest.approx(99.9)
    # unknown volume is treated conservatively
    assert costs.slippage_bps(f, 1_000, None, 0) > costs.slippage_bps(f, 1_000, 1e9, 0)


def st(**kw):
    base = dict(entry=100.0, qty=10.0, initial_qty=10.0, stop=98.0, initial_stop=98.0, tp1=104.0, tp2=106.0, opened_ts=0.0, high_water=100.0)
    base.update(kw)
    return PosState(**base)


def test_stop_evaluated_before_target_in_same_bar():
    acts = manage(st(), low=97.0, high=105.0, close=101.0, now_ts=60)
    assert [a.kind for a in acts] == ["stop"]
    assert acts[0].price == 98.0


def test_gap_through_stop_fills_at_open():
    acts = manage(st(), low=95.0, high=96.0, close=95.5, now_ts=60, open_=96.0)
    assert acts[0].kind == "stop" and acts[0].price == 96.0


def test_tp1_then_stop_to_plus_1r_then_tp2():
    s = st()
    acts = manage(s, low=101, high=104.5, close=104, now_ts=60)
    kinds = [a.kind for a in acts]
    assert kinds == ["tp1", "move_stop"]
    assert acts[0].fraction == 0.5
    for a in acts:
        apply(s, a)
    assert s.qty == pytest.approx(5.0) and s.stop == pytest.approx(102.0) and s.tp1_hit
    acts = manage(s, low=103, high=106.2, close=106, now_ts=120)
    assert [a.kind for a in acts] == ["tp2"]


def test_target_requires_trade_through():
    assert all(a.kind not in ('tp1', 'tp2') for a in manage(st(), low=101, high=104.0, close=103, now_ts=60))


def test_breakeven_after_1r():
    s = st(fee_per_unit=0.2)
    acts = manage(s, low=100.5, high=102.1, close=101.5, now_ts=60)
    assert acts and acts[0].kind == "move_stop" and acts[0].price == pytest.approx(100.2)
    apply(s, acts[0])
    assert s.breakeven_set and s.stop == pytest.approx(100.2)
    assert manage(s, low=100.5, high=102.5, close=101.5, now_ts=70) == []  # not moved twice


def test_time_stops():
    p = RuleParams(stale_after_s=3600, max_hold_s=7200)
    assert manage(st(), 99.5, 100.5, 100.2, 3601, p)[0].kind == "time_exit"
    s = st(high_water=101.5)  # made progress → no stale exit
    assert manage(s, 99.5, 100.5, 100.2, 3601, p) == []
    assert manage(s, 99.5, 100.5, 100.2, 7201, p)[0].kind == "time_exit"
