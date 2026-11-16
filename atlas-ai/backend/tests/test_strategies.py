import numpy as np
import pytest

from atlas.backtest import resample
from atlas.strategies.base import StrategyContext
from atlas.strategies.library import STRATEGIES, build
from tests.conftest import make_series


def paths():
    r = np.random.default_rng(7)
    for seed in range(6):
        g = np.random.default_rng(seed)
        drift = [0.0004, -0.0002, 0.0, 0.0008, -0.0006, 0.0002][seed]
        closes = 100 * np.exp(np.cumsum(g.normal(drift, 0.004, 1500)))
        vol = r.lognormal(7, 0.6, 1500)
        yield make_series(closes, vol=vol)[0]


@pytest.mark.parametrize("name", list(STRATEGIES))
def test_strategy_signals_are_structured_and_safe(name):
    strat = build(name)
    longs = 0
    for s in paths():
        htf, htf_close = resample(s, "1h")
        for i in range(260, len(s), 3):
            end_t = int(s.t[i]) + 300_000
            j = int(np.searchsorted(htf_close, end_t, side="right"))
            ctx = StrategyContext(s.symbol, s.slice(i + 1, max(0, i + 1 - 500)), htf.slice(j, max(0, j - 300)))
            sig = strat.evaluate(ctx)
            assert sig.direction in ("long", "exit", "none")
            assert sig.strategy == name and sig.candle_time == int(s.t[i])
            assert sig.reasons, "every signal must explain itself"
            if sig.direction == "long":
                longs += 1
                assert sig.stop < sig.entry, "mandatory stop below entry"
                assert sig.targets and sig.targets[0] >= sig.entry + 2 * (sig.entry - sig.stop) - 1e-9
                assert 0 <= sig.strength <= 1
                assert sig.tradeable
    assert longs > 0, f"{name} never produced a long signal on synthetic data"


def test_insufficient_data_returns_none():
    s, _ = make_series(np.linspace(100, 110, 100))
    for name in STRATEGIES:
        sig = build(name).evaluate(StrategyContext("SOLUSDC", s))
        assert sig.direction == "none" and "need" in sig.reasons[0]


def test_momentum_rejects_overextended_rsi():
    closes = 100 * np.exp(np.cumsum(np.full(400, 0.004)))  # straight up → RSI ~100
    s, _ = make_series(closes, vol=np.full(400, 1000.0))
    sig = build("momentum").evaluate(StrategyContext("SOLUSDC", s))
    assert sig.direction == "none" and "overextended" in sig.reasons[0]


def test_strategy_cannot_see_future_bars():
    s = next(paths())
    strat = build("trend_following")
    ctx_a = StrategyContext(s.symbol, s.slice(700, 200))
    a = strat.evaluate(ctx_a).to_dict()
    # Mutating bars AFTER the slice must not change the signal
    s.c[700:] *= 1.5
    s.h[700:] *= 1.5
    b = strat.evaluate(StrategyContext(s.symbol, s.slice(700, 200))).to_dict()
    assert a == b
