"""Chart Coach: image validation, deterministic verification of the AI's chart reading, and the upload endpoint."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from atlas.marketdata.types import Quote
from atlas.screenshot import ScreenshotError, assess, validate_images
from atlas.trading_config import TradingConfig

NOW = datetime(2026, 11, 17, 14, 0, tzinfo=timezone.utc)  # Tuesday, London/NY overlap
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


def q(sym, bid, ask):
    x = Quote(sym, "test", bid, ask, (bid + ask) / 2)
    return x


QUOTES = {"XAUUSD": q("XAUUSD", 3850.10, 3850.42), "EURUSD": q("EURUSD", 1.10000, 1.10012), "GBPUSD": q("GBPUSD", 1.27, 1.27012),
          "USDJPY": q("USDJPY", 150.0, 150.012)}


def reading(**kw):
    base = {"readable": True, "instrument": "XAUUSD", "timeframe": "M15", "platform": "MetaTrader 5", "visible_price": 3850.2, "trend": "up",
            "observations": ["higher highs", "retest of 3845 support", "bullish engulfing"], "key_levels": [{"price": 3845.0, "kind": "support", "note": "retest"}],
            "recommendation": "BUY", "entry": 3850.4, "stop_loss": 3843.0, "take_profit": 3868.0, "rationale": "trend continuation after retest",
            "invalidation": ["M15 close below 3843"], "risks": ["US data later"], "uncertainties": [], "confidence": 72}
    base.update(kw)
    return base


def run_assess(r, events=(), balance=10_000, risk=0.5):
    for qq in QUOTES.values():
        qq.ts = __import__("time").time()
    return assess(r, TradingConfig(), QUOTES, list(events), [{"symbol": "XAUUSD", "signal": "WAIT", "trend_1h": "up"}], balance, risk, NOW)


def names(res, passed=None):
    return {c["name"] for c in res["checks"] if passed is None or c["passed"] == passed}


def test_image_validation():
    assert validate_images([PNG])[0][1] == "image/png"
    assert validate_images([b"\xff\xd8\xff" + b"0" * 10])[0][1] == "image/jpeg"
    with pytest.raises(ScreenshotError, match="HEIC"):
        validate_images([b"\x00\x00\x00\x18ftypheic"])
    with pytest.raises(ScreenshotError, match="at most"):
        validate_images([PNG] * 5)
    with pytest.raises(ScreenshotError, match="5 MB"):
        validate_images([PNG + b"0" * (5 * 1024 * 1024)])
    with pytest.raises(ScreenshotError):
        validate_images([])


def test_good_gold_buy_is_sized_and_confirmed():
    res = run_assess(reading())
    assert res["final"] == "BUY", res["final_reasons"]
    sz = res["sizing"]
    assert sz["lots"] >= 0.01 and sz["risk_usd"] <= 50.0 and sz["net_rr"] >= 2.0
    assert res["live"]["difference_pips"] < 5 and res["atlas_view"]["trend_1h"] == "up"


def test_unsupported_and_unreadable():
    assert run_assess(reading(instrument="OTHER"))["final"] == "NO TRADE"
    r = run_assess(reading(readable=False, uncertainties=["blurry"]))
    assert r["final"] == "NO TRADE" and "could not be read" in r["final_reasons"][0]


def test_old_screenshot_price_mismatch_downgrades_to_wait():
    res = run_assess(reading(visible_price=3790.0, entry=3790.4, stop_loss=3783.0, take_profit=3808.0))
    assert res["final"] in ("WAIT", "NO TRADE") and "price_cross_check" in names(res, False)


def test_wrong_side_stop_and_news_blackout_block():
    assert run_assess(reading(stop_loss=3855.0))["final"] == "NO TRADE"
    cpi = [{"title": "CPI m/m", "country": "USD", "date": "2026-11-17T09:10:00-05:00", "impact": "High"}]  # 14:10 UTC
    res = run_assess(reading(), events=cpi)
    assert res["final"] == "NO TRADE" and "news_blackout" in names(res, False)
    assert res["events"][0]["title"] == "CPI m/m"


def test_ai_wait_is_never_upgraded_and_low_confidence_downgraded():
    assert run_assess(reading(recommendation="WAIT"))["final"] == "WAIT"
    assert run_assess(reading(confidence=40))["final"] == "WAIT"


def test_target_moved_out_when_too_close_for_net_rr():
    res = run_assess(reading(take_profit=3858.0))  # ~1x the stop → ATLAS requires ≥2R net
    assert res["sizing"]["target"] > 3858.0


def test_small_balance_below_min_lot():
    res = run_assess(reading(), balance=100)
    assert res["final"] == "NO TRADE" and "min_lot" in names(res, False)


@pytest.fixture
def client(monkeypatch):
    from atlas.api.app import create_app
    from atlas.db import session_scope
    from atlas.models import User
    from atlas.security import hash_password, limiter

    limiter.hits.clear()
    with TestClient(create_app(disable_agent=True)) as c:
        with session_scope() as db:
            db.add(User(username="viewer1", password_hash=hash_password("viewer-password"), role="viewer"))
        yield c


H = {"x-atlas-client": "web"}


def test_endpoint_requires_key_and_role(client):
    client.post("/api/auth/login", json={"username": "viewer1", "password": "viewer-password"})
    assert client.post("/api/coach/analyze", files=[("files", ("c.png", PNG, "image/png"))], headers=H).status_code == 403
    client.post("/api/auth/login", json={"username": "admin", "password": "test-admin-password"})
    r = client.post("/api/coach/analyze", files=[("files", ("c.png", PNG, "image/png"))], headers=H)
    assert r.status_code == 503 and "ANTHROPIC_API_KEY" in r.text
    r = client.post("/api/coach/analyze", files=[("files", ("x.heic", b"\x00\x00\x00\x18ftypheic", "image/heic"))], headers=H)
    assert r.status_code == 400


def test_endpoint_end_to_end_with_mocked_reader(client, monkeypatch):
    async def fake_read(images, note):
        assert len(images) == 2 and note == "London open"
        return reading(instrument="EURUSD", visible_price=None, entry=1.1001, stop_loss=1.0981, take_profit=1.1045, confidence=65)

    monkeypatch.setattr("atlas.api.coach.read_chart", fake_read)
    client.post("/api/auth/login", json={"username": "admin", "password": "test-admin-password"})
    r = client.post("/api/coach/analyze", files=[("files", ("a.png", PNG, "image/png")), ("files", ("b.png", PNG, "image/png"))],
                    data={"note": "London open", "balance": "5000", "risk_pct": "0.5"}, headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["instrument"] == "EURUSD" and body["final"] in ("BUY", "WAIT", "NO TRADE")
    assert body["result"]["disclaimer"] and body["result"]["reading"]["entry"] == 1.1001
    assert client.get("/api/coach/history").json()[0]["id"] == body["id"]
    assert client.post("/api/coach/analyze", files=[("files", ("a.png", PNG, "image/png"))], data={"risk_pct": "3"}, headers=H).status_code == 422
