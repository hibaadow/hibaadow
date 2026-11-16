import numpy as np
import pytest

from atlas.backtest import Backtester, BTParams, resample, split_metrics, walk_forward
from atlas.trading_config import FeeModel, TradingConfig
from tests.conftest import make_series


def series(n=3000, seed=11, drift=0.0003):
    g = np.random.default_rng(seed)
    closes = 100 * np.exp(np.cumsum(g.normal(drift, 0.004, n)))
    return make_series(closes, vol=g.lognormal(7, 0.6, n))[0]


def test_backtest_runs_and_accounts_costs():
    s = series()
    r = Backtester(TradingConfig()).run(s, BTParams("SOLUSDC", "momentum", "5m"))
    m = r["metrics"]
    assert m["total_trades"] > 0
    for t in r["trades"]:
        assert t["fees"] > 0
        assert t["net_pnl"] == pytest.approx(t["gross_pnl"] - t["fees"], abs=1e-5)
        assert t["exit_time"] >= t["entry_time"]
    assert m["final_equity"] == pytest.approx(10_000 + sum(t["net_pnl"] for t in r["trades"]), rel=1e-6)
    for k in ("net_return_pct", "win_rate", "max_drawdown_pct", "sharpe", "sortino", "expectancy", "avg_holding_minutes"):
        assert k in m


def test_costs_reduce_performance():
    s = series()
    free = TradingConfig(fees=FeeModel(taker_fee_bps=0, maker_fee_bps=0, base_slippage_bps=0, impact_coefficient=0))
    a = Backtester(free).run(s, BTParams("SOLUSDC", "trend_following", "5m", spread_bps=0))["metrics"]
    b = Backtester(TradingConfig()).run(s, BTParams("SOLUSDC", "trend_following", "5m"))["metrics"]
    assert b["final_equity"] < a["final_equity"]


def test_no_lookahead_future_changes_do_not_alter_past_trades():
    s = series()
    p = BTParams("SOLUSDC", "breakout", "5m")
    full = Backtester(TradingConfig()).run(s, p)
    cut = 2000
    s2 = series()
    s2.c[cut:] *= 0.7
    s2.h[cut:] *= 0.7
    s2.l[cut:] *= 0.7
    s2.o[cut:] *= 0.7
    alt = Backtester(TradingConfig()).run(s2, p)
    t_cut = int(s.t[cut - 1])
    before = [t for t in full["trades"] if t["exit_time"] < t_cut]
    before2 = [t for t in alt["trades"] if t["exit_time"] < t_cut]
    assert before == before2


def test_entries_fill_at_next_bar_open():
    s = series()
    r = Backtester(TradingConfig()).run(s, BTParams("SOLUSDC", "momentum", "5m"))
    opens = dict(zip(s.t.tolist(), s.o.tolist()))
    for t in r["trades"][:20]:
        assert t["entry"] >= opens[t["entry_time"]]  # open + spread + slippage, never better


def test_resample_hides_incomplete_htf_bars():
    s = series(600)
    htf, close_t = resample(s, "1h")
    assert np.all(close_t == htf.t + 3_600_000)
    assert htf.h[0] == pytest.approx(s.h[:12].max()) or s.t[0] % 3_600_000 != 0


def test_out_of_sample_and_walk_forward():
    s = series(4000)
    p = BTParams("SOLUSDC", "vwap_reversion", "5m")
    bt = Backtester(TradingConfig())
    r = bt.run(s, p)
    ins, oos = split_metrics(r, s, p)
    assert ins["total_trades"] + oos["total_trades"] == r["metrics"]["total_trades"]
    wf = walk_forward(bt, s, p, folds=2)
    assert len(wf["folds"]) == 2
    for f in wf["folds"]:
        assert f["train"][1] < f["test"][0], "test window must be strictly after training window"
