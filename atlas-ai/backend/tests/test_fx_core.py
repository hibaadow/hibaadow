"""Instruments, pip values, margin, sessions, calendar and currency strength."""
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from atlas import instruments as I
from atlas.econ import blackout, currency_strength, parse_calendar, upcoming
from atlas.sessions import active_sessions, is_market_open, near_rollover, session_info

MIDS = {"EURUSD": 1.10, "GBPUSD": 1.27, "USDJPY": 150.0, "AUDUSD": 0.65, "NZDUSD": 0.60, "USDCAD": 1.37, "USDCHF": 0.88, "XAUUSD": 3800.0}


def test_universe_is_gold_and_forex_only():
    assert set(I.INSTRUMENTS) == {"XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "GBPJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURGBP", "EURJPY"}
    for bad in ("BTCUSD", "ETHUSD", "SOLUSDC", "SPX500", "XAGUSD", "USOIL"):
        assert not I.is_supported(bad)
        with pytest.raises(I.UnsupportedInstrument):
            I.get(bad)
    assert I.normalize("eur/usd") == "EURUSD" and I.get("XAU_USD").symbol == "XAUUSD"


@pytest.mark.parametrize("sym,expected", [
    ("EURUSD", 10.0),                 # USD-quoted: $10 per pip per lot
    ("XAUUSD", 10.0),                 # 100 oz × $0.10
    ("USDJPY", 1000 / 150.0),         # ¥1000 → USD
    ("USDCAD", 10 / 1.37),
    ("USDCHF", 10 / 0.88),
    ("EURGBP", 10 * 1.27),            # £10 → USD via GBPUSD
    ("GBPJPY", 1000 / 150.0),         # ¥1000 → USD via USDJPY
    ("EURJPY", 1000 / 150.0),
])
def test_pip_values_in_usd(sym, expected):
    assert I.pip_value_usd(I.get(sym), MIDS) == pytest.approx(expected)


def test_pip_value_unknown_without_conversion_rate():
    assert I.pip_value_usd(I.get("EURGBP"), {"EURGBP": 0.86}) is None


def test_notional_and_margin():
    eu = I.get("EURUSD")
    assert I.notional_usd(eu, 1.0, 1.10, MIDS) == pytest.approx(110_000)
    assert I.margin_usd(eu, 1.0, 1.10, MIDS) == pytest.approx(110_000 / 30)
    xau = I.get("XAUUSD")
    assert I.notional_usd(xau, 0.5, 3800, MIDS) == pytest.approx(190_000)
    assert I.margin_usd(xau, 0.5, 3800, MIDS) == pytest.approx(190_000 * 0.05)


def test_lots_floor_never_rounds_risk_up():
    eu = I.get("EURUSD")
    assert I.floor_lots(eu, 0.379999) == 0.37
    assert I.floor_lots(eu, 0.009) == 0.0
    assert I.floor_lots(eu, 999) == eu.max_lot


def test_market_hours_and_sessions_dst():
    sat = datetime(2026, 11, 21, 12, tzinfo=timezone.utc)
    assert not is_market_open(sat)
    sun_before = datetime(2026, 11, 22, 21, 30, tzinfo=timezone.utc)  # 16:30 NY (EST)
    sun_after = datetime(2026, 11, 22, 22, 30, tzinfo=timezone.utc)   # 17:30 NY
    assert not is_market_open(sun_before) and is_market_open(sun_after)
    gold_break = datetime(2026, 11, 18, 22, 30, tzinfo=timezone.utc)   # 17:30 NY Wednesday
    assert is_market_open(gold_break, "forex") and not is_market_open(gold_break, "gold")
    assert near_rollover(datetime(2026, 11, 18, 22, 3, tzinfo=timezone.utc))
    # London opens 08:00 London: 08:00 UTC in winter, 07:00 UTC in summer (BST)
    assert "London" in active_sessions(datetime(2026, 11, 17, 8, 5, tzinfo=timezone.utc))
    assert "London" not in active_sessions(datetime(2026, 11, 17, 7, 30, tzinfo=timezone.utc))
    assert "London" in active_sessions(datetime(2026, 7, 14, 7, 30, tzinfo=timezone.utc))
    s = session_info(datetime(2026, 11, 17, 14, tzinfo=timezone.utc), ("EUR", "USD"), "forex")
    assert s.overlap_london_ny and s.quality == 1.0


CAL = [
    {"title": "Non-Farm Employment Change", "country": "USD", "date": "2026-11-17T08:30:00-05:00", "impact": "High", "forecast": "150K", "previous": "120K"},
    {"title": "Federal Funds Rate", "country": "USD", "date": "2026-11-18T14:00:00-05:00", "impact": "High"},
    {"title": "German ZEW", "country": "EUR", "date": "2026-11-17T05:00:00-05:00", "impact": "Medium"},
    {"title": "<script>x</script>", "country": "BTC", "date": "2026-11-17T05:00:00-05:00", "impact": "High"},
    {"title": "bad", "country": "USD", "date": "not-a-date", "impact": "High"},
]


def test_calendar_parsing_and_central_banks():
    ev = parse_calendar(CAL)
    assert [e.title for e in ev] == ["German ZEW", "Non-Farm Employment Change", "Federal Funds Rate"]
    nfp = ev[1]
    assert nfp.time == datetime(2026, 11, 17, 13, 30, tzinfo=timezone.utc)
    assert ev[2].central_bank and not nfp.central_bank


def test_news_blackout_by_instrument():
    ev = parse_calendar(CAL)
    t = datetime(2026, 11, 17, 13, 10, tzinfo=timezone.utc)  # 20 min before NFP
    assert blackout(ev, "EURUSD", t, 30, 30).title.startswith("Non-Farm")
    assert blackout(ev, "XAUUSD", t, 30, 30) is not None  # gold reacts to USD news
    assert blackout(ev, "EURGBP", t, 30, 30) is None      # no USD exposure
    assert blackout(ev, "EURUSD", t - timedelta(hours=2), 30, 30) is None
    fomc = datetime(2026, 11, 18, 18, 0, tzinfo=timezone.utc) + timedelta(minutes=50)
    assert blackout(ev, "USDJPY", fomc, 30, 30, cb_extra_min=30) is not None  # central-bank window is wider
    assert len(upcoming(ev, "EURUSD", t, 24)) == 1


def test_currency_strength():
    closes = {"EURUSD": np.array([1.0] * 30 + [1.01]), "GBPUSD": np.array([1.0] * 30 + [1.01]), "USDJPY": np.array([150.0] * 30 + [148.5])}
    s = currency_strength(closes, 24)
    assert s["USD"] < 0 < s["EUR"] and s["JPY"] > 0
