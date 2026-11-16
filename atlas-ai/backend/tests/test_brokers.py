"""HTTP resilience + OANDA / MT5 / public-feed adapters against mocked transports (no credentials needed)."""
import asyncio
import json
import time

import httpx
import pytest

from atlas.brokers.base import BrokerError
from atlas.brokers.public import BarBuilder, pick_quote
from atlas.config import get_settings
from atlas.marketdata.http import ProviderClient, ProviderError
from atlas.marketdata.types import Quote


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def mock(client: ProviderClient, handler):
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), headers=client._headers)
    return client


# ---------------------------------------------------------------- http
def test_http_retries_and_rate_limits():
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        return httpx.Response(503, json={}) if calls["n"] < 3 else httpx.Response(200, json={"ok": True})

    assert run(mock(ProviderClient("t", "https://x", 1000, 1000), h).get("/a")) == {"ok": True}
    c = mock(ProviderClient("t", "https://x", 1000, 1000, max_retries=1), lambda r: httpx.Response(429, headers={"Retry-After": "0.01"}, json={}))
    with pytest.raises(ProviderError):
        run(c.get("/a"))
    with pytest.raises(ProviderError):
        run(mock(ProviderClient("t", "https://x", 1000, 1000), lambda r: httpx.Response(200, text="<html>", headers={"content-type": "text/html"})).get("/a"))


def test_auth_errors_do_not_leak_bodies():
    c = mock(ProviderClient("t", "https://x", 1000, 1000), lambda r: httpx.Response(401, json={"secret": "token-echo"}))
    with pytest.raises(ProviderError) as e:
        run(c.get("/a"))
    assert "token-echo" not in str(e.value)


# ---------------------------------------------------------------- public feed
SQ = [{"topo": {"platform": "A"}, "spreadProfilePrices": [{"spreadProfile": "elite", "bid": 3800.0, "ask": 3800.2},
                                                          {"spreadProfile": "prime", "bid": 3799.9, "ask": 3800.3},
                                                          {"spreadProfile": "standard", "bid": 3799.8, "ask": 3800.4}], "ts": int(time.time() * 1000)}]


def test_public_quote_uses_median_spread_profile():
    q = pick_quote("XAUUSD", SQ)
    assert (q.bid, q.ask) == (3799.9, 3800.3)
    assert pick_quote("XAUUSD", [{"spreadProfilePrices": [{"bid": "x"}]}]) is None
    assert pick_quote("XAUUSD", [{"spreadProfilePrices": [{"bid": 2, "ask": 1}]}]) is None  # crossed book rejected


def test_bar_builder_builds_minute_bars():
    b = BarBuilder()
    t0 = 1_794_902_400.0
    for i, (bid, ask) in enumerate([(1.1, 1.1001), (1.1004, 1.1005), (1.0998, 1.0999), (1.1002, 1.1003)]):
        q = Quote("EURUSD", "p", bid, ask, (bid + ask) / 2)
        q.ts = t0 + i * 15
        b.add(q)
    nxt = Quote("EURUSD", "p", 1.1, 1.1001, 1.10005)
    nxt.ts = t0 + 61
    b.add(nxt)
    (bar,) = b.bars["EURUSD"]
    assert bar.open == pytest.approx(1.10005) and bar.high == pytest.approx(1.10045) and bar.low == pytest.approx(1.09985)
    assert bar.close == pytest.approx(1.10025) and bar.volume == 4 and bar.spread == pytest.approx(0.0001)
    assert b.completed[0][0] == "EURUSD"


# ---------------------------------------------------------------- OANDA
@pytest.fixture
def oanda(monkeypatch):
    monkeypatch.setenv("ATLAS_OANDA_TOKEN", "test-token")
    monkeypatch.setenv("ATLAS_OANDA_ACCOUNT_ID", "101-001-0000000-001")
    get_settings.cache_clear()
    from atlas.brokers.oanda import OandaClient
    c = OandaClient()
    yield c
    get_settings.cache_clear()


def test_oanda_candles_pricing_and_order_payload(oanda):
    seen = {}

    def h(req: httpx.Request):
        assert req.headers["Authorization"] == "Bearer test-token"
        assert req.url.host == "api-fxpractice.oanda.com"  # practice (demo) by default
        if "/candles" in req.url.path:
            return httpx.Response(200, json={"candles": [
                {"time": "2026-11-17T10:00:00.000000000Z", "complete": True, "volume": 120,
                 "bid": {"o": "1.10000", "h": "1.10100", "l": "1.09900", "c": "1.10050"}, "ask": {"o": "1.10010", "h": "1.10110", "l": "1.09910", "c": "1.10060"}},
                {"time": "2026-11-17T10:05:00.000000000Z", "complete": False, "volume": 3,
                 "bid": {"o": "1.1", "h": "1.1", "l": "1.1", "c": "1.1"}, "ask": {"o": "1.1", "h": "1.1", "l": "1.1", "c": "1.1"}}]})
        if req.url.path.endswith("/pricing"):
            return httpx.Response(200, json={"prices": [{"instrument": "XAU_USD", "time": "2026-11-17T10:00:01.000000000Z", "tradeable": True,
                                                         "bids": [{"price": "3800.10"}], "asks": [{"price": "3800.45"}]}]})
        if req.url.path.endswith("/orders") and req.method == "POST":
            seen["order"] = json.loads(req.content)["order"]
            return httpx.Response(201, json={"orderFillTransaction": {"id": "55", "price": "1.10012", "units": "23000", "commission": "1.61",
                                                                      "tradeOpened": {"tradeID": "56"}}})
        return httpx.Response(404, json={})

    mock(oanda.http, h)
    cs = run(oanda.candles("EURUSD", "5m", 2))
    assert len(cs) == 1 and cs[0].open == pytest.approx(1.10005) and cs[0].spread == pytest.approx(0.0001)
    qs = run(oanda.quotes(["XAUUSD"]))
    assert qs["XAUUSD"].ask == 3800.45
    fill = run(oanda.market_order("EURUSD", "buy", 0.23, 1.09800, 1.10600, "atlas-demo-EURUSD-x-1", 1.10020))
    o = seen["order"]
    assert o["units"] == "23000" and o["stopLossOnFill"]["price"] == "1.09800" and o["takeProfitOnFill"]["price"] == "1.10600"
    assert o["clientExtensions"]["id"] == "atlas-demo-EURUSD-x-1" and o["priceBound"] == "1.10020"
    assert fill.broker_id == "56" and fill.lots == pytest.approx(0.23) and fill.commission == pytest.approx(-1.61)


def test_oanda_rejection_is_reported(oanda):
    mock(oanda.http, lambda r: httpx.Response(201, json={"orderCancelTransaction": {"reason": "INSUFFICIENT_MARGIN"}}))
    with pytest.raises(BrokerError, match="INSUFFICIENT_MARGIN"):
        run(oanda.market_order("XAUUSD", "sell", 0.1, 3810, 3780, "cid", None))


def test_oanda_live_requires_operator_gate(monkeypatch):
    monkeypatch.setenv("ATLAS_OANDA_TOKEN", "t")
    monkeypatch.setenv("ATLAS_OANDA_ACCOUNT_ID", "a")
    monkeypatch.setenv("ATLAS_OANDA_ENVIRONMENT", "live")
    get_settings.cache_clear()
    from atlas.brokers.oanda import OandaClient
    with pytest.raises(BrokerError, match="LIVE_TRADING_ALLOWED"):
        OandaClient()
    get_settings.cache_clear()


# ---------------------------------------------------------------- MT5 bridge
def test_mt5_bridge_client(monkeypatch):
    monkeypatch.setenv("ATLAS_MT5_BRIDGE_URL", "http://bridge.local:8765")
    monkeypatch.setenv("ATLAS_MT5_BRIDGE_TOKEN", "x" * 32)
    monkeypatch.setenv("ATLAS_MT5_SYMBOL_SUFFIX", ".a")
    get_settings.cache_clear()
    from atlas.brokers.mt5 import MT5Client
    c = MT5Client()
    sent = {}

    def h(req: httpx.Request):
        assert req.headers["X-Bridge-Token"] == "x" * 32
        if req.url.path == "/account":
            return httpx.Response(200, json={"trade_mode": 0, "balance": 5000, "equity": 5010, "margin": 100, "margin_free": 4910, "currency": "USD", "leverage": 30})
        if req.url.path == "/rates":
            assert req.url.params["symbol"] == "XAUUSD.a"
            return httpx.Response(200, json={"point": 0.01, "rates": [{"time": 1794902400, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "tick_volume": 9, "spread": 30},
                                                                      {"time": 1794902700, "open": 1, "high": 1, "low": 1, "close": 1, "tick_volume": 1, "spread": 30}]})
        if req.url.path == "/order":
            sent.update(json.loads(req.content))
            return httpx.Response(200, json={"retcode": 10009, "order": 77, "position": 78, "price": 3800.4, "volume": 0.05})
        if req.url.path == "/positions":
            return httpx.Response(200, json={"positions": [{"ticket": 78, "symbol": "XAUUSD.a", "type": 1, "volume": 0.05, "price_open": 3800.4,
                                                            "sl": 3810.0, "tp": 3780.0, "profit": 2.5, "comment": "cid"},
                                                           {"ticket": 79, "symbol": "BTCUSD", "type": 0, "volume": 1, "price_open": 1, "sl": 0, "tp": 0}]})
        return httpx.Response(404, json={})

    mock(c.http, h)
    a = run(c.account())
    assert a.environment == "demo" and a.equity == 5010
    rates = run(c.candles("XAUUSD", "5m", 1))
    assert len(rates) == 1 and rates[0].spread == pytest.approx(0.30)  # forming bar dropped; spread points → price
    fill = run(c.market_order("XAUUSD", "sell", 0.05, 3810.0, 3780.0, "cid", 0.5))
    assert sent["symbol"] == "XAUUSD.a" and sent["side"] == "sell" and sent["deviation"] == 50 and fill.broker_id == "78"
    trades = run(c.open_trades())
    assert [t.symbol for t in trades] == ["XAUUSD"]  # non gold/forex positions are ignored
    get_settings.cache_clear()
