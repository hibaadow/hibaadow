import numpy as np
import pytest

from atlas.backtest import resample
from atlas.strategies.base import MIN_CONFLUENCE, StrategyContext
from atlas.strategies.library import STRATEGIES, build
from tests.conftest import make_series


def paths(symbol="EURUSD", p0=1.10, vol=0.0006, n=1800):
    for seed in range(8):
        g = np.random.default_rng(seed)
        drift = [0.00006, -0.00006, 0.0, 0.00012, -0.00012, 0.00003, -0.00003, 0.0][seed]
        closes = p0 * np.exp(np.cumsum(g.normal(drift, vol, n)))
        yield make_series(closes, symbol=symbol, vol=g.lognormal(4, 0.5, n), spread_frac=vol * 0.6)[0]


def run_strategy(name, symbol, p0, vol):
    strat = build(name)
    sigs = []
    for s in paths(symbol, p0, vol):
        h1, h1c = resample(s, "1h")
        h4, h4c = resample(s, "4h")
        for i in range(300, len(s), 2):
            close_t = int(s.t[i]) + 300_000
            j1, j4 = int(np.searchsorted(h1c, close_t, "right")), int(np.searchsorted(h4c, close_t, "right"))
            ctx = StrategyContext(symbol, s.slice(i + 1, max(0, i + 1 - 500)), h1.slice(j1, max(0, j1 - 300)), h4.slice(j4, max(0, j4 - 200)), close_t,
                                  usd_strength=-0.2 if i % 2 else 0.2)
            sigs.append(strat.evaluate(ctx))
    return sigs


@pytest.mark.parametrize("name,symbol,p0,vol", [("trend_pullback", "EURUSD", 1.10, 0.0006), ("breakout_retest", "GBPUSD", 1.27, 0.0006),
                                                ("liquidity_sweep", "USDJPY", 150.0, 0.0006), ("supply_demand", "EURUSD", 1.10, 0.0008),
                                                ("gold_session", "XAUUSD", 3800.0, 0.0010)])
def test_signals_structured_confluent_and_two_sided(name, symbol, p0, vol):
    sigs = run_strategy(name, symbol, p0, vol)
    trades = [s for s in sigs if s.direction in ("buy", "sell")]
    assert trades, f"{name} produced no trade signals on synthetic data"
    for s in sigs:
        assert s.direction in ("buy", "sell", "exit", "none") and s.reasons
    for s in trades:
        sg = 1 if s.direction == "buy" else -1
        assert sg * (s.entry - s.stop) > 0, "stop must be on the protective side"
        assert sg * (s.targets[0] - s.entry) >= 2 * sg * (s.entry - s.stop) - 1e-6 * s.entry
        assert len(s.categories) >= MIN_CONFLUENCE, "never a single-indicator trade"
        assert s.invalidation, "every proposal states its invalidation"
    if name != "gold_session":
        assert {s.direction for s in trades} == {"buy", "sell"}, "strategies must trade both directions"


def test_gold_strategy_is_gold_only():
    s, _ = make_series(np.linspace(1.1, 1.11, 400))
    sig = build("gold_session").evaluate(StrategyContext("EURUSD", s))
    assert sig.direction == "none" and not build("gold_session").applies_to("EURUSD")


def test_insufficient_data():
    s, _ = make_series(np.linspace(1.1, 1.11, 60))
    for n in STRATEGIES:
        sig = build(n).evaluate(StrategyContext("XAUUSD" if n == "gold_session" else "EURUSD", s))
        assert sig.direction == "none"


def test_no_lookahead():
    s = next(paths())
    strat = build("trend_pullback")
    a = strat.evaluate(StrategyContext(s.symbol, s.slice(900, 400))).to_dict()
    s.c[900:] *= 1.05
    s.h[900:] *= 1.05
    assert strat.evaluate(StrategyContext(s.symbol, s.slice(900, 400))).to_dict() == a
