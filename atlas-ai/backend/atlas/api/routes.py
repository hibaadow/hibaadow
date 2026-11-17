"""REST API — ATLAS AI gold & forex."""
from __future__ import annotations

import csv
import io
import time
from datetime import datetime, timedelta, timezone

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from .. import indicators as ind
from ..config import get_settings
from ..db import get_db
from ..decision import calibration
from ..econ import CURRENCIES
from ..instruments import FOREX, GOLD, INSTRUMENTS, is_supported, normalize
from ..marketdata.types import TF_MS
from ..marketdata.types import Candle as C
from ..marketdata.types import resample_candles
from ..marketdata.validation import validate_candles
from ..models import (ActivityEvent, AppSetting, AuditLog, Candle, Command, Decision, Execution, IntegrationStatus, Order, Position, RiskEvent,
                      Signal, StrategyConfig, User)
from ..portfolio import analytics, get_account, overview, quotes_from_snapshot, risk_context
from ..risk import gate_status
from ..security import COOKIE, ROLES, audit, client_ip, current_user, hash_password, issue_token, limiter, login, require
from ..strategies.library import STRATEGIES
from ..trading_config import (HARD_MAX_DAILY_LOSS_PCT, HARD_MAX_LEVERAGE, HARD_MAX_OPEN_POSITIONS, HARD_MAX_RISK_PER_TRADE_PCT,
                              HARD_MAX_WEEKLY_LOSS_PCT, HARD_MIN_RR, SUPPORTED_TIMEFRAMES, TradingConfig, load_config, save_config)

router = APIRouter(prefix="/api")
LIVE_CONFIRM_PHRASE = "I understand live trading uses real money"
MODE_RE = "^(paper|demo|live)$"


def setting(db: Session, key: str, default=None):
    row = db.get(AppSetting, key)
    return row.value if row else default


def quotes(db: Session):
    return quotes_from_snapshot(setting(db, "market_quotes"))


def iso(dt):
    return dt.isoformat() if dt else None


def symbol_or_404(symbol: str) -> str:
    if not is_supported(symbol):
        raise HTTPException(404, "ATLAS AI trades XAU/USD and selected forex pairs only")
    return normalize(symbol)


def pos_dict(p: Position, qs=None) -> dict:
    inst = INSTRUMENTS.get(p.symbol)
    dur = None
    if p.opened_at:
        dur = ((p.closed_at or datetime.now(timezone.utc)) - p.opened_at).total_seconds()
    sg = 1 if p.side == "buy" else -1
    r = (p.entry_price - p.initial_stop) * sg if p.entry_price else None
    unreal = None
    if qs is not None and p.status == "open" and p.symbol in qs and inst:
        from ..execution.paper import unrealized_usd
        unreal = unrealized_usd(p, qs[p.symbol], {s: q.mid for s, q in qs.items()})
    return {"id": p.id, "mode": p.mode, "symbol": p.symbol, "display": inst.display if inst else p.symbol, "asset_class": inst.asset_class if inst else None,
            "digits": inst.digits if inst else 5, "strategy": p.strategy, "side": p.side, "status": p.status, "broker_id": p.broker_id,
            "opened_at": iso(p.opened_at), "closed_at": iso(p.closed_at), "created_at": iso(p.created_at), "lots": p.qty, "initial_lots": p.initial_qty,
            "entry_price": p.entry_price, "exit_price": p.exit_price, "stop_price": p.stop_price, "initial_stop": p.initial_stop, "tp1": p.tp1,
            "tp2": p.tp2, "tp1_hit": p.tp1_hit, "risk_amount": p.risk_amount, "commission": p.commission, "swap": p.swap, "fees": p.fees_paid,
            "slippage": p.slippage_cost, "gross_pnl": p.gross_pnl, "net_pnl": p.net_pnl, "pip_value_usd": p.pip_value_usd,
            "stop_pips": round(inst.to_pips(abs(p.entry_price - p.initial_stop)), 1) if inst and p.entry_price else None,
            "r_multiple": round(p.net_pnl / p.risk_amount, 3) if p.status == "closed" and p.risk_amount else None,
            "rr": round((p.tp1 - p.entry_price) * sg / r, 2) if r and r > 0 else None, "last_price": p.last_price, "unrealized_pnl": unreal,
            "entry_reason": p.entry_reason, "exit_reason": p.exit_reason, "duration_s": dur, "decision_id": p.decision_id, "stop_history": p.stop_history}


def order_dict(o: Order) -> dict:
    return {"id": o.id, "client_order_id": o.client_order_id, "mode": o.mode, "position_id": o.position_id, "symbol": o.symbol,
            "display": INSTRUMENTS[o.symbol].display if o.symbol in INSTRUMENTS else o.symbol, "side": o.side, "type": o.type, "purpose": o.purpose,
            "lots": o.qty, "filled_lots": o.filled_qty, "limit_price": o.limit_price, "stop_price": o.stop_price, "avg_fill_price": o.avg_fill_price,
            "status": o.status, "fees": o.fees, "reason": o.reason, "venue": o.venue, "broker_order_id": o.external_id, "created_at": iso(o.created_at)}


def decision_dict(d: Decision) -> dict:
    inst = INSTRUMENTS.get(d.symbol)
    return {"id": d.id, "ts": iso(d.ts), "symbol": d.symbol, "display": inst.display if inst else d.symbol, "asset_class": inst.asset_class if inst else None,
            "digits": inst.digits if inst else 5, "strategy": d.strategy, "strategy_label": STRATEGIES[d.strategy].label if d.strategy in STRATEGIES else d.strategy,
            "timeframe": d.timeframe, "direction": d.direction, "classification": d.classification, "confidence": d.confidence, "entry": d.entry,
            "stop_loss": d.stop_loss, "take_profit": d.take_profit, "take_profit_2": d.take_profit_2, "risk_reward": d.risk_reward, "lots": d.lots,
            "risk_amount": d.risk_amount, "est_costs": d.est_costs, "evidence": d.evidence, "events": d.events, "invalidation": d.invalidation,
            "score_breakdown": d.score_breakdown, "risk_flags": d.risk_flags, "explanation": d.explanation, "ai_commentary": d.ai_commentary,
            "executed": d.executed, "rejected_reason": d.rejected_reason, "position_id": d.position_id, "outcome": d.outcome, "outcome_r": d.outcome_r}


@router.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("select 1"))
    hb = setting(db, "agent_heartbeat")
    age = time.time() - hb["ts"] if hb else None
    return {"status": "ok", "database": "ok", "worker": "ok" if age is not None and age < 45 else "down",
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
# ------------------------------------------------------------------ dashboard
@router.get("/overview")
def get_overview(mode: str | None = Query(None, pattern=MODE_RE), user: User = Depends(current_user), db: Session = Depends(get_db)):
    cfg = load_config(db)
    mode = mode or cfg.mode
    acct = get_account(db, mode, cfg.paper_starting_capital)
    qs = quotes(db)
    broker_acct = setting(db, "broker_account") if mode != "paper" else None
    ov = overview(db, acct, qs, broker_acct)
    ctx = risk_context(db, acct, qs, broker_account=broker_acct, leverage=cfg.paper_leverage)
    g = gate_status(cfg, ctx)
    hb = setting(db, "agent_heartbeat")
    label = {"paper": "PAPER TRADING — simulated fills on live gold/forex quotes", "demo": "DEMO ACCOUNT — broker demo (no real money)",
             "live": "LIVE ACCOUNT — real money"}[mode]
    return {**ov, "gates": g.checks, "trading_allowed": g.approved, "halt": g.halt, "currency_risk": ctx.currency_risk(),
            "agent": {**(hb or {}), "alive": bool(hb and time.time() - hb["ts"] < 45)},
            "config": {"mode": cfg.mode, "kill_switch": cfg.kill_switch, "trading_enabled": cfg.trading_enabled, "scanning": cfg.automation.scanning_enabled,
                       "auto_trading": cfg.automation.auto_trading, "risk_per_trade_pct": cfg.risk.risk_per_trade_pct, "data_source": get_settings().data_source},
            "results_label": label}


@router.get("/markets")
def markets(user: User = Depends(current_user), db: Session = Depends(get_db)):
    snap = setting(db, "analysis_snapshot") or {"rows": [], "ts": None, "strength": {}}
    qs = quotes(db)
    rows = []
    for r in snap.get("rows", []):
        q = qs.get(r["symbol"])
        if q:
            r = {**r, "bid": q.bid, "ask": q.ask, "mid": q.mid, "spread_pips": round(INSTRUMENTS[r["symbol"]].to_pips(q.ask - q.bid), 2)}
        rows.append(r)
    return {"ts": snap.get("ts"), "source": snap.get("source"), "strength": snap.get("strength", {}), "us10y": snap.get("us10y"),
            "gold": [r for r in rows if r["asset_class"] == "gold"], "forex": [r for r in rows if r["asset_class"] == "forex"]}


@router.get("/macro")
def macro(user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = setting(db, "macro_snapshot") or {}
    return {"strength": m.get("strength", {}), "us10y": m.get("us10y"), "ts": m.get("ts"),
            "note": "Currency strength is derived from ATLAS's tracked FX pairs (average 24h % change vs the other currencies). US10Y: FRED DGS10 (daily)."}


@router.get("/calendar")
def calendar(currency: str | None = None, impact: str | None = Query(None, pattern="^(High|Medium|Low)$"), days: int = Query(7, ge=1, le=14),
             user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = setting(db, "macro_snapshot") or {}
    order = {"Low": 0, "Medium": 1, "High": 2}
    now = datetime.now(timezone.utc)
    rows = []
    for e in m.get("events", []):
        t = datetime.fromisoformat(e["time"])
        if t < now - timedelta(days=days) or t > now + timedelta(days=days):
            continue
        if currency and e["currency"] != currency.upper():
            continue
        if impact and order.get(e["impact"], -1) < order[impact]:
            continue
        affects = [s for s, i in INSTRUMENTS.items() if e["currency"] in ((i.base, i.quote) if i.asset_class == "forex" else ("USD",))]
        rows.append({**e, "affects": affects})
    return {"events": rows, "fetched": m.get("events_fetched"), "source": "ForexFactory weekly calendar export (times converted to UTC)",
            "blackout": load_config(db).news.model_dump()}


@router.get("/market/{symbol}/candles")
async def candles(request: Request, symbol: str, tf: str = Query("5m"), limit: int = Query(300, ge=50, le=1000),
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
    sym = symbol_or_404(symbol)
    if tf not in SUPPORTED_TIMEFRAMES:
        raise HTTPException(400, "invalid timeframe")
    inst = INSTRUMENTS[sym]
    s = get_settings()
    cs: list[C] = []
    src = s.data_source
    if src in ("oanda", "mt5", "metaapi") and getattr(request.app.state, "history", None) is not None:
        try:
            cs = await request.app.state.history.candles(sym, tf, limit)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, f"broker data unavailable: {str(e)[:120]}")
    else:
        base_tf = "1m"
        need = limit * TF_MS[tf] // TF_MS[base_tf] + TF_MS[tf] // 60_000
        rows = db.execute(select(Candle).where(Candle.venue == "public", Candle.symbol == sym, Candle.timeframe == base_tf)
                          .order_by(Candle.open_time.desc()).limit(min(need, 60_000))).scalars().all()
        base = [C(r.open_time, r.open, r.high, r.low, r.close, r.volume, 0.0, r.spread or 0.0) for r in reversed(rows)]
        cs = base if tf == "1m" else resample_candles(base, tf)
        src = "public quotes (sampled bars)"
    clean, report = validate_candles(cs[-limit:], tf, drop_open=False, asset_class=inst.asset_class)
    c = np.array([x.close for x in clean])
    h = np.array([x.high for x in clean])
    l_ = np.array([x.low for x in clean])
    v = np.array([x.volume for x in clean])
    t = np.array([x.open_time for x in clean], dtype=np.int64)

    def series(a):
        return [None if (x != x) else round(float(x), 8) for x in a]

    vw, _ = ind.vwap(h, l_, c, v, t) if len(c) else (c, c)
    return {"symbol": sym, "display": inst.display, "digits": inst.digits, "timeframe": tf, "source": src,
            "quality": {k: report[k] for k in ("invalid", "duplicates", "missing_bars", "issues")},
            "candles": [{"t": x.open_time // 1000, "o": x.open, "h": x.high, "l": x.low, "c": x.close, "v": x.volume} for x in clean],
            "indicators": {"ema9": series(ind.ema(c, 9)), "ema21": series(ind.ema(c, 21)), "ema50": series(ind.ema(c, 50)),
                           "ema200": series(ind.ema(c, 200)), "vwap": series(vw), "rsi": series(ind.rsi(c, 14))}}


@router.get("/gold")
def gold_workspace(user: User = Depends(current_user), db: Session = Depends(get_db)):
    snap = setting(db, "analysis_snapshot") or {}
    m = setting(db, "macro_snapshot") or {}
    row = next((r for r in snap.get("rows", []) if r["symbol"] == GOLD), None)
    now = datetime.now(timezone.utc)
    usd_events = [e for e in m.get("events", []) if e["currency"] == "USD" and e["impact"] in ("High", "Medium")
                  and now - timedelta(hours=2) <= datetime.fromisoformat(e["time"]) <= now + timedelta(days=3)]
    decs = db.execute(select(Decision).where(Decision.symbol == GOLD).order_by(Decision.id.desc()).limit(10)).scalars().all()
    from ..sessions import session_info
    s = session_info(now, ("XAU", "USD"), "gold")
    return {"row": row, "usd_strength": (m.get("strength") or {}).get("USD"), "strength": m.get("strength", {}), "us10y": m.get("us10y"),
            "usd_events": usd_events, "decisions": [decision_dict(d) for d in decs],
            "session": {"active": s.active, "label": s.label, "overlap": s.overlap_london_ny, "market_open": s.market_open, "rollover": s.rollover},
            "spec": {"contract_size": INSTRUMENTS[GOLD].contract_size, "pip_size": INSTRUMENTS[GOLD].pip_size, "digits": INSTRUMENTS[GOLD].digits,
                     "min_lot": INSTRUMENTS[GOLD].min_lot, "pip_value_usd_per_lot": INSTRUMENTS[GOLD].pip_value_quote,
                     "margin_rate": INSTRUMENTS[GOLD].margin_rate}}


@router.get("/instruments")
def instruments(user: User = Depends(current_user)):
    return [{"symbol": i.symbol, "display": i.display, "asset_class": i.asset_class, "category": i.category, "pip_size": i.pip_size, "digits": i.digits,
             "contract_size": i.contract_size, "min_lot": i.min_lot, "lot_step": i.lot_step, "max_lot": i.max_lot, "margin_rate": round(i.margin_rate, 5),
             "leverage": round(1 / i.margin_rate), "default_max_spread_pips": i.max_spread_pips, "oanda": i.oanda} for i in INSTRUMENTS.values()]


@router.get("/positions")
def positions(status: str = Query("open", pattern="^(open|closed|all)$"), mode: str | None = Query(None, pattern=MODE_RE),
              limit: int = Query(200, le=1000), user: User = Depends(current_user), db: Session = Depends(get_db)):
    mode = mode or load_config(db).mode
    q = select(Position).where(Position.mode == mode)
    if status == "open":
        q = q.where(Position.status.in_(("open", "pending")))
    elif status == "closed":
        q = q.where(Position.status == "closed")
    qs = quotes(db)
    return [pos_dict(p, qs) for p in db.execute(q.order_by(Position.id.desc()).limit(limit)).scalars()]


@router.get("/positions/{pid}")
def position_detail(pid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = db.get(Position, pid)
    if not p:
        raise HTTPException(404, "not found")
    orders = db.execute(select(Order).where(Order.position_id == pid).order_by(Order.id)).scalars().all()
    ex = db.execute(select(Execution).where(Execution.order_id.in_([o.id for o in orders])).order_by(Execution.id)).scalars().all()
    d = db.get(Decision, p.decision_id) if p.decision_id else None
    return {**pos_dict(p, quotes(db)), "orders": [order_dict(o) for o in orders],
            "executions": [{"order_id": e.order_id, "ts": iso(e.ts), "lots": e.qty, "price": e.price, "reference_price": e.reference_price,
                            "commission": e.fee, "slippage_pips": e.slippage_bps, "slippage_usd": e.slippage_cost, "liquidity": e.liquidity,
                            "broker_ref": e.tx_signature} for e in ex],
            "decision": decision_dict(d) if d else None}


def enqueue(db: Session, kind: str, payload: dict, user: User) -> Command:
    c = Command(kind=kind, payload=payload, requested_by=user.username)
    db.add(c)
    db.flush()
    return c


@router.post("/positions/{pid}/close")
def close_position(pid: int, request: Request, user: User = Depends(require("trader")), db: Session = Depends(get_db)):
    p = db.get(Position, pid)
    if not p or p.status != "open":
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
def orders(status: str = Query("open", pattern="^(open|all)$"), mode: str | None = Query(None, pattern=MODE_RE),
           limit: int = Query(200, le=1000), user: User = Depends(current_user), db: Session = Depends(get_db)):
    mode = mode or load_config(db).mode
    q = select(Order).where(Order.mode == mode)
    if status == "open":
        q = q.where(Order.status.in_(("new", "open", "submitted")))
    return [order_dict(o) for o in db.execute(q.order_by(Order.id.desc()).limit(limit)).scalars()]


def _trades_query(mode, q, symbol, strategy, asset_class=None):
    stmt = select(Position).where(Position.mode == mode, Position.status == "closed")
    if symbol:
        stmt = stmt.where(Position.symbol == normalize(symbol))
    if asset_class in ("gold", "forex"):
        stmt = stmt.where(Position.symbol.in_([GOLD] if asset_class == "gold" else FOREX))
    if strategy:
        stmt = stmt.where(Position.strategy == strategy)
    if q:
        like = f"%{q[:64]}%"
        stmt = stmt.where(or_(Position.symbol.ilike(like), Position.strategy.ilike(like), Position.entry_reason.ilike(like),
                              Position.exit_reason.ilike(like), Position.side.ilike(like)))
    return stmt.order_by(Position.closed_at.desc())


@router.get("/trades")
def trades(mode: str | None = Query(None, pattern=MODE_RE), q: str | None = None, symbol: str | None = None, strategy: str | None = None,
           asset_class: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500),
           user: User = Depends(current_user), db: Session = Depends(get_db)):
    mode = mode or load_config(db).mode
    stmt = _trades_query(mode, q, symbol, strategy, asset_class)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).scalars().all()
    return {"total": total, "page": page, "page_size": page_size, "rows": [pos_dict(p) for p in rows], "mode": mode}


@router.get("/trades/export.csv")
def export_trades(mode: str | None = Query(None, pattern=MODE_RE), q: str | None = None, symbol: str | None = None, strategy: str | None = None,
                  asset_class: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    mode = mode or load_config(db).mode
    rows = db.execute(_trades_query(mode, q, symbol, strategy, asset_class)).scalars().all()
    buf = io.StringIO()
    cols = ["id", "mode", "symbol", "side", "strategy", "opened_at", "closed_at", "duration_s", "initial_lots", "entry_price", "exit_price",
            "initial_stop", "stop_pips", "tp1", "tp2", "commission", "swap", "slippage", "gross_pnl", "net_pnl", "r_multiple", "entry_reason", "exit_reason"]
    w = csv.writer(buf)
    w.writerow(cols)
    for p in rows:
        d = pos_dict(p)
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
        q = q.where(ActivityEvent.symbol == normalize(symbol))
    if before_id:
        q = q.where(ActivityEvent.id < before_id)
    return [{"id": e.id, "ts": iso(e.ts), "kind": e.kind, "symbol": e.symbol, "message": e.message, "explanation": e.explanation, "data": e.data}
            for e in db.execute(q.order_by(ActivityEvent.id.desc()).limit(limit)).scalars()]


@router.get("/analyst/proposals")
def proposals(limit: int = Query(100, le=500), symbol: str | None = None, asset_class: str | None = None, status: str | None = Query(None, pattern="^(executed|rejected)$"),
              user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(Decision)
    if symbol:
        q = q.where(Decision.symbol == normalize(symbol))
    if asset_class in ("gold", "forex"):
        q = q.where(Decision.symbol.in_([GOLD] if asset_class == "gold" else FOREX))
    if status == "executed":
        q = q.where(Decision.executed.is_(True))
    elif status == "rejected":
        q = q.where(Decision.executed.is_(False))
    return [decision_dict(d) for d in db.execute(q.order_by(Decision.id.desc()).limit(limit)).scalars()]


@router.get("/analyst/calibration")
def get_calibration(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"buckets": calibration(db), "note": "Confidence is a setup-quality score, not a probability of profit. These are measured outcomes."}


# ------------------------------------------------------------------ risk & control
@router.get("/risk/status")
def risk_status(mode: str | None = Query(None, pattern=MODE_RE), user: User = Depends(current_user), db: Session = Depends(get_db)):
    cfg = load_config(db)
    mode = mode or cfg.mode
    acct = get_account(db, mode, cfg.paper_starting_capital)
    ctx = risk_context(db, acct, quotes(db), broker_account=setting(db, "broker_account") if mode != "paper" else None, leverage=cfg.paper_leverage)
    g = gate_status(cfg, ctx)
    return {"approved": g.approved, "halt": g.halt, "checks": g.checks, "limits": cfg.risk.model_dump(), "news": cfg.news.model_dump(),
            "sessions": cfg.sessions.model_dump(),
            "context": {"equity": ctx.equity, "balance": ctx.balance, "margin_used": ctx.margin_used, "day_pnl_pct": round(ctx.day_pnl_pct, 4),
                        "week_pnl_pct": round(ctx.week_pnl_pct, 4), "open_positions": len(ctx.open_positions), "trades_today": ctx.trades_today,
                        "consecutive_losses": ctx.consecutive_losses, "notional": ctx.notional,
                        "effective_leverage": round(ctx.notional / ctx.equity, 3) if ctx.equity else None, "currency_risk": ctx.currency_risk()},
            "hard_limits": {"max_risk_per_trade_pct": HARD_MAX_RISK_PER_TRADE_PCT, "max_daily_loss_pct": HARD_MAX_DAILY_LOSS_PCT,
                            "max_weekly_loss_pct": HARD_MAX_WEEKLY_LOSS_PCT, "max_open_positions": HARD_MAX_OPEN_POSITIONS, "min_rr": HARD_MIN_RR,
                            "max_leverage": HARD_MAX_LEVERAGE}}


@router.get("/risk/events")
def risk_events(limit: int = Query(100, le=500), user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [{"id": e.id, "ts": iso(e.ts), "kind": e.kind, "severity": e.severity, "message": e.message, "data": e.data}
            for e in db.execute(select(RiskEvent).order_by(RiskEvent.id.desc()).limit(limit)).scalars()]


def broker_status() -> dict:
    s = get_settings()
    return {"data_source": s.data_source, "broker": s.broker, "oanda_configured": s.oanda_configured, "oanda_environment": s.oanda_environment,
            "mt5_configured": s.mt5_configured, "metaapi_configured": s.metaapi_configured, "live_trading_allowed": s.live_trading_allowed}


def mode_requirements(cfg: TradingConfig, target: str, db: Session) -> list[str]:
    s = get_settings()
    out = []
    if target == "paper":
        return out
    if s.broker == "none":
        out.append("no broker configured: set ATLAS_BROKER=metaapi (MT5 without Windows: ATLAS_METAAPI_TOKEN, ATLAS_METAAPI_ACCOUNT_ID), "
                   "ATLAS_BROKER=oanda (ATLAS_OANDA_TOKEN, ATLAS_OANDA_ACCOUNT_ID) or ATLAS_BROKER=mt5 (ATLAS_MT5_BRIDGE_URL)")
    elif s.broker == "oanda" and not s.oanda_configured:
        out.append("OANDA credentials missing")
    elif s.broker == "mt5" and not s.mt5_configured:
        out.append("MT5 bridge not configured")
    elif s.broker == "metaapi" and not s.metaapi_configured:
        out.append("MetaApi token/account id missing")
    ba = setting(db, "broker_account")
    if s.broker != "none" and not ba:
        out.append("broker account not reachable yet (check credentials / bridge)")
    elif ba and ba.get("environment") != target:
        out.append(f"connected broker account is {str(ba.get('environment')).upper()}, not {target.upper()}")
    if target == "live" and not s.live_trading_allowed:
        out.append("server operator has not allowed live trading (ATLAS_LIVE_TRADING_ALLOWED=false)")
    return out


@router.get("/settings")
def get_settings_api(user: User = Depends(current_user), db: Session = Depends(get_db)):
    cfg = load_config(db)
    return {"config": cfg.model_dump(), "strategies": list(STRATEGIES), "timeframes": SUPPORTED_TIMEFRAMES,
            "instruments": [{"symbol": s, "display": i.display, "asset_class": i.asset_class} for s, i in INSTRUMENTS.items()],
            "broker": broker_status(), "demo_requirements": mode_requirements(cfg, "demo", db), "live_requirements": mode_requirements(cfg, "live", db),
            "live_confirm_phrase": LIVE_CONFIRM_PHRASE}


@router.put("/settings")
def put_settings(body: dict, request: Request, user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    old = load_config(db)
    merged = {**old.model_dump(), **body}
    for k in ("mode", "kill_switch", "live_confirmed", "trading_enabled"):
        merged[k] = getattr(old, k)  # dedicated, audited endpoints only
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
            c.automation.auto_trading = False

    cfg = _mutate(db, user, request, "kill_switch_engaged" if body.engage else "kill_switch_released", f)
    db.add(RiskEvent(kind="kill_switch", severity="critical" if body.engage else "info",
                     message=f"Emergency stop {'ENGAGED' if body.engage else 'released'} by {user.username}" + (f" ({body.action})" if body.engage else ""), data={}))
    db.add(ActivityEvent(kind="risk", message=f"Emergency stop {'ENGAGED' if body.engage else 'released'} by {user.username}",
                         explanation=("No new orders. " + ("All positions will be closed at market." if body.action == "flatten"
                                      else "Open positions keep their stop-loss/take-profit and stay monitored.")) if body.engage else
                         "Automatic trading stays OFF until re-enabled explicitly.", data={}))
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


@router.post("/control/auto-trading")
def auto_trading(body: Toggle, request: Request, user: User = Depends(require("trader")), db: Session = Depends(get_db)):
    cur = load_config(db)
    if body.enabled and cur.kill_switch:
        raise HTTPException(409, "release the emergency stop first")
    if body.enabled and cur.mode == "live" and ROLES[user.role] < ROLES["admin"]:
        raise HTTPException(403, "only an admin can enable automatic trading on a live account")
    cfg = _mutate(db, user, request, f"auto_trading_{body.enabled}", lambda c: setattr(c.automation, "auto_trading", body.enabled))
    return {"auto_trading": cfg.automation.auto_trading, "mode": cfg.mode}


class ResetBody(BaseModel):
    capital: float = Field(gt=100, le=1e8)


@router.post("/control/reset-paper")
def reset_paper(body: ResetBody, request: Request, user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    c = enqueue(db, "reset_paper", {"capital": body.capital}, user)
    audit(db, user, "reset_paper", details={"capital": body.capital}, request=request)
    return {"queued": True, "command_id": c.id}


class ModeBody(BaseModel):
    mode: str = Field(pattern="^(paper|demo)$")


@router.post("/control/mode")
def set_mode(body: ModeBody, request: Request, user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    cfg = load_config(db)
    problems = mode_requirements(cfg, body.mode, db)
    if problems:
        raise HTTPException(409, "; ".join(problems))
    cfg = _mutate(db, user, request, f"mode_{body.mode}", lambda c: (setattr(c, "mode", body.mode), setattr(c, "live_confirmed", False),
                                                                     setattr(c.automation, "auto_trading", False)))
    return {"mode": cfg.mode}


class ArmBody(BaseModel):
    confirm: str


@router.post("/control/live/arm")
def arm_live(body: ArmBody, request: Request, user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    if body.confirm.strip() != LIVE_CONFIRM_PHRASE:
        raise HTTPException(400, f"type exactly: {LIVE_CONFIRM_PHRASE}")
    cfg = load_config(db)
    problems = mode_requirements(cfg, "live", db)
    if problems:
        raise HTTPException(409, "; ".join(problems))
    cfg = _mutate(db, user, request, "live_armed", lambda c: (setattr(c, "mode", "live"), setattr(c, "live_confirmed", True),
                                                              setattr(c.automation, "auto_trading", False)))
    db.add(RiskEvent(kind="live_armed", severity="critical", message=f"LIVE trading armed by {user.username} (automatic trading left OFF)", data={}))
    return {"mode": cfg.mode}


@router.post("/control/live/disarm")
def disarm_live(request: Request, user: User = Depends(require("trader")), db: Session = Depends(get_db)):
    cfg = _mutate(db, user, request, "live_disarmed", lambda c: (setattr(c, "mode", "paper"), setattr(c, "live_confirmed", False),
                                                                 setattr(c.automation, "auto_trading", False)))
    return {"mode": cfg.mode}


@router.post("/calendar/refresh")
def refresh_calendar(request: Request, user: User = Depends(require("trader")), db: Session = Depends(get_db)):
    return {"queued": True, "command_id": enqueue(db, "refresh_calendar", {}, user).id}


# ------------------------------------------------------------------ strategies
@router.get("/strategies")
def strategies(user: User = Depends(current_user), db: Session = Depends(get_db)):
    cfg = load_config(db)
    rows = {r.name: r for r in db.execute(select(StrategyConfig)).scalars()}
    return [{"name": n, "label": cls.label, "doc": (cls.__doc__ or "").strip(), "enabled": n in cfg.enabled_strategies,
             "instruments": list(cls.instruments) if cls.instruments else "all", "params": {**cls.default_params, **(rows[n].params if n in rows else {})},
             "defaults": cls.default_params, "grid": cls.param_grid} for n, cls in STRATEGIES.items()]


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


# ------------------------------------------------------------------ analytics / system
@router.get("/analytics")
def get_analytics(mode: str | None = Query(None, pattern=MODE_RE), user: User = Depends(current_user), db: Session = Depends(get_db)):
    cfg = load_config(db)
    mode = mode or cfg.mode
    a = analytics(db, get_account(db, mode, cfg.paper_starting_capital))
    a["label"] = {"paper": "PAPER TRADING results — simulated execution on live quotes", "demo": "DEMO ACCOUNT results (broker demo)",
                  "live": "LIVE ACCOUNT results"}[mode]
    return a


@router.get("/integrations")
def integrations(user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = get_settings()
    rows = {r.name: r for r in db.execute(select(IntegrationStatus)).scalars()}
    desc = {
        "public_quotes": ("Swissquote public quote feed", "Live XAU/USD & FX bid/ask without credentials; ATLAS builds sampled bars from it", False, True),
        "oanda": ("OANDA v20 REST", "Candles (bid/ask), live prices, demo/live execution", True, s.oanda_configured),
        "oanda_account": ("OANDA account", "Balance, equity, margin, open trades", True, s.oanda_configured),
        "metaapi": ("MetaTrader 5 via MetaApi (no Windows)", "MT5 candles, prices, demo/live execution through MetaApi's cloud terminal", True, s.metaapi_configured),
        "metaapi_account": ("MetaTrader 5 account (MetaApi)", "Balance, equity, margin, positions", True, s.metaapi_configured),
        "mt5_bridge": ("MetaTrader 5 (Windows bridge)", "Candles, ticks, demo/live execution via your own MT5 terminal", True, s.mt5_configured),
        "mt5_account": ("MetaTrader 5 account", "Balance, equity, margin, positions", True, s.mt5_configured),
        "forexfactory_calendar": ("Economic calendar (ForexFactory export)", "High-impact events & central-bank decisions; news blackout", False, True),
        "fred": ("FRED — US 10Y Treasury yield", "Daily DGS10 for gold macro context", False, True),
        "anthropic": ("Claude API (optional)", "Narrative commentary on decisions; never affects execution", True, bool(s.anthropic_api_key)),
    }
    out = []
    for name, (label, purpose, creds, configured) in desc.items():
        r = rows.get(name)
        status = r.status if r else ("unconfigured" if not configured else "unknown")
        out.append({"name": name, "label": label, "purpose": purpose, "status": status, "last_ok": iso(r.last_ok) if r else None,
                    "last_error": r.last_error if r else None, "latency_ms": r.latency_ms if r else None, "requires_credentials": creds,
                    "configured": configured})
    return {"integrations": out, "broker": broker_status()}


@router.get("/audit")
def audit_log(limit: int = Query(200, le=1000), user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    return [{"id": a.id, "ts": iso(a.ts), "username": a.username, "action": a.action, "target": a.target, "details": a.details, "ip": a.ip}
            for a in db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)).scalars()]
