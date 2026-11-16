import numpy as np
import pytest

from atlas import indicators as ind


def test_sma_and_ema_against_naive():
    x = np.arange(1, 51, dtype=float)
    assert ind.sma(x, 5)[4] == pytest.approx(3.0)
    assert np.isnan(ind.sma(x, 5)[3])
    e = ind.ema(x, 10)
    k = 2 / 11
    ref = [x[:10].mean()]
    for v in x[10:]:
        ref.append(v * k + ref[-1] * (1 - k))
    assert np.allclose(e[9:], ref)


def test_rsi_bounds_and_extremes():
    up = np.linspace(1, 100, 60)
    assert ind.rsi(up, 14)[-1] == pytest.approx(100.0)
    down = np.linspace(100, 1, 60)
    assert ind.rsi(down, 14)[-1] == pytest.approx(0.0, abs=1e-9)
    flat = np.full(60, 5.0)
    assert ind.rsi(flat, 14)[-1] == pytest.approx(50.0)


def test_rsi_wilder_reference():
    # Wilder example data: avg gain 3.34/14, avg loss 1.40/14 → RS 2.386 → RSI 70.46 (hand computed)
    closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28]
    assert ind.rsi(closes, 14)[14] == pytest.approx(70.464, abs=0.01)


def test_macd_identity():
    x = np.cumsum(np.random.default_rng(0).normal(0, 1, 300)) + 100
    line, sig, hist = ind.macd(x)
    assert np.allclose(line, ind.ema(x, 12) - ind.ema(x, 26), equal_nan=True)
    assert np.allclose(hist[~np.isnan(hist)], (line - sig)[~np.isnan(hist)])


def test_atr_constant_range():
    n = 50
    h = np.full(n, 11.0)
    l = np.full(n, 9.0)
    c = np.full(n, 10.0)
    assert ind.atr(h, l, c, 14)[-1] == pytest.approx(2.0)


def test_vwap_resets_each_session():
    day = 86_400_000
    t = np.array([0, 300_000, day, day + 300_000])
    h = l = c = np.array([10.0, 20.0, 100.0, 200.0])
    v = np.array([1.0, 1.0, 1.0, 3.0])
    vw, _ = ind.vwap(h, l, c, v, t)
    assert vw[1] == pytest.approx(15.0)
    assert vw[2] == pytest.approx(100.0)  # reset at new UTC day
    assert vw[3] == pytest.approx((100 + 600) / 4)


def test_relative_volume_excludes_current_bar():
    v = np.array([10.0] * 20 + [30.0])
    assert ind.relative_volume(v, 20)[-1] == pytest.approx(3.0)


@pytest.mark.parametrize("fn", [lambda x: ind.ema(x, 21), lambda x: ind.rsi(x, 14), lambda x: ind.macd(x)[2],
                                lambda x: ind.roc(x, 3), lambda x: ind.rolling_max(x, 10), lambda x: ind.sma(x, 20)])
def test_indicators_are_causal(fn):
    """Appending future data must not change past indicator values (no look-ahead)."""
    x = np.cumsum(np.random.default_rng(3).normal(0, 1, 400)) + 200
    a = fn(x[:300])
    b = fn(x)[:300]
    assert np.allclose(a, b, equal_nan=True)


def test_support_resistance_levels():
    base = [10, 11, 12, 11, 10, 11, 12, 11, 10, 11, 12, 11, 10] * 4
    h = np.array(base, dtype=float) + 0.1
    l = np.array(base, dtype=float) - 0.1
    c = np.array(base, dtype=float)
    sr = ind.support_resistance(h, l, c)
    assert sr["resistance"] is None or sr["resistance"]["price"] > c[-1]
    assert sr["support"] is None or sr["support"]["price"] < c[-1]
    assert sr["levels"]
