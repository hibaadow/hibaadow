"""Backtest job API. Jobs run in the API process (network fetch async, compute in a thread)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..agent import _jsonable
from ..backtest import Backtester, BTParams, split_metrics, walk_forward
from ..db import get_db, session_scope
from ..logging import get_logger
from ..marketdata.providers import BinanceMarketData
from ..marketdata.types import TF_MS, CandleSeries
from ..marketdata.validation import validate_candles
from ..models import BacktestRun, User
from ..security import audit, current_user, require
from ..strategies.library import STRATEGIES
from ..trading_config import FeeModel, RiskLimits, load_config

log = get_logger("atlas.backtest.api")
router = APIRouter(prefix="/api/backtests")
MAX_BARS = 60_000
_running: set[int] = set()


class BacktestBody(BaseModel):
    symbol: str = Field(pattern=r"^[A-Z0-9]{5,20}$")
    strategy: str
    timeframe: str = Field(pattern="^(1m|5m|15m|1h|4h)$")
    start: datetime
    end: datetime
    starting_capital: float = Field(10_000, gt=100, le=1e8)
    taker_fee_bps: float = Field(10, ge=0, le=100)
    maker_fee_bps: float = Field(10, ge=0, le=100)
    base_slippage_bps: float = Field(2, ge=0, le=100)
    spread_bps: float = Field(2, ge=0, le=100)
    risk_per_trade_pct: float = Field(0.5, gt=0, le=1.0)
    oos_fraction: float = Field(0.3, ge=0.1, le=0.5)
    walk_forward: bool = True
    folds: int = Field(3, ge=2, le=6)

    @model_validator(mode="after")
    def _v(self):
        if self.strategy not in STRATEGIES:
            raise ValueError(f"strategy must be one of {list(STRATEGIES)}")
        s, e = self.start.replace(tzinfo=self.start.tzinfo or timezone.utc), self.end.replace(tzinfo=self.end.tzinfo or timezone.utc)
        if e <= s:
            raise ValueError("end must be after start")
        if e > datetime.now(timezone.utc):
            self.end = datetime.now(timezone.utc)
        bars = (e - s).total_seconds() * 1000 / TF_MS[self.timeframe]
        if bars > MAX_BARS:
            raise ValueError(f"range too large ({bars:.0f} bars, max {MAX_BARS}); shorten range or use a higher timeframe")
        if bars < 600:
            raise ValueError("range too short: need at least ~600 bars for warm-up and meaningful statistics")
        return self


def run_summary(r: BacktestRun) -> dict:
    return {"id": r.id, "created_at": r.created_at.isoformat(), "created_by": r.created_by, "status": r.status, "params": r.params,
            "metrics": r.metrics, "oos_metrics": r.oos_metrics, "error": r.error, "label": "BACKTEST (historical simulation)"}


@router.post("")
async def create(body: BacktestBody, request: Request, user: User = Depends(require("trader")), db: Session = Depends(get_db)):
    if len(_running) >= 2:
        raise HTTPException(429, "two backtests already running; wait for them to finish")
    params = _jsonable(body.model_dump())
    run = BacktestRun(params=params, created_by=user.username, status="queued")
    db.add(run)
    db.flush()
    audit(db, user, "backtest_created", str(run.id), params, request)
    db.commit()
    asyncio.get_event_loop().create_task(execute(run.id, body, request.app.state.binance))
    return {"id": run.id, "status": "queued"}


async def execute(run_id: int, body: BacktestBody, md: BinanceMarketData) -> None:
    _running.add(run_id)
    try:
        with session_scope() as db:
            db.get(BacktestRun, run_id).status = "fetching"
        start = int(body.start.timestamp() * 1000)
        end = int(body.end.timestamp() * 1000)
        candles = await md.history(body.symbol, body.timeframe, start, end, MAX_BARS + 10)
        clean, report = validate_candles(candles, body.timeframe)
        if len(clean) < 600:
            raise ValueError(f"only {len(clean)} valid candles returned for {body.symbol} {body.timeframe}")
        series = CandleSeries.from_candles(body.symbol, body.timeframe, "binance", clean)
        with session_scope() as db:
            run = db.get(BacktestRun, run_id)
            run.status = "running"
            run.data_quality = _jsonable({**report, "first": clean[0].open_time, "last": clean[-1].open_time})
            base_cfg = load_config(db)
        cfg = base_cfg.model_copy(update={
            "fees": FeeModel(**{**base_cfg.fees.model_dump(), "taker_fee_bps": body.taker_fee_bps, "maker_fee_bps": body.maker_fee_bps,
                                "base_slippage_bps": body.base_slippage_bps}),
            "risk": RiskLimits(**{**base_cfg.risk.model_dump(), "risk_per_trade_pct": body.risk_per_trade_pct})})
        p = BTParams(body.symbol, body.strategy, body.timeframe, body.starting_capital, body.spread_bps, {}, body.oos_fraction)

        def compute():
            bt = Backtester(cfg)
            res = bt.run(series, p)
            ins, oos = split_metrics(res, series, p)
            wf = walk_forward(bt, series, p, body.folds) if body.walk_forward else {}
            return res, ins, oos, wf

        res, ins, oos, wf = await asyncio.to_thread(compute)
        curve = res["curve"]
        stride = max(1, len(curve) // 1500)
        with session_scope() as db:
            run = db.get(BacktestRun, run_id)
            run.metrics = _jsonable({**res["metrics"], "signals": res["signals"], "rejected_by_risk": res["rejected"], "in_sample": ins})
            run.oos_metrics = _jsonable(oos)
            run.walk_forward = _jsonable(wf)
            run.equity_curve = _jsonable(curve[::stride] + ([curve[-1]] if curve and len(curve) % stride else []))
            run.trades = _jsonable(res["trades"][-2000:])
            run.status = "done"
    except Exception as e:  # noqa: BLE001
        log.exception("backtest failed")
        with session_scope() as db:
            run = db.get(BacktestRun, run_id)
            run.status = "failed"
            run.error = f"{type(e).__name__}: {str(e)[:500]}"
    finally:
        _running.discard(run_id)


@router.get("")
def list_runs(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [run_summary(r) for r in db.execute(select(BacktestRun).order_by(BacktestRun.id.desc()).limit(100)).scalars()]


@router.get("/compare")
def compare(ids: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        id_list = [int(x) for x in ids.split(",")][:8]
    except ValueError:
        raise HTTPException(400, "ids must be comma-separated integers")
    runs = db.execute(select(BacktestRun).where(BacktestRun.id.in_(id_list))).scalars().all()
    return [{**run_summary(r), "equity_curve": r.equity_curve, "walk_forward": r.walk_forward} for r in runs]


@router.get("/{run_id}")
def get_run(run_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = db.get(BacktestRun, run_id)
    if not r:
        raise HTTPException(404, "not found")
    return {**run_summary(r), "walk_forward": r.walk_forward, "equity_curve": r.equity_curve, "trades": r.trades, "data_quality": r.data_quality,
            "disclaimer": "Backtested results are hypothetical, use modelled costs, and do not prove future profitability."}


@router.delete("/{run_id}")
def delete_run(run_id: int, request: Request, user: User = Depends(require("trader")), db: Session = Depends(get_db)):
    r = db.get(BacktestRun, run_id)
    if not r:
        raise HTTPException(404, "not found")
    db.delete(r)
    audit(db, user, "backtest_deleted", str(run_id), request=request)
    return {"ok": True}
