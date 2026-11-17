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
    fill = run(c.market_order("XAUUSD", "sell", 0.05, 3810.0, 3780.0, "cid", None, 5.0))  # 5 pips = $0.50 = 50 points
    assert sent["symbol"] == "XAUUSD.a" and sent["side"] == "sell" and sent["deviation"] == 50 and fill.broker_id == "78"
    trades = run(c.open_trades())
    assert [t.symbol for t in trades] == ["XAUUSD"]  # non gold/forex positions are ignored
    get_settings.cache_clear()


# ---------------------------------------------------------------- MetaApi (MT5 without Windows)
@pytest.fixture
def metaapi(monkeypatch):
    monkeypatch.setenv("ATLAS_METAAPI_TOKEN", "meta-token")
    monkeypatch.setenv("ATLAS_METAAPI_ACCOUNT_ID", "acc-1")
    get_settings.cache_clear()
    state = {"positions": [], "deals": [], "trades": [], "account_state": "DEPLOYED"}

    def handler(req: httpx.Request):
        assert req.headers["auth-token"] == "meta-token"
        host, path = req.url.host, req.url.path
        if host == "mt-provisioning-api-v1.agiliumtrade.agiliumtrade.ai":
            return httpx.Response(200, json={"_id": "acc-1", "state": state["account_state"], "region": "london"})
        assert host.endswith(".london.agiliumtrade.ai"), host  # region auto-detected
        base = "/users/current/accounts/acc-1"
        if path == base + "/account-information":
            return httpx.Response(200, json={"broker": "Demo Broker", "currency": "USD", "server": "Demo-Server", "balance": 10000, "equity": 10012.5,
                                             "margin": 120, "freeMargin": 9892.5, "leverage": 30, "type": "ACCOUNT_TRADE_MODE_DEMO", "platform": "mt5"})
        if path.endswith("/specification"):
            return httpx.Response(200, json={"symbol": "XAUUSD", "tickSize": 0.01, "contractSize": 100, "minVolume": 0.01, "volumeStep": 0.01})
        if path.endswith("/current-price"):
            return httpx.Response(200, json={"symbol": "XAUUSD", "bid": 3850.10, "ask": 3850.42, "time": "2026-11-17T10:00:00.000Z"})
        if "/historical-market-data/" in path:
            assert host.startswith("mt-market-data-client-api-v1.")
            return httpx.Response(200, json=[  # newest first, like MetaApi; last one still forming
                {"symbol": "XAUUSD", "timeframe": "5m", "time": "2099-01-01T00:00:00.000Z", "open": 1, "high": 1, "low": 1, "close": 1, "tickVolume": 1, "spread": 30},
                {"symbol": "XAUUSD", "timeframe": "5m", "time": "2026-11-10T09:55:00.000Z", "open": 3849, "high": 3851, "low": 3848, "close": 3850, "tickVolume": 410, "spread": 32},
                {"symbol": "XAUUSD", "timeframe": "5m", "time": "2026-11-10T09:50:00.000Z", "open": 3847, "high": 3849.5, "low": 3846, "close": 3849, "tickVolume": 380, "spread": 30}])
        if path == base + "/positions":
            return httpx.Response(200, json=state["positions"])
        if path.startswith(base + "/history-deals/position/"):
            return httpx.Response(200, json=state["deals"])
        if path == base + "/trade":
            body = json.loads(req.content)
            state["trades"].append(body)
            if body["actionType"] in ("ORDER_TYPE_BUY", "ORDER_TYPE_SELL"):
                state["positions"].append({"id": "900", "type": "POSITION_TYPE_SELL" if body["actionType"] == "ORDER_TYPE_SELL" else "POSITION_TYPE_BUY",
                                           "symbol": body["symbol"], "magic": body["magic"], "openPrice": 3850.08, "volume": body["volume"],
                                           "stopLoss": body["stopLoss"], "takeProfit": body.get("takeProfit"), "clientId": body["clientId"],
                                           "commission": -0.35, "unrealizedProfit": 0, "time": "2026-11-17T10:00:01.000Z"})
                state["deals"] = [{"id": "d1", "entryType": "DEAL_ENTRY_IN", "type": "DEAL_TYPE_SELL", "price": 3850.08, "volume": body["volume"], "commission": -0.35}]
                return httpx.Response(200, json={"numericCode": 10009, "stringCode": "TRADE_RETCODE_DONE", "message": "Request completed", "orderId": "901"})
            if body["actionType"] == "POSITION_PARTIAL":
                state["deals"].append({"id": "d2", "entryType": "DEAL_ENTRY_OUT", "type": "DEAL_TYPE_BUY", "price": 3830.0, "volume": body["volume"],
                                       "profit": 100.4, "commission": -0.18, "swap": 0})
                state["positions"][0]["volume"] = round(state["positions"][0]["volume"] - body["volume"], 2)
                return httpx.Response(200, json={"numericCode": 10009, "stringCode": "TRADE_RETCODE_DONE", "orderId": "902", "positionId": "900"})
            if body["actionType"] == "POSITION_CLOSE_ID":
                state["deals"].append({"id": "d3", "entryType": "DEAL_ENTRY_OUT", "type": "DEAL_TYPE_BUY", "price": 3820.0, "volume": state["positions"][0]["volume"],
                                       "profit": 150.2, "commission": -0.17, "swap": -0.3})
                state["positions"] = []
                return httpx.Response(200, json={"numericCode": 10009, "stringCode": "TRADE_RETCODE_DONE", "orderId": "903", "positionId": "900"})
            if body["actionType"] == "POSITION_MODIFY":
                return httpx.Response(200, json={"numericCode": 10016, "stringCode": "TRADE_RETCODE_INVALID_STOPS", "message": "Invalid stops"})
        return httpx.Response(404, json={"error": "NotFound"})

    def fake_http(self):
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), headers=self._headers)
        return self._client

    monkeypatch.setattr(ProviderClient, "_http", fake_http)
    from atlas.brokers.metaapi import MetaApiClient
    yield MetaApiClient(), state
    get_settings.cache_clear()


def test_metaapi_account_candles_and_prices(metaapi):
    c, _ = metaapi
    a = run(c.account())
    assert a.environment == "demo" and a.equity == 10012.5 and c.region == "london"
    cs = run(c.candles("XAUUSD", "5m", 10))
    assert [x.close for x in cs] == [3849, 3850]                 # sorted ascending, forming bar dropped
    assert cs[-1].spread == pytest.approx(0.32) and cs[-1].volume == 410  # spread points × tickSize
    q = run(c.quotes(["XAUUSD"]))["XAUUSD"]
    assert (q.bid, q.ask) == (3850.10, 3850.42)


def test_metaapi_order_lifecycle_and_duplicates(metaapi):
    from atlas.brokers.metaapi import short_client_id
    c, state = metaapi
    fill = run(c.market_order("XAUUSD", "sell", 0.05, 3860.0, 3830.0, "atlas-demo-XAUUSD-gold_s-1794902400", None, 5.0))
    body = state["trades"][0]
    assert body["actionType"] == "ORDER_TYPE_SELL" and body["volume"] == 0.05 and body["stopLoss"] == 3860.0 and body["takeProfit"] == 3830.0
    assert len(body["clientId"]) <= 26 and body["clientId"] == short_client_id("atlas-demo-XAUUSD-gold_s-1794902400")
    assert body["slippage"] == 50 and body["magic"] == c.magic       # 5 pips × $0.10 / 0.01 tick = 50 points
    assert fill.broker_id == "900" and fill.price == 3850.08
    with pytest.raises(BrokerError, match="duplicate"):
        run(c.market_order("XAUUSD", "sell", 0.05, 3860.0, 3830.0, "atlas-demo-XAUUSD-gold_s-1794902400", None, 5.0))
    trades = run(c.open_trades())
    assert len(trades) == 1 and trades[0].side == "sell" and trades[0].symbol == "XAUUSD"
    part = run(c.close_trade("900", "XAUUSD", 0.02))
    assert part.lots == pytest.approx(0.02) and part.price == 3830.0 and part.realized_pnl == pytest.approx(100.4)
    full = run(c.close_trade("900", "XAUUSD"))
    assert full.price == 3820.0 and full.realized_pnl == pytest.approx(150.2)
    det = run(c.trade_details("900"))
    assert det["state"] == "CLOSED" and det["realized_pnl"] == pytest.approx(250.6)


def test_metaapi_rejections_and_undeployed(metaapi, monkeypatch):
    c, state = metaapi
    with pytest.raises(BrokerError, match="INVALID_STOPS"):
        run(c.modify_stop("900", "XAUUSD", 3840.0))
    from atlas.brokers.metaapi import MetaApiClient
    state["account_state"] = "UNDEPLOYED"
    with pytest.raises(BrokerError, match="deploy"):
        run(MetaApiClient().account())


def test_metaapi_requires_credentials(monkeypatch):
    monkeypatch.delenv("ATLAS_METAAPI_TOKEN", raising=False)
    get_settings.cache_clear()
    from atlas.brokers.metaapi import MetaApiClient
    with pytest.raises(BrokerError, match="not configured"):
        MetaApiClient()
    get_settings.cache_clear()
