import numpy as np
import pytest

from atlas.backtest import Backtester, BTParams, resample, split_metrics, walk_forward
from atlas.trading_config import CostModel, TradingConfig
from tests.conftest import make_series

MIDS = {"EURUSD": 1.10, "GBPUSD": 1.27, "USDJPY": 150.0}


def series(n=3000, seed=11, drift=0.00004, symbol="EURUSD", p0=1.10, vol=0.0006, bar_spread=0.00012):
    g = np.random.default_rng(seed)
    closes = p0 * np.exp(np.cumsum(g.normal(drift, vol, n)))
    return make_series(closes, symbol=symbol, vol=g.lognormal(4, 0.5, n), spread_frac=vol * 0.6, bar_spread=bar_spread)[0]


def test_runs_and_accounts_costs_both_sides():
    s = series()
    r = Backtester(TradingConfig()).run(s, BTParams("EURUSD", "trend_pullback", "5m", conversion_mids=MIDS))
    m = r["metrics"]
    assert m["total_trades"] > 0
    assert {t["side"] for t in r["trades"]} <= {"buy", "sell"}
    for t in r["trades"]:
        assert t["fees"] > 0 and t["lots"] >= 0.01
        assert t["net_pnl"] == pytest.approx(t["gross_pnl"] - t["fees"], abs=1e-3)
    assert m["final_equity"] == pytest.approx(10_000 + sum(t["net_pnl"] for t in r["trades"]), abs=0.05)
    for k in ("net_return_pct", "win_rate", "profit_factor", "max_drawdown_pct", "sharpe", "sortino", "expectancy", "avg_holding_minutes"):
        assert k in m


def test_costs_reduce_performance():
    s = series()
    free = TradingConfig(costs=CostModel(commission_per_lot_side_usd=0, slippage_multiplier=0))
    a = Backtester(free).run(s, BTParams("EURUSD", "breakout_retest", "5m", spread_pips=0.0, conversion_mids=MIDS))["metrics"]
    b = Backtester(TradingConfig()).run(s, BTParams("EURUSD", "breakout_retest", "5m", spread_pips=2.0, conversion_mids=MIDS))["metrics"]
    assert b["final_equity"] < a["final_equity"]


def test_no_lookahead():
    p = BTParams("EURUSD", "liquidity_sweep", "5m", conversion_mids=MIDS)
    full = Backtester(TradingConfig()).run(series(), p)
    s2 = series()
    cut = 2000
    for arr in (s2.o, s2.h, s2.l, s2.c):
        arr[cut:] *= 0.97
    alt = Backtester(TradingConfig()).run(s2, p)
    t_cut = int(s2.t[cut - 1])
    assert [t for t in full["trades"] if t["exit_time"] < t_cut] == [t for t in alt["trades"] if t["exit_time"] < t_cut]


def test_entries_at_next_open_plus_half_spread():
    s = series(bar_spread=0.0002)
    r = Backtester(TradingConfig()).run(s, BTParams("EURUSD", "trend_pullback", "5m", conversion_mids=MIDS))
    opens = dict(zip(s.t.tolist(), s.o.tolist()))
    for t in r["trades"][:20]:
        o = opens[t["entry_time"]]
        if t["side"] == "buy":
            assert t["entry"] >= o + 0.0001 - 1e-9
        else:
            assert t["entry"] <= o - 0.0001 + 1e-9


def test_gold_and_jpy_backtests_run():
    g = series(symbol="XAUUSD", p0=3800.0, vol=0.001, bar_spread=0.3)
    r = Backtester(TradingConfig()).run(g, BTParams("XAUUSD", "gold_session", "5m", conversion_mids=MIDS))
    assert r["metrics"]["total_trades"] >= 0
    j = series(symbol="USDJPY", p0=150.0, bar_spread=0.012)
    r = Backtester(TradingConfig()).run(j, BTParams("USDJPY", "trend_pullback", "5m", conversion_mids=MIDS))
    assert not r["metrics"]["cross_rate_approximated"]


def test_resample_htf_close_times():
    s = series(600)
    htf, close_t = resample(s, "1h")
    assert np.all(close_t == htf.t + 3_600_000)


def test_oos_and_walk_forward():
    s = series(4000)
    p = BTParams("EURUSD", "supply_demand", "5m", conversion_mids=MIDS)
    bt = Backtester(TradingConfig())
    r = bt.run(s, p)
    ins, oos = split_metrics(r, s, p)
    assert ins["total_trades"] + oos["total_trades"] == r["metrics"]["total_trades"]
    wf = walk_forward(bt, s, p, folds=2)
    assert len(wf["folds"]) == 2 and all(f["train"][1] < f["test"][0] for f in wf["folds"])
