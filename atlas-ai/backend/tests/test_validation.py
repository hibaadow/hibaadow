from atlas.marketdata.types import Candle
from atlas.marketdata.validation import validate_candles
from tests.conftest import T0

STEP = 300_000


def bars(n, start=T0, price=1.10):
    return [Candle(start + i * STEP, price, price * 1.0005, price * 0.9995, price * 1.0002, 10.0) for i in range(n)]


def now_after(cs):
    return cs[-1].open_time + STEP + 30_000


def test_clean_data_usable():
    cs = bars(100)
    out, r = validate_candles(cs, "5m", now_ms=now_after(cs), drop_open=False)
    assert r["usable"] and len(out) == 100 and r["missing_bars"] == 0


def test_duplicates_and_invalid_rejected():
    cs = bars(50)
    cs.append(cs[10])
    cs.append(Candle(cs[-1].open_time + STEP, 1.1, 1.09, 1.11, 1.1, 1))  # high < low
    cs.append(Candle(cs[-2].open_time + 2 * STEP, float("nan"), 1, 1, 1, 1))
    cs.append(Candle(cs[-3].open_time + 3 * STEP, 1.1, 1.3, 1.09, 1.1, 1))  # 19% FX bar = corrupt
    out, r = validate_candles(cs, "5m", now_ms=now_after(cs), drop_open=False)
    assert r["duplicates"] == 1 and r["invalid"] == 3 and len(out) == 50


def test_gap_while_market_open_is_detected():
    cs = bars(100)
    del cs[40:50]
    out, r = validate_candles(cs, "5m", now_ms=now_after(cs), drop_open=False)
    assert r["gaps"] == 1 and r["missing_bars"] == 10 and not r["usable"]


def test_weekend_closure_is_not_a_gap():
    # Friday 2026-11-20 21:00 UTC (16:00 NY) → Sunday 22:00 UTC (17:00 NY) reopen
    fri = 1_795_208_400_000  # Fri 2026-11-20 21:00:00 UTC
    pre = [Candle(fri + i * STEP, 1.1, 1.1005, 1.0995, 1.1, 1) for i in range(12)]  # until 22:00 UTC = 17:00 NY close
    sun_open = fri + 2 * 86_400_000 + 3_600_000  # Sun 22:00 UTC
    post = [Candle(sun_open + i * STEP, 1.1, 1.1005, 1.0995, 1.1, 1) for i in range(12)]
    out, r = validate_candles(pre + post, "5m", now_ms=post[-1].open_time + STEP + 1000, drop_open=False)
    assert r["missing_bars"] == 0 and r["usable"], r


def test_stale_detected_only_when_market_open():
    cs = bars(100)
    out, r = validate_candles(cs, "5m", now_ms=cs[-1].open_time + 10 * STEP, drop_open=False)
    assert r["stale"] and not r["usable"]
    fri_close = 1_795_208_400_000 + 3_600_000 - STEP  # last bar before Friday close
    cs2 = [Candle(fri_close - i * STEP, 1.1, 1.1005, 1.0995, 1.1, 1) for i in range(50)][::-1]
    out, r = validate_candles(cs2, "5m", now_ms=fri_close + 86_400_000, drop_open=False)  # Saturday
    assert not r["stale"]


def test_open_bar_dropped():
    cs = bars(100)
    out, r = validate_candles(cs, "5m", now_ms=cs[-1].open_time + 60_000)
    assert r["dropped_open_bar"] and len(out) == 99
