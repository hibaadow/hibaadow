from atlas.marketdata.types import Candle
from atlas.marketdata.validation import validate_candles

STEP = 300_000


def bars(n, start=1_000 * STEP, price=100.0):
    return [Candle(start + i * STEP, price, price + 1, price - 1, price + 0.5, 10.0, 1000.0) for i in range(n)]


def now_after(cs, extra=STEP):
    return cs[-1].open_time + STEP + extra // 10


def test_clean_data_usable():
    cs = bars(100)
    out, r = validate_candles(cs, "5m", now_ms=now_after(cs), drop_open=False)
    assert r["usable"] and len(out) == 100 and r["missing_bars"] == 0


def test_duplicates_removed_and_invalid_rejected():
    cs = bars(50)
    cs.append(cs[10])  # duplicate
    cs.append(Candle(cs[-1].open_time + STEP, 100, 99, 101, 100, 1, 1))  # high < low → invalid
    cs.append(Candle(cs[-2].open_time + 2 * STEP, float("nan"), 1, 1, 1, 1, 1))
    out, r = validate_candles(cs, "5m", now_ms=now_after(cs), drop_open=False)
    assert r["duplicates"] == 1
    assert r["invalid"] == 2
    assert len(out) == 50


def test_gap_detection_marks_unusable():
    cs = bars(100)
    del cs[40:50]
    out, r = validate_candles(cs, "5m", now_ms=now_after(cs), drop_open=False)
    assert r["gaps"] == 1 and r["missing_bars"] == 10
    assert not r["usable"]


def test_stale_data_detected():
    cs = bars(100)
    out, r = validate_candles(cs, "5m", now_ms=cs[-1].open_time + 10 * STEP, drop_open=False)
    assert r["stale"] and not r["usable"]


def test_open_bar_dropped():
    cs = bars(100)
    out, r = validate_candles(cs, "5m", now_ms=cs[-1].open_time + 60_000)
    assert r["dropped_open_bar"] and len(out) == 99


def test_misaligned_and_extreme_bars_rejected():
    cs = bars(20)
    cs.append(Candle(cs[-1].open_time + STEP + 7, 100, 101, 99, 100, 1, 1))
    cs.append(Candle(cs[-2].open_time + 2 * STEP, 100, 300, 99, 100, 1, 1))  # 200% range
    out, r = validate_candles(cs, "5m", now_ms=now_after(cs), drop_open=False)
    assert r["misaligned"] == 1 and r["invalid"] == 1
