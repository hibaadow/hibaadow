import asyncio

import httpx
import pytest

from atlas.marketdata.http import ProviderClient, ProviderError
from atlas.strategies.token_scanner import TokenReport, assess_holders, assess_market, assess_mint, assess_sell_route, sanitize_text, sanitize_url, score, valid_mint


def client_with(handler, retries=3):
    c = ProviderClient("test", "https://example.test", rate_per_sec=1000, burst=1000, max_retries=retries)
    c._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return c


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def test_retries_server_errors_then_succeeds():
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, json={})
        return httpx.Response(200, json={"ok": True})

    assert run(client_with(h).get("/x")) == {"ok": True}
    assert calls["n"] == 3


def test_rate_limit_respects_retry_after_and_fails_after_retries():
    def h(req):
        return httpx.Response(429, headers={"Retry-After": "0.01"}, json={})

    c = client_with(h, retries=1)
    with pytest.raises(ProviderError) as e:
        run(c.get("/x"))
    assert e.value.status == 429
    assert c.health()["status"] in ("degraded", "down")


def test_rejects_non_json_and_client_errors():
    with pytest.raises(ProviderError):
        run(client_with(lambda r: httpx.Response(200, text="<html>", headers={"content-type": "text/html"})).get("/x"))
    with pytest.raises(ProviderError) as e:
        run(client_with(lambda r: httpx.Response(400, json={"msg": "bad"})).get("/x"))
    assert e.value.status == 400


def test_network_errors_raise_provider_error():
    def h(req):
        raise httpx.ConnectError("boom")

    with pytest.raises(ProviderError):
        run(client_with(h, retries=1).get("/x"))


def test_metadata_sanitisation():
    assert "<script>" not in sanitize_text("<script>alert(1)</script>")
    assert sanitize_text("A‮B\x00C") == "ABC"
    assert sanitize_url("javascript:alert(1)") is None
    assert sanitize_url("https://ok.example/x") == "https://ok.example/x"
    assert not valid_mint("../../etc/passwd")
    assert valid_mint("JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN")


def test_mint_and_freeze_authority_are_critical():
    r = TokenReport("M")
    assess_mint(r, {"info": {"mintAuthority": "abc", "freezeAuthority": "def", "supply": "100", "decimals": 6}}, None)
    score(r)
    codes = {f["code"] for f in r.flags}
    assert {"mint_authority", "freeze_authority"} <= codes and r.risk_level == "extreme"


def test_token2022_transfer_tax_flag():
    r = TokenReport("M")
    ext = [{"extension": "transferFeeConfig", "state": {"newerTransferFee": {"transferFeeBasisPoints": 1000}}}]
    assess_mint(r, {"info": {"mintAuthority": None, "freezeAuthority": None, "extensions": ext}}, None)
    assert any(f["code"] == "ext_transferFeeConfig" and f["severity"] == "critical" for f in r.flags)


def test_honeypot_and_wash_trading_signals():
    r = TokenReport("M")
    pair = {"liquidity": {"usd": 5000}, "volume": {"h24": 900_000}, "txns": {"h24": {"buys": 800, "sells": 0}},
            "pairCreatedAt": None, "priceChange": {"h1": 150}}
    assess_market(r, pair)
    assess_sell_route(r, None, "no route")
    score(r)
    codes = {f["code"] for f in r.flags}
    assert {"low_liquidity", "no_sells", "wash_trading_turnover", "extreme_volatility", "no_sell_route"} <= codes
    assert r.risk_level == "extreme"


def test_holder_concentration_and_unverified():
    r = TokenReport("M")
    assess_holders(r, [{"amount": "500"}, {"amount": "300"}, {"amount": "100"}], "1000", 6)
    assert r.top10_holder_pct == pytest.approx(90.0)
    assert any(f["code"] == "holder_concentration" for f in r.flags)
    r2 = TokenReport("M")
    assess_holders(r2, None, None, None)
    assert any(f["code"] == "holders_unverified" for f in r2.flags)


def test_new_tokens_are_never_rated_safe():
    r = score(TokenReport("M"))
    assert r.risk_level == "moderate"
