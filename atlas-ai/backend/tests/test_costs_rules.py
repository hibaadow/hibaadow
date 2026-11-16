import pytest

from atlas.execution import costs
from atlas.execution.rules import PosState, RuleParams, apply, manage
from atlas.instruments import get
from atlas.trading_config import CostModel

MIDS = {"EURUSD": 1.10, "USDJPY": 150.0, "GBPUSD": 1.27, "XAUUSD": 3800.0}


def test_cost_estimate_usd():
    eu = get("EURUSD")
    ce = costs.estimate(eu, 1.0, 0.00012, MIDS, CostModel(commission_per_lot_side_usd=3.5))
    assert ce.spread_pips == pytest.approx(1.2)
    assert ce.spread_usd == pytest.approx(12.0)
    assert ce.commission_usd == pytest.approx(7.0)
    assert ce.slippage_usd == pytest.approx(2 * 0.2 * 10)
    xau = costs.estimate(get("XAUUSD"), 0.1, 0.30, MIDS, CostModel())
    assert xau.spread_pips == pytest.approx(3.0) and xau.spread_usd == pytest.approx(3.0)


def test_slippage_direction_and_news():
    eu = get("EURUSD")
    assert costs.apply_slippage(1.1, 2, eu, "buy") == pytest.approx(1.1002)
    assert costs.apply_slippage(1.1, 2, eu, "sell") == pytest.approx(1.0998)
    cm = CostModel()
    assert costs.slippage_pips(eu, cm, news=True) == pytest.approx(3 * costs.slippage_pips(eu, cm))
    assert costs.slippage_pips(eu, cm, stop=True) == pytest.approx(2 * costs.slippage_pips(eu, cm))


def st(side="buy", **kw):
    if side == "buy":
        base = dict(entry=1.1000, qty=1.0, initial_qty=1.0, stop=1.0980, initial_stop=1.0980, tp1=1.1040, tp2=1.1060, opened_ts=0.0, side="buy")
    else:
        base = dict(entry=1.1000, qty=1.0, initial_qty=1.0, stop=1.1020, initial_stop=1.1020, tp1=1.0960, tp2=1.0940, opened_ts=0.0, side="sell")
    base.update(kw)
    return PosState(**base)


def test_long_stop_first_and_gap():
    acts = manage(st(), 1.0975, 1.1050, 1.1, 60)
    assert [a.kind for a in acts] == ["stop"] and acts[0].price == 1.0980
    acts = manage(st(), 1.0960, 1.0970, 1.0965, 60, open_=1.0970)
    assert acts[0].price == 1.0970  # gapped through → worse fill


def test_short_mirror_rules():
    s = st("sell")
    acts = manage(s, 1.0990, 1.1025, 1.1, 60)  # ask went above stop
    assert [a.kind for a in acts] == ["stop"]
    s = st("sell")
    acts = manage(s, 1.0955, 1.0990, 1.0958, 60)
    assert [a.kind for a in acts] == ["tp1", "move_stop"]
    for a in acts:
        apply(s, a)
    assert s.qty == 0.5 and s.stop == pytest.approx(1.0980)  # +1R for a short = below entry
    assert [a.kind for a in manage(s, 1.0935, 1.0950, 1.094, 120)] == ["tp2"]


def test_breakeven_long_and_short():
    s = st(cost_per_unit=0.00005)
    acts = manage(s, 1.1005, 1.1021, 1.101, 60)
    assert acts[0].kind == "move_stop" and acts[0].price == pytest.approx(1.10005)
    s = st("sell", cost_per_unit=0.00005)
    acts = manage(s, 1.0979, 1.0995, 1.099, 60)
    assert acts[0].kind == "move_stop" and acts[0].price == pytest.approx(1.09995)


def test_targets_need_trade_through():
    s = st(through=0.00001)
    assert all(a.kind not in ("tp1", "tp2") for a in manage(s, 1.1, 1.1040, 1.103, 60))
    assert manage(st(through=0.00001), 1.1, 1.10402, 1.103, 60)[0].kind == "tp1"


def test_time_stops():
    p = RuleParams(stale_after_s=3600, max_hold_s=7200)
    assert manage(st(), 1.0995, 1.1005, 1.1, 3601, p)[0].kind == "time_exit"
    s = st(best=1.1015)
    assert manage(s, 1.0995, 1.1005, 1.1, 3601, p) == []
    assert manage(s, 1.0995, 1.1005, 1.1, 7201, p)[0].kind == "time_exit"
