"""Chart Coach API: upload chart screenshots → AI reading + ATLAS risk checks → suggested move."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..agent import _jsonable
from ..db import get_db, session_scope
from ..logging import get_logger
from ..models import AppSetting, ScreenshotAnalysis, User
from ..portfolio import get_account, mark, quotes_from_snapshot
from ..screenshot import MAX_BYTES, ScreenshotError, assess, image_hashes, read_chart, validate_images
from ..security import audit, current_user, limiter, require
from ..trading_config import HARD_MAX_RISK_PER_TRADE_PCT, load_config

log = get_logger("atlas.coach")
router = APIRouter(prefix="/api/coach")


def _setting(db: Session, key: str, default=None):
    row = db.get(AppSetting, key)
    return row.value if row else default


def row_dict(r: ScreenshotAnalysis) -> dict:
    return {"id": r.id, "ts": r.ts.isoformat(), "username": r.username, "instrument": r.instrument, "ai_recommendation": r.ai_recommendation,
            "final": r.final, "note": r.note, "result": r.result}


@router.post("/analyze")
async def analyze(request: Request, files: list[UploadFile] = File(...), note: str = Form(""), balance: float | None = Form(None),
                  risk_pct: float = Form(0.5), user: User = Depends(require("trader"))):
    if not limiter.allow(f"coach:{user.username}", 6, 60):
        raise HTTPException(429, "at most 6 chart analyses per minute")
    if not (0 < risk_pct <= HARD_MAX_RISK_PER_TRADE_PCT):
        raise HTTPException(422, f"risk per trade must be between 0 and {HARD_MAX_RISK_PER_TRADE_PCT}%")
    if balance is not None and not (50 <= balance <= 1e8):
        raise HTTPException(422, "account balance must be between 50 and 100,000,000")
    raw = []
    for f in files[:5]:
        data = await f.read(MAX_BYTES + 1)
        raw.append(data)
    try:
        images = validate_images(raw)
    except ScreenshotError as e:
        raise HTTPException(e.status, str(e))
    with session_scope() as db:
        cfg = load_config(db)
        quotes = quotes_from_snapshot(_setting(db, "market_quotes"))
        events = (_setting(db, "macro_snapshot") or {}).get("events", [])
        rows = (_setting(db, "analysis_snapshot") or {}).get("rows", [])
        if balance is None:
            balance = mark(db, get_account(db, "paper", cfg.paper_starting_capital), quotes)["equity"]
    try:
        reading = await read_chart(images, note.strip())
    except ScreenshotError as e:
        raise HTTPException(e.status, str(e))
    except ValueError:
        raise HTTPException(502, "the AI returned an unreadable answer — try again")
    result = _jsonable(assess(reading, cfg, quotes, events, rows, float(balance), risk_pct))
    with session_scope() as db:
        rec = ScreenshotAnalysis(username=user.username, instrument=reading.get("instrument"), ai_recommendation=reading.get("recommendation"),
                                 final=result["final"], note=note[:1000] or None, image_hashes=image_hashes(images), result=result)
        db.add(rec)
        db.flush()
        audit(db, user, "chart_coach", reading.get("instrument"), {"final": result["final"], "images": len(images)}, request)
        return row_dict(rec)


@router.get("/history")
def history(limit: int = 30, user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(ScreenshotAnalysis).order_by(ScreenshotAnalysis.id.desc()).limit(min(limit, 100))
    return [row_dict(r) for r in db.execute(q).scalars()]
