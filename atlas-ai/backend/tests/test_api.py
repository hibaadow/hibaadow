import pytest
from fastapi.testclient import TestClient

from atlas.api.app import create_app
from atlas.db import session_scope
from atlas.models import User
from atlas.security import hash_password

H = {"x-atlas-client": "web"}


@pytest.fixture
def client():
    from atlas.security import limiter
    limiter.hits.clear()
    app = create_app(disable_agent=True)
    with TestClient(app) as c:
        with session_scope() as db:
            db.add(User(username="viewer1", password_hash=hash_password("viewer-password"), role="viewer"))
            db.add(User(username="trader1", password_hash=hash_password("trader-password"), role="trader"))
        yield c


def login(c, u="admin", p="test-admin-password"):
    r = c.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return r


def test_health_and_auth_required(client):
    assert client.get("/api/health").json()["database"] == "ok"
    assert client.get("/api/overview").status_code == 401
    assert client.get("/api/trades").status_code == 401


def test_login_sets_httponly_cookie_and_me(client):
    r = login(client)
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert client.get("/api/auth/me").json()["role"] == "admin"


def test_bad_password_and_lockout(client):
    for _ in range(5):
        assert client.post("/api/auth/login", json={"username": "trader1", "password": "wrong-pass"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "trader1", "password": "trader-password"}).status_code == 423


def test_csrf_header_required_for_mutations(client):
    login(client)
    assert client.post("/api/control/scanning", json={"enabled": False}).status_code == 403
    assert client.post("/api/control/scanning", json={"enabled": False}, headers=H).status_code == 200


def test_role_permissions(client):
    login(client, "viewer1", "viewer-password")
    assert client.get("/api/overview").status_code == 200
    assert client.post("/api/control/kill-switch", json={"engage": True}, headers=H).status_code == 403
    login(client, "trader1", "trader-password")
    assert client.post("/api/control/kill-switch", json={"engage": True}, headers=H).status_code == 200
    # only admins can release
    assert client.post("/api/control/kill-switch", json={"engage": False}, headers=H).status_code == 403
    assert client.put("/api/settings", json={"symbols": ["SOLUSDC"]}, headers=H).status_code == 403


def test_kill_switch_cycle_and_audit(client):
    login(client)
    r = client.post("/api/control/kill-switch", json={"engage": True, "action": "flatten"}, headers=H)
    assert r.json() == {"kill_switch": True, "action": "flatten"}
    s = client.get("/api/settings").json()["config"]
    assert s["kill_switch"] and not s["automation"]["auto_trading"]
    assert client.post("/api/control/auto-trading", json={"enabled": True}, headers=H).status_code == 409
    ov = client.get("/api/overview").json()
    assert not ov["trading_allowed"]
    assert client.post("/api/control/kill-switch", json={"engage": False}, headers=H).json()["kill_switch"] is False
    actions = [a["action"] for a in client.get("/api/audit").json()]
    assert "kill_switch_engaged" in actions and "kill_switch_released" in actions
    assert any(e["kind"] == "kill_switch" for e in client.get("/api/risk/events").json())


def test_live_mode_and_demo_require_broker(client):
    login(client)
    from atlas.api.routes import LIVE_CONFIRM_PHRASE
    assert client.post("/api/control/live/arm", json={"confirm": "yes"}, headers=H).status_code == 400
    r = client.post("/api/control/live/arm", json={"confirm": LIVE_CONFIRM_PHRASE}, headers=H)
    assert r.status_code == 409 and "no broker configured" in r.text and "LIVE_TRADING_ALLOWED" in r.text
    r = client.post("/api/control/mode", json={"mode": "demo"}, headers=H)
    assert r.status_code == 409 and "no broker configured" in r.text
    assert client.post("/api/control/mode", json={"mode": "live"}, headers=H).status_code == 422  # live only via arm
    s = client.get("/api/settings").json()
    assert s["config"]["mode"] == "paper" and s["broker"]["broker"] == "none"


def test_crypto_and_other_assets_rejected_everywhere(client):
    login(client)
    for sym in ("BTCUSD", "SOLUSDC", "ETHUSD", "SPX500"):
        assert client.get(f"/api/market/{sym}/candles").status_code == 404
    r = client.put("/api/settings", json={"symbols": ["XAUUSD", "BTCUSD"]}, headers=H)
    assert r.status_code == 422 and "not supported" in r.text
    r = client.post("/api/backtests", json={"symbol": "BTCUSD", "strategy": "trend_pullback", "timeframe": "5m",
                                            "start": "2026-10-01T00:00:00Z", "end": "2026-10-20T00:00:00Z"}, headers=H)
    assert r.status_code == 422
    assert client.get("/api/tokens").status_code in (404, 405)
    syms = {i["symbol"] for i in client.get("/api/instruments").json()}
    assert syms == {"XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "GBPJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURGBP", "EURJPY"}


def test_settings_validation_enforces_hard_limits(client):
    login(client)
    assert client.put("/api/settings", json={"risk": {"risk_per_trade_pct": 2.0}}, headers=H).status_code == 422
    r = client.put("/api/settings", json={"min_confidence_to_trade": 70, "mode": "live"}, headers=H)
    assert r.status_code == 200
    cfg = r.json()["config"]
    assert cfg["min_confidence_to_trade"] == 70 and cfg["mode"] == "paper"


def test_markets_gold_calendar_endpoints(client):
    from datetime import datetime, timedelta, timezone

    from atlas.db import session_scope
    from atlas.models import AppSetting

    now = datetime.now(timezone.utc)
    with session_scope() as db:
        db.add(AppSetting(key="analysis_snapshot", value={"ts": 1, "strength": {"USD": -0.1}, "rows": [
            {"symbol": "XAUUSD", "display": "XAU/USD", "asset_class": "gold", "signal": "WAIT"},
            {"symbol": "EURUSD", "display": "EUR/USD", "asset_class": "forex", "signal": "NO TRADE"}]}))
        db.add(AppSetting(key="macro_snapshot", value={"events": [
            {"title": "CPI m/m", "currency": "USD", "time": (now + timedelta(hours=3)).isoformat(), "impact": "High", "central_bank": False},
            {"title": "BOE Official Bank Rate", "currency": "GBP", "time": (now + timedelta(days=1)).isoformat(), "impact": "High", "central_bank": True}],
            "strength": {"USD": -0.1}, "us10y": {"value": 4.1, "trend": "falling"}}))
    login(client)
    m = client.get("/api/markets").json()
    assert [r["symbol"] for r in m["gold"]] == ["XAUUSD"] and [r["symbol"] for r in m["forex"]] == ["EURUSD"]
    cal = client.get("/api/calendar", params={"impact": "High"}).json()
    cpi = next(e for e in cal["events"] if e["title"] == "CPI m/m")
    assert "XAUUSD" in cpi["affects"] and "EURGBP" not in cpi["affects"]
    assert next(e for e in cal["events"] if e["currency"] == "GBP")["central_bank"]
    g = client.get("/api/gold").json()
    assert g["row"]["symbol"] == "XAUUSD" and g["us10y"]["trend"] == "falling" and len(g["usd_events"]) == 1
    assert g["spec"]["contract_size"] == 100


def test_trades_search_and_csv_export(client):
    from datetime import datetime, timezone

    from atlas.db import session_scope
    from atlas.models import Position
    from atlas.portfolio import get_account

    with session_scope() as db:
        acct = get_account(db, "paper", 10_000)
        now = datetime.now(timezone.utc)
        db.add(Position(account_id=acct.id, mode="paper", symbol="XAUUSD", strategy="gold_session", side="sell", status="closed", opened_at=now,
                        closed_at=now, qty=0, initial_qty=0.1, entry_price=3800, exit_price=3780, stop_price=3810, initial_stop=3810, tp1=3780,
                        risk_amount=100, fees_paid=0.7, gross_pnl=200, net_pnl=199.3, entry_reason="=HYPERLINK('x')", exit_reason="tp1"))
    login(client)
    r = client.get("/api/trades", params={"q": "gold"}).json()
    assert r["total"] == 1 and r["rows"][0]["r_multiple"] == pytest.approx(1.993) and r["rows"][0]["side"] == "sell"
    assert client.get("/api/trades", params={"asset_class": "forex"}).json()["total"] == 0
    csv = client.get("/api/trades/export.csv").text
    assert "XAUUSD" in csv and "'=HYPERLINK" in csv


def test_backtest_validation(client):
    login(client)
    r = client.post("/api/backtests", json={"symbol": "EURUSD", "strategy": "gold_session", "timeframe": "5m",
                                            "start": "2026-10-01T00:00:00Z", "end": "2026-10-20T00:00:00Z"}, headers=H)
    assert r.status_code == 422 and "XAUUSD" in r.text
    r = client.post("/api/backtests", json={"symbol": "EURUSD", "strategy": "trend_pullback", "timeframe": "1m",
                                            "start": "2025-01-01T00:00:00Z", "end": "2026-10-01T00:00:00Z"}, headers=H)
    assert r.status_code == 422 and "too large" in r.text


def test_strategy_param_bounds(client):
    login(client)
    assert client.put("/api/strategies/trend_pullback", json={"params": {"stop_atr_min": 100}}, headers=H).status_code == 422
    assert client.put("/api/strategies/trend_pullback", json={"params": {"bogus": 1}}, headers=H).status_code == 422
    assert client.put("/api/strategies/trend_pullback", json={"params": {"stop_atr_min": 1.2}}, headers=H).status_code == 200
    s = {x["name"]: x for x in client.get("/api/strategies").json()}
    assert s["trend_pullback"]["params"]["stop_atr_min"] == 1.2 and s["gold_session"]["instruments"] == ["XAUUSD"]


def test_integrations_report_credentials_honestly(client):
    login(client)
    r = client.get("/api/integrations").json()
    by = {i["name"]: i for i in r["integrations"]}
    assert by["oanda"]["status"] == "unconfigured" and by["mt5_bridge"]["status"] == "unconfigured"
    assert by["public_quotes"]["requires_credentials"] is False
    assert not any(k in str(r).lower() for k in ("binance", "solana", "jupiter", "dexscreener"))


def test_security_headers(client):
    r = client.get("/api/health")
    assert r.headers["x-frame-options"] == "DENY" and "frame-ancestors 'none'" in r.headers["content-security-policy"]


def test_websocket_requires_auth(client):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/ws") as ws:
            ws.receive_json()
