"""REST API."""
from __future__ import annotations

import csv
import io
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from .. import indicators as ind
from ..config import get_settings
from ..db import get_db
from ..decision import calibration
from ..execution.live import preflight
from ..marketdata.providers import BinanceMarketData
from ..marketdata.types import TF_MS
from ..marketdata.types import Candle as C
from ..marketdata.validation import validate_candles
from ..models import (ActivityEvent, AppSetting, AuditLog, Candle, Command, Decision, Execution, IntegrationStatus, Order,
                      Position, RiskEvent, Signal, StrategyConfig, TokenScan, User)
from ..portfolio import analytics, get_account, overview, risk_context
from ..risk import gate_status
from ..security import (COOKIE, ROLES, audit, client_ip, current_user, ensure_admin, hash_password, issue_token, limiter, login,
                        require)
from ..strategies.library import STRATEGIES
from ..trading_config import (HARD_MAX_DAILY_LOSS_PCT, HARD_MAX_OPEN_POSITIONS, HARD_MAX_RISK_PER_TRADE_PCT, HARD_MAX_WEEKLY_LOSS_PCT,
                              HARD_MIN_RR, SUPPORTED_TIMEFRAMES, TradingConfig, load_config, save_config)

router = APIRouter(prefix="/api")
LIVE_CONFIRM_PHRASE = "I understand live trading uses real funds"


def setting(db: Session, key: str, default=None):
    row = db.get(AppSetting, key)
    return row.value if row else default


def prices(db: Session) -> dict[str, float]:
    snap = setting(db, "scanner_snapshot", {}) or {}
    return {r["symbol"]: r["price"] for r in snap.get("rows", []) if r.get("price")}


def iso(dt):
    return dt.isoformat() if dt else None


def pos_dict(p: Position) -> dict:
    dur = None
    if p.opened_at:
        end = p.closed_at or datetime.now(timezone.utc)
        dur = (end - p.opened_at).total_seconds()
    r = p.initial_stop and (p.entry_price or p.planned_entry) - p.initial_stop
    return {"id": p.id, "mode": p.mode, "symbol": p.symbol, "strategy": p.strategy, "side": p.side, "status": p.status,
            "opened_at": iso(p.opened_at), "closed_at": iso(p.closed_at), "created_at": iso(p.created_at), "qty": p.qty,
            "initial_qty": p.initial_qty, "entry_price": p.entry_price, "exit_price": p.exit_price, "stop_price": p.stop_price,
            "initial_stop": p.initial_stop, "tp1": p.tp1, "tp2": p.tp2, "tp1_hit": p.tp1_hit, "risk_amount": p.risk_amount,
            "fees": p.fees_paid, "slippage": p.slippage_cost, "gross_pnl": p.gross_pnl, "net_pnl": p.net_pnl,
            "r_multiple": round(p.net_pnl / p.risk_amount, 3) if p.status == "closed" and p.risk_amount else None,
            "rr": round((p.tp1 - p.entry_price) / r, 2) if r and r > 0 and p.entry_price else None,
            "position_value": (p.qty * (p.last_price or p.entry_price)), "last_price": p.last_price,
            "unrealized_pnl": (p.qty * ((p.last_price or p.entry_price) - p.entry_price)) if p.status == "open" else 0.0,
            "entry_reason": p.entry_reason, "exit_reason": p.exit_reason, "duration_s": dur, "decision_id": p.decision_id,
            "stop_history": p.stop_history}


def order_dict(o: Order) -> dict:
    return {"id": o.id, "client_order_id": o.client_order_id, "mode": o.mode, "position_id": o.position_id, "symbol": o.symbol,
            "side": o.side, "type": o.type, "purpose": o.purpose, "qty": o.qty, "filled_qty": o.filled_qty, "limit_price": o.limit_price,
            "stop_price": o.stop_price, "avg_fill_price": o.avg_fill_price, "status": o.status, "fees": o.fees, "reason": o.reason,
            "venue": o.venue, "created_at": iso(o.created_at), "updated_at": iso(o.updated_at)}


# ------------------------------------------------------------------ health / auth
@router.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("select 1"))
    hb = setting(db, "agent_heartbeat")
    age = time.time() - hb["ts"] if hb else None
    return {"status": "ok", "database": "ok", "worker": "ok" if age is not None and age < 30 else "down",
            "worker_heartbeat_age_s": round(age, 1) if age is not None else None, "time": datetime.now(timezone.utc).isoformat()}


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


@router.post("/auth/login")
def do_login(body: LoginBody, request: Request, response: Response, db: Session = Depends(get_db)):
    if not limiter.allow(f"login:{client_ip(request)}", 10, 60):
        raise HTTPException(429, "too many login attempts; wait a minute")
    try:
        user = login(db, body.username, body.password)
    except HTTPException:
        audit(db, None, "login_failed", body.username, request=request)
        db.commit()
        raise
    s = get_settings()
    response.set_cookie(COOKIE, issue_token(user), httponly=True, secure=s.cookie_secure, samesite="strict",
                        max_age=s.session_ttl_minutes * 60, path="/")
    audit(db, user, "login", request=request)
    return {"username": user.username, "role": user.role}


@router.post("/auth/logout")
def logout(response: Response, request: Request, db: Session = Depends(get_db)):
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.post("/auth/logout-all")
def logout_all(response: Response, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.session_version += 1
    audit(db, user, "logout_all", request=request)
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/auth/me")
def me(user: User = Depends(current_user)):
    return {"username": user.username, "role": user.role, "permissions": {"trade": ROLES[user.role] >= 1, "admin": ROLES[user.role] >= 2}}


class PasswordBody(BaseModel):
    current: str
    new: str = Field(min_length=10, max_length=256)


@router.post("/auth/password")
def change_password(body: PasswordBody, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from ..security import verify_password

    if not verify_password(body.current, user.password_hash):
        raise HTTPException(400, "current password incorrect")
    user.password_hash = hash_password(body.new)
    user.session_version += 1
    audit(db, user, "password_changed", request=request)
    return {"ok": True, "note": "all sessions signed out"}


class UserBody(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=10, max_length=256)
    role: str = Field(pattern="^(viewer|trader|admin)$")


@router.get("/users")
def users(user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    return [{"username": u.username, "role": u.role, "last_login": iso(u.last_login), "created_at": iso(u.created_at)}
            for u in db.query(User).order_by(User.id)]


@router.post("/users")
def create_user(body: UserBody, request: Request, user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    if db.query(User).filter_by(username=body.username).count():
        raise HTTPException(409, "username exists")
    db.add(User(username=body.username, password_hash=hash_password(body.password), role=body.role))
    audit(db, user, "user_created", body.username, {"role": body.role}, request)
    return {"ok": True}


# ------------------------------------------------------------------ dashboard
@router.get("/overview")
def get_overview(mode: str = Query("paper", pattern="^(paper|live)$"), user: User = Depends(current_user), db: Session = Depends(get_db)):
    cfg = load_config(db)
    acct = get_account(db, mode, cfg.paper_starting_capital)
    px = prices(db)
    ov = overview(db, acct, px)
    gates = gate_status(cfg, risk_context(db, acct, px))
    hb = setting(db, "agent_heartbeat")
    return {**ov, "gates": gates.checks, "trading_allowed": gates.approved, "halt": gates.halt,
            "agent": {**(hb or {}), "alive": bool(hb and time.time() - hb["ts"] < 30)},
            "config": {"mode": cfg.mode, "kill_switch": cfg.kill_switch, "trading_enabled": cfg.trading_enabled,
                       "scanning": cfg.automation.scanning_enabled, "auto_paper": cfg.automation.auto_paper_trading,
                       "risk_per_trade_pct": cfg.risk.risk_per_trade_pct},
            "results_label": "PAPER TRADING (simulated fills on live market data)" if mode == "paper" else "LIVE TRADING"}


@router.get("/scanner")
def scanner(user: User = Depends(current_user), db: Session = Depends(get_db)):
    snap = setting(db, "scanner_snapshot") or {"rows": [], "ts": None, "regime": "unknown"}
    return snap


@router.get("/market/{symbol}/candles")
async def candles(request: Request, symbol: str, tf: str = Query("5m"), limit: int = Query(300, ge=50, le=1000),
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
    symbol = symbol.upper()
    if tf not in SUPPORTED_TIMEFRAMES or not symbol.isalnum() or len(symbol) > 20:
        raise HTTPException(400, "invalid symbol or timeframe")
    rows = db.execute(select(Candle).where(Candle.symbol == symbol, Candle.timeframe == tf).order_by(Candle.open_time.desc())
                      .limit(limit)).scalars().all()
    src = "database"
    cs = [C(r.open_time, r.open, r.high, r.low, r.close, r.volume, r.quote_volume) for r in reversed(rows)]
    fresh = cs and (time.time() * 1000 - (cs[-1].open_time + TF_MS[tf])) < 3 * TF_MS[tf]
    if len(cs) < min(limit, 200) or not fresh:
        md: BinanceMarketData = request.app.state.binance
        try:
            cs = await md.candles(symbol, tf, limit)
            src = "binance"
        except Exception as e:  # noqa: BLE001
            if not cs:
                raise HTTPException(502, f"market data unavailable: {str(e)[:120]}")
    clean, report = validate_candles(cs, tf, drop_open=False)
    import numpy as np

    c = np.array([x.close for x in clean])
    h = np.array([x.high for x in clean])
    l_ = np.array([x.low for x in clean])
    v = np.array([x.volume for x in clean])
    t = np.array([x.open_time for x in clean])

    def series(a):
        return [None if (x != x) else round(float(x), 10) for x in a]

    vw, _ = ind.vwap(h, l_, c, v, t) if len(c) else (c, c)
    return {"symbol": symbol, "timeframe": tf, "source": src, "quality": {k: report[k] for k in ("invalid", "duplicates", "missing_bars", "issues")},
            "candles": [{"t": x.open_time // 1000, "o": x.open, "h": x.high, "l": x.low, "c": x.close, "v": x.volume} for x in clean],
            "indicators": {"ema9": series(ind.ema(c, 9)), "ema21": series(ind.ema(c, 21)), "ema50": series(ind.ema(c, 50)),
                           "ema200": series(ind.ema(c, 200)), "vwap": series(vw), "rsi": series(ind.rsi(c, 14))}}


@router.get("/positions")
def positions(status: str = Query("open", pattern="^(open|closed|all)$"), mode: str = Query("paper", pattern="^(paper|live)$"),
              limit: int = Query(200, le=1000), user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(Position).where(Position.mode == mode)
    if status == "open":
        q = q.where(Position.status.in_(("open", "pending")))
    elif status == "closed":
        q = q.where(Position.status == "closed")
    return [pos_dict(p) for p in db.execute(q.order_by(Position.id.desc()).limit(limit)).scalars()]


@router.get("/positions/{pid}")
def position_detail(pid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = db.get(Position, pid)
    if not p:
        raise HTTPException(404, "not found")
    orders = db.execute(select(Order).where(Order.position_id == pid).order_by(Order.id)).scalars().all()
    ex = db.execute(select(Execution).where(Execution.order_id.in_([o.id for o in orders])).order_by(Execution.id)).scalars().all()
    d = db.get(Decision, p.decision_id) if p.decision_id else None
    return {**pos_dict(p), "orders": [order_dict(o) for o in orders],
            "executions": [{"order_id": e.order_id, "ts": iso(e.ts), "qty": e.qty, "price": e.price, "reference_price": e.reference_price,
                            "fee": e.fee, "slippage_bps": e.slippage_bps, "slippage_cost": e.slippage_cost, "liquidity": e.liquidity,
                            "tx": e.tx_signature} for e in ex],
            "decision": decision_dict(d) if d else None}


def enqueue(db: Session, kind: str, payload: dict, user: User) -> Command:
    c = Command(kind=kind, payload=payload, requested_by=user.username)
    db.add(c)
    db.flush()
    return c


@router.post("/positions/{pid}/close")
def close_position(pid: int, request: Request, user: User = Depends(require("trader")), db: Session = Depends(get_db)):
    p = db.get(Position, pid)
    if not p or p.status not in ("open", "pending"):
        raise HTTPException(404, "no open position with that id")
    c = enqueue(db, "close_position", {"position_id": pid}, user)
    audit(db, user, "close_position", str(pid), request=request)
    return {"queued": True, "command_id": c.id}


@router.post("/positions/flatten")
def flatten(request: Request, user: User = Depends(require("trader")), db: Session = Depends(get_db)):
    c = enqueue(db, "flatten_all", {}, user)
    audit(db, user, "flatten_all", request=request)
    return {"queued": True, "command_id": c.id}


@router.get("/commands/{cid}")
def command_status(cid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = db.get(Command, cid)
    if not c:
        raise HTTPException(404, "not found")
    return {"id": c.id, "kind": c.kind, "status": c.status, "result": c.result, "processed_at": iso(c.processed_at)}


@router.get("/orders")
def orders(status: str = Query("open", pattern="^(open|all)$"), mode: str = Query("paper", pattern="^(paper|live)$"),
           limit: int = Query(200, le=1000), user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(Order).where(Order.mode == mode)
    if status == "open":
        q = q.where(Order.status.in_(("new", "open", "partially_filled", "submitted")))
    return [order_dict(o) for o in db.execute(q.order_by(Order.id.desc()).limit(limit)).scalars()]


def _trades_query(mode, q, symbol, strategy):
    stmt = select(Position).where(Position.mode == mode, Position.status == "closed")
    if symbol:
        stmt = stmt.where(Position.symbol == symbol.upper())
    if strategy:
        stmt = stmt.where(Position.strategy == strategy)
    if q:
        like = f"%{q[:64]}%"
        stmt = stmt.where(or_(Position.symbol.ilike(like), Position.strategy.ilike(like), Position.entry_reason.ilike(like),
                              Position.exit_reason.ilike(like)))
    return stmt.order_by(Position.closed_at.desc())


@router.get("/trades")
def trades(mode: str = Query("paper", pattern="^(paper|live)$"), q: str | None = None, symbol: str | None = None,
           strategy: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500),
           user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = _trades_query(mode, q, symbol, strategy)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).scalars().all()
    return {"total": total, "page": page, "page_size": page_size, "rows": [pos_dict(p) for p in rows],
            "label": "Paper trading" if mode == "paper" else "Live trading"}


@router.get("/trades/export.csv")
def export_trades(mode: str = Query("paper", pattern="^(paper|live)$"), q: str | None = None, symbol: str | None = None,
                  strategy: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.execute(_trades_query(mode, q, symbol, strategy)).scalars().all()
    buf = io.StringIO()
    cols = ["id", "mode", "symbol", "strategy", "opened_at", "closed_at", "duration_s", "initial_qty", "entry_price", "exit_price",
            "initial_stop", "tp1", "tp2", "fees", "slippage", "gross_pnl", "net_pnl", "r_multiple", "entry_reason", "exit_reason"]
    w = csv.writer(buf)
    w.writerow(cols)
    for p in rows:
        d = pos_dict(p)
        # neutralise spreadsheet formula injection
        w.writerow([("'" + str(d[c])) if isinstance(d[c], str) and d[c][:1] in "=+-@" else d[c] for c in cols])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="atlas-{mode}-trades.csv"'})


@router.get("/activity")
def activity(limit: int = Query(100, le=500), kind: str | None = None, symbol: str | None = None, before_id: int | None = None,
             user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(ActivityEvent)
    if kind:
        q = q.where(ActivityEvent.kind == kind)
    if symbol:
        q = q.where(ActivityEvent.symbol == symbol.upper())
    if before_id:
        q = q.where(ActivityEvent.id < before_id)
    return [{"id": e.id, "ts": iso(e.ts), "kind": e.kind, "symbol": e.symbol, "message": e.message, "explanation": e.explanation,
             "data": e.data} for e in db.execute(q.order_by(ActivityEvent.id.desc()).limit(limit)).scalars()]


def decision_dict(d: Decision) -> dict:
    return {"id": d.id, "ts": iso(d.ts), "symbol": d.symbol, "strategy": d.strategy, "classification": d.classification,
            "confidence": d.confidence, "score_breakdown": d.score_breakdown, "risk_flags": d.risk_flags, "explanation": d.explanation,
            "ai_commentary": d.ai_commentary, "executed": d.executed, "rejected_reason": d.rejected_reason, "position_id": d.position_id,
            "outcome": d.outcome, "outcome_r": d.outcome_r}


@router.get("/decisions")
def decisions(limit: int = Query(100, le=500), symbol: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(Decision)
    if symbol:
        q = q.where(Decision.symbol == symbol.upper())
    return [decision_dict(d) for d in db.execute(q.order_by(Decision.id.desc()).limit(limit)).scalars()]


@router.get("/decisions/calibration")
def get_calibration(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"buckets": calibration(db), "note": "Confidence is a setup-quality score, not a probability of profit. "
            "These are measured outcomes of executed paper/live decisions."}


@router.get("/signals")
def signals(limit: int = Query(100, le=500), symbol: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(Signal)
    if symbol:
        q = q.where(Signal.symbol == symbol.upper())
    return [{"id": s.id, "ts": iso(s.ts), "symbol": s.symbol, "timeframe": s.timeframe, "strategy": s.strategy, "direction": s.direction,
             "entry": s.entry, "stop": s.stop, "targets": s.targets, "strength": s.strength, "reasons": s.reasons, "features": s.features}
            for s in db.execute(q.order_by(Signal.id.desc()).limit(limit)).scalars()]


# ------------------------------------------------------------------ risk & control
@router.get("/risk/status")
def risk_status(mode: str = Query("paper", pattern="^(paper|live)$"), user: User = Depends(current_user), db: Session = Depends(get_db)):
    cfg = load_config(db)
    acct = get_account(db, mode, cfg.paper_starting_capital)
    ctx = risk_context(db, acct, prices(db))
    g = gate_status(cfg, ctx)
    return {"approved": g.approved, "halt": g.halt, "checks": g.checks, "limits": cfg.risk.model_dump(),
            "context": {"equity": ctx.equity, "cash": ctx.cash, "day_pnl_pct": round(ctx.day_pnl_pct, 4), "week_pnl_pct": round(ctx.week_pnl_pct, 4),
                        "open_positions": len(ctx.open_positions), "trades_today": ctx.trades_today, "consecutive_losses": ctx.consecutive_losses,
                        "exposure": ctx.exposure},
            "hard_limits": {"max_risk_per_trade_pct": HARD_MAX_RISK_PER_TRADE_PCT, "max_daily_loss_pct": HARD_MAX_DAILY_LOSS_PCT,
                            "max_weekly_loss_pct": HARD_MAX_WEEKLY_LOSS_PCT, "max_open_positions": HARD_MAX_OPEN_POSITIONS, "min_rr": HARD_MIN_RR}}


@router.get("/risk/events")
def risk_events(limit: int = Query(100, le=500), user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [{"id": e.id, "ts": iso(e.ts), "kind": e.kind, "severity": e.severity, "message": e.message, "data": e.data}
            for e in db.execute(select(RiskEvent).order_by(RiskEvent.id.desc()).limit(limit)).scalars()]


@router.get("/settings")
def get_settings_api(user: User = Depends(current_user), db: Session = Depends(get_db)):
    cfg = load_config(db)
    return {"config": cfg.model_dump(), "strategies": list(STRATEGIES), "timeframes": SUPPORTED_TIMEFRAMES,
            "live_preflight": preflight(cfg), "live_confirm_phrase": LIVE_CONFIRM_PHRASE}


@router.put("/settings")
def put_settings(body: dict, request: Request, user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    old = load_config(db)
    merged = {**old.model_dump(), **body}
    # these switches have dedicated, audited endpoints
    for k in ("mode", "kill_switch", "live_confirmed", "trading_enabled"):
        merged[k] = getattr(old, k)
    try:
        cfg = TradingConfig.model_validate(merged)
    except ValidationError as e:
        raise HTTPException(422, e.errors(include_url=False, include_context=False))
    save_config(db, cfg, user.username)
    audit(db, user, "settings_updated", details={"changed": sorted(k for k in body if body[k] != old.model_dump().get(k))}, request=request)
    return {"config": cfg.model_dump()}


class Toggle(BaseModel):
    enabled: bool


def _mutate(db, user, request, action, fn):
    cfg = load_config(db)
    fn(cfg)
    cfg = TradingConfig.model_validate(cfg.model_dump())
    save_config(db, cfg, user.username)
    audit(db, user, action, request=request)
    return cfg


class KillBody(BaseModel):
    engage: bool
    action: str = Field("keep_protective", pattern="^(keep_protective|flatten)$")


@router.post("/control/kill-switch")
def kill_switch(body: KillBody, request: Request, user: User = Depends(require("trader")), db: Session = Depends(get_db)):
    if not body.engage and ROLES[user.role] < ROLES["admin"]:
        raise HTTPException(403, "only an admin can release the kill switch")

    def f(c: TradingConfig):
        c.kill_switch = body.engage
        if body.engage:
            c.kill_switch_action = body.action
            c.automation.auto_paper_trading = False

    cfg = _mutate(db, user, request, "kill_switch_engaged" if body.engage else "kill_switch_released", f)
    db.add(RiskEvent(kind="kill_switch", severity="critical" if body.engage else "info",
                     message=f"Kill switch {'ENGAGED' if body.engage else 'released'} by {user.username}"
                     + (f" (action: {body.action})" if body.engage else ""), data={}))
    db.add(ActivityEvent(kind="risk", message=f"Emergency kill switch {'ENGAGED' if body.engage else 'released'} by {user.username}",
                         explanation=("No new orders will be placed. " + ("All positions will be closed at market." if body.action == "flatten"
                                      else "Existing positions keep their protective stops/targets and remain monitored.")) if body.engage else
                         "Automatic paper trading stays OFF until re-enabled explicitly.", data={}))
    return {"kill_switch": cfg.kill_switch, "action": cfg.kill_switch_action}


@router.post("/control/trading")
def trading_toggle(body: Toggle, request: Request, user: User = Depends(require("trader")), db: Session = Depends(get_db)):
    if body.enabled and ROLES[user.role] < ROLES["admin"]:
        raise HTTPException(403, "only an admin can re-enable trading")
    cfg = _mutate(db, user, request, f"trading_{'enabled' if body.enabled else 'disabled'}", lambda c: setattr(c, "trading_enabled", body.enabled))
    return {"trading_enabled": cfg.trading_enabled}


@router.post("/control/scanning")
def scanning_toggle(body: Toggle, request: Request, user: User = Depends(require("trader")), db: Session = Depends(get_db)):
    cfg = _mutate(db, user, request, f"scanning_{body.enabled}", lambda c: setattr(c.automation, "scanning_enabled", body.enabled))
    return {"scanning_enabled": cfg.automation.scanning_enabled}


@router.post("/control/auto-paper")
def auto_paper(body: Toggle, request: Request, user: User = Depends(require("trader")), db: Session = Depends(get_db)):
    cur = load_config(db)
    if body.enabled and cur.kill_switch:
        raise HTTPException(409, "release the kill switch first")
    cfg = _mutate(db, user, request, f"auto_paper_{body.enabled}", lambda c: setattr(c.automation, "auto_paper_trading", body.enabled))
    return {"auto_paper_trading": cfg.automation.auto_paper_trading}


class ResetBody(BaseModel):
    capital: float = Field(gt=100, le=1e8)


@router.post("/control/reset-paper")
def reset_paper(body: ResetBody, request: Request, user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    c = enqueue(db, "reset_paper", {"capital": body.capital}, user)
    audit(db, user, "reset_paper", details={"capital": body.capital}, request=request)
    return {"queued": True, "command_id": c.id}


class ArmBody(BaseModel):
    confirm: str


@router.post("/control/live/arm")
def arm_live(body: ArmBody, request: Request, user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    if body.confirm.strip() != LIVE_CONFIRM_PHRASE:
        raise HTTPException(400, f"type exactly: {LIVE_CONFIRM_PHRASE}")
    if not get_settings().live_trading_allowed:
        raise HTTPException(409, "server operator has not allowed live trading (ATLAS_LIVE_TRADING_ALLOWED=false)")
    cfg = load_config(db)
    if [p for p in preflight(TradingConfig.model_validate({**cfg.model_dump(), "mode": "live", "live_confirmed": True}))]:
        raise HTTPException(409, "live preflight failed: " + "; ".join(preflight(TradingConfig.model_validate({**cfg.model_dump(), "mode": "live", "live_confirmed": True}))))
    cfg = _mutate(db, user, request, "live_armed", lambda c: (setattr(c, "mode", "live"), setattr(c, "live_confirmed", True)))
    db.add(RiskEvent(kind="live_armed", severity="critical", message=f"LIVE trading armed by {user.username}", data={}))
    return {"mode": cfg.mode}


@router.post("/control/live/disarm")
def disarm_live(request: Request, user: User = Depends(require("trader")), db: Session = Depends(get_db)):
    cfg = _mutate(db, user, request, "live_disarmed", lambda c: (setattr(c, "mode", "paper"), setattr(c, "live_confirmed", False)))
    return {"mode": cfg.mode}


# ------------------------------------------------------------------ strategies
@router.get("/strategies")
def strategies(user: User = Depends(current_user), db: Session = Depends(get_db)):
    cfg = load_config(db)
    rows = {r.name: r for r in db.execute(select(StrategyConfig)).scalars()}
    return [{"name": n, "label": cls.label, "doc": (cls.__doc__ or "").strip(), "enabled": n in cfg.enabled_strategies,
             "params": {**cls.default_params, **(rows[n].params if n in rows else {})}, "defaults": cls.default_params,
             "grid": cls.param_grid} for n, cls in STRATEGIES.items()] + [
        {"name": "solana_new_token", "label": "Solana New Token Scanner", "enabled": cfg.automation.token_scanner_enabled,
         "doc": "Informational safety scanner for newly launched Solana tokens. Never trades automatically.", "params": {}, "defaults": {}, "grid": {}}]


class StrategyBody(BaseModel):
    params: dict[str, float]


@router.put("/strategies/{name}")
def put_strategy(name: str, body: StrategyBody, request: Request, user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    if name not in STRATEGIES:
        raise HTTPException(404, "unknown strategy")
    defaults = STRATEGIES[name].default_params
    bad = [k for k in body.params if k not in defaults]
    if bad:
        raise HTTPException(422, f"unknown params {bad}")
    for k, v in body.params.items():
        d = defaults[k]
        if not (abs(d) * 0.25 <= abs(v) <= abs(d) * 4) or (d > 0) != (v > 0):
            raise HTTPException(422, f"{k}={v} outside allowed range around default {d}")
    row = db.get(StrategyConfig, name) or StrategyConfig(name=name, params={})
    row.params = {**(row.params or {}), **body.params}
    db.merge(row)
    audit(db, user, "strategy_params", name, body.params, request)
    return {"ok": True}


# ------------------------------------------------------------------ analytics / tokens / system
@router.get("/analytics")
def get_analytics(mode: str = Query("paper", pattern="^(paper|live)$"), user: User = Depends(current_user), db: Session = Depends(get_db)):
    cfg = load_config(db)
    a = analytics(db, get_account(db, mode, cfg.paper_starting_capital))
    a["label"] = "PAPER TRADING results — simulated execution on live data" if mode == "paper" else "LIVE TRADING results"
    return a


@router.get("/tokens")
def tokens(limit: int = Query(50, le=200), user: User = Depends(current_user), db: Session = Depends(get_db)):
    sub = select(TokenScan.mint, func.max(TokenScan.id).label("mid")).group_by(TokenScan.mint).subquery()
    rows = db.execute(select(TokenScan).join(sub, TokenScan.id == sub.c.mid).order_by(TokenScan.id.desc()).limit(limit)).scalars().all()
    return [{"id": t.id, "ts": iso(t.ts), "mint": t.mint, "symbol": t.symbol, "name": t.name, "dex": t.dex, "pair_address": t.pair_address,
             "price_usd": t.price_usd, "liquidity_usd": t.liquidity_usd, "volume_24h": t.volume_24h, "market_cap": t.market_cap, "fdv": t.fdv,
             "pair_created_at": iso(t.pair_created_at), "top10_holder_pct": t.top10_holder_pct, "mint_authority": t.mint_authority,
             "freeze_authority": t.freeze_authority, "risk_score": t.risk_score, "risk_level": t.risk_level, "flags": t.flags,
             "checks": t.checks, "tradeable": False} for t in rows]


@router.post("/tokens/scan")
def token_scan(request: Request, user: User = Depends(require("trader")), db: Session = Depends(get_db)):
    c = enqueue(db, "scan_tokens", {}, user)
    return {"queued": True, "command_id": c.id}


@router.get("/integrations")
def integrations(user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = get_settings()
    rows = {r.name: r for r in db.execute(select(IntegrationStatus)).scalars()}
    desc = {
        "binance_rest": ("Binance spot market data (data-api.binance.vision)", "Candles, top-of-book, depth, 24h stats — primary venue"),
        "coinbase_rest": ("Coinbase Exchange REST", "Fallback / reference prices"),
        "kraken_rest": ("Kraken REST", "Fallback / reference prices"),
        "coinbase_ws": ("Coinbase Exchange WebSocket", "Real-time reference ticks, cross-venue validation"),
        "kraken_ws": ("Kraken WebSocket v2", "Real-time reference ticks, cross-venue validation"),
        "dexscreener": ("DexScreener", "Solana token discovery, pair liquidity/volume, market cap"),
        "jupiter": ("Jupiter (lite-api.jup.ag)", "Sell-route/honeypot probe; live swap routing"),
        "solana_rpc": ("Solana RPC", "Mint/freeze authority, holder concentration; live tx simulation/confirmation"),
        "anthropic": ("Claude API (optional)", "Natural-language commentary on decisions; never affects execution"),
    }
    out = []
    for name, (label, purpose) in desc.items():
        r = rows.get(name)
        out.append({"name": name, "label": label, "purpose": purpose, "status": r.status if r else "unknown",
                    "last_ok": iso(r.last_ok) if r else None, "last_error": r.last_error if r else None,
                    "latency_ms": r.latency_ms if r else None, "requires_credentials": name == "anthropic",
                    "configured": bool(s.anthropic_api_key) if name == "anthropic" else True})
    out.append({"name": "live_execution", "label": "Live execution (Solana / Jupiter)", "purpose": "Real-funds swaps — disabled by default",
                "status": "disabled" if not s.live_trading_allowed else ("armed" if not preflight(load_config(db)) else "not armed"),
                "requires_credentials": True, "configured": bool(s.solana_keypair_path), "last_error": None, "last_ok": None, "latency_ms": None})
    return out


@router.get("/audit")
def audit_log(limit: int = Query(200, le=1000), user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    return [{"id": a.id, "ts": iso(a.ts), "username": a.username, "action": a.action, "target": a.target, "details": a.details, "ip": a.ip}
            for a in db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)).scalars()]
