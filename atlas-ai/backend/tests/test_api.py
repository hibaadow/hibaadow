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
    assert s["kill_switch"] and not s["automation"]["auto_paper_trading"]
    assert client.post("/api/control/auto-paper", json={"enabled": True}, headers=H).status_code == 409
    ov = client.get("/api/overview").json()
    assert not ov["trading_allowed"]
    assert client.post("/api/control/kill-switch", json={"engage": False}, headers=H).json()["kill_switch"] is False
    actions = [a["action"] for a in client.get("/api/audit").json()]
    assert "kill_switch_engaged" in actions and "kill_switch_released" in actions
    assert any(e["kind"] == "kill_switch" for e in client.get("/api/risk/events").json())


def test_settings_validation_enforces_hard_limits(client):
    login(client)
    r = client.put("/api/settings", json={"risk": {"risk_per_trade_pct": 2.0}}, headers=H)
    assert r.status_code == 422
    r = client.put("/api/settings", json={"symbols": ["SOLUSDC", "<script>"]}, headers=H)
    assert r.status_code == 422
    r = client.put("/api/settings", json={"min_confidence_to_trade": 70, "mode": "live"}, headers=H)
    assert r.status_code == 200
    cfg = r.json()["config"]
    assert cfg["min_confidence_to_trade"] == 70 and cfg["mode"] == "paper"  # mode only via dedicated endpoint


def test_live_mode_cannot_be_armed_without_operator_gate(client):
    login(client)
    r = client.post("/api/control/live/arm", json={"confirm": "yes"}, headers=H)
    assert r.status_code == 400
    from atlas.api.routes import LIVE_CONFIRM_PHRASE
    r = client.post("/api/control/live/arm", json={"confirm": LIVE_CONFIRM_PHRASE}, headers=H)
    assert r.status_code == 409 and "ATLAS_LIVE_TRADING_ALLOWED" in r.text


def test_trades_search_and_csv_export(client):
    from datetime import datetime, timezone

    from atlas.models import Position
    from atlas.portfolio import get_account

    with session_scope() as db:
        acct = get_account(db, "paper", 10_000)
        now = datetime.now(timezone.utc)
        db.add(Position(account_id=acct.id, mode="paper", symbol="SOLUSDC", strategy="breakout", status="closed", opened_at=now,
                        closed_at=now, qty=0, initial_qty=1, entry_price=100, exit_price=104, stop_price=98, initial_stop=98, tp1=104,
                        risk_amount=2, fees_paid=0.2, gross_pnl=4, net_pnl=3.8, entry_reason="=HYPERLINK('x')", exit_reason="tp1"))
    login(client)
    r = client.get("/api/trades", params={"q": "break"}).json()
    assert r["total"] == 1 and r["rows"][0]["r_multiple"] == pytest.approx(1.9)
    assert client.get("/api/trades", params={"q": "nomatch"}).json()["total"] == 0
    csv = client.get("/api/trades/export.csv").text
    assert "SOLUSDC" in csv and "'=HYPERLINK" in csv  # formula injection neutralised


def test_backtest_validation(client):
    login(client)
    r = client.post("/api/backtests", json={"symbol": "SOLUSDC", "strategy": "nope", "timeframe": "5m",
                                            "start": "2026-01-01T00:00:00Z", "end": "2026-01-10T00:00:00Z"}, headers=H)
    assert r.status_code == 422
    r = client.post("/api/backtests", json={"symbol": "SOLUSDC", "strategy": "momentum", "timeframe": "1m",
                                            "start": "2025-01-01T00:00:00Z", "end": "2026-01-10T00:00:00Z"}, headers=H)
    assert r.status_code == 422 and "too large" in r.text


def test_strategy_param_bounds(client):
    login(client)
    assert client.put("/api/strategies/momentum", json={"params": {"min_rel_volume": 100}}, headers=H).status_code == 422
    assert client.put("/api/strategies/momentum", json={"params": {"bogus": 1}}, headers=H).status_code == 422
    assert client.put("/api/strategies/momentum", json={"params": {"min_rel_volume": 2.0}}, headers=H).status_code == 200
    s = {x["name"]: x for x in client.get("/api/strategies").json()}
    assert s["momentum"]["params"]["min_rel_volume"] == 2.0


def test_security_headers(client):
    r = client.get("/api/health")
    assert r.headers["x-frame-options"] == "DENY" and "frame-ancestors 'none'" in r.headers["content-security-policy"]


def test_websocket_requires_auth(client):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/ws") as ws:
            ws.receive_json()
