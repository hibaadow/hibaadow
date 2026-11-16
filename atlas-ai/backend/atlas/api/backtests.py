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
from ..config import get_settings
from ..instruments import INSTRUMENTS, is_supported, normalize
from ..models import Candle as CandleRow
from ..marketdata.types import Candle, resample_candles
from ..marketdata.types import TF_MS, CandleSeries
from ..marketdata.validation import validate_candles
from ..models import BacktestRun, User
from ..security import audit, current_user, require
from ..strategies.library import STRATEGIES
from ..trading_config import RiskLimits, load_config

log = get_logger("atlas.backtest.api")
router = APIRouter(prefix="/api/backtests")
MAX_BARS = 60_000
_running: set[int] = set()


class BacktestBody(BaseModel):
    symbol: str = Field(pattern=r"^[A-Za-z/_]{6,8}$")
    strategy: str
    timeframe: str = Field(pattern="^(1m|5m|15m|1h|4h)$")
    start: datetime
    end: datetime
    starting_capital: float = Field(10_000, gt=100, le=1e8)
    commission_per_lot_side: float = Field(3.5, ge=0, le=50)
    spread_pips: float | None = Field(None, ge=0, le=200)  # None = per-bar spread from broker data, else instrument default
    risk_per_trade_pct: float = Field(0.5, gt=0, le=1.0)
    oos_fraction: float = Field(0.3, ge=0.1, le=0.5)
    walk_forward: bool = True
    folds: int = Field(3, ge=2, le=6)

    @model_validator(mode="after")
    def _v(self):
        if not is_supported(self.symbol):
            raise ValueError("ATLAS backtests XAU/USD and the supported forex pairs only")
        self.symbol = normalize(self.symbol)
        if self.strategy not in STRATEGIES:
            raise ValueError(f"strategy must be one of {list(STRATEGIES)}")
        if not STRATEGIES[self.strategy]({}).applies_to(self.symbol):
            raise ValueError(f"{self.strategy} only applies to {STRATEGIES[self.strategy].instruments}")
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
    asyncio.get_event_loop().create_task(execute(run.id, body, request.app.state.history))
    return {"id": run.id, "status": "queued"}


def stored_public_history(symbol: str, tf: str, start: int, end: int) -> list[Candle]:
    with session_scope() as db:
        rows = db.execute(select(CandleRow).where(CandleRow.venue == "public", CandleRow.symbol == symbol, CandleRow.timeframe == "1m",
                                                  CandleRow.open_time >= start, CandleRow.open_time < end).order_by(CandleRow.open_time)).scalars().all()
        base = [Candle(r.open_time, r.open, r.high, r.low, r.close, r.volume, 0.0, r.spread or 0.0) for r in rows]
    return base if tf == "1m" else resample_candles(base, tf)


async def execute(run_id: int, body: BacktestBody, history) -> None:
    _running.add(run_id)
    try:
        with session_scope() as db:
            db.get(BacktestRun, run_id).status = "fetching"
        start = int(body.start.timestamp() * 1000)
        end = int(body.end.timestamp() * 1000)
        inst = INSTRUMENTS[body.symbol]
        if history is not None:
            candles = await history.history(body.symbol, body.timeframe, start, end)
            source = get_settings().data_source
        else:
            candles = stored_public_history(body.symbol, body.timeframe, start, end)
            source = "public (sampled bars stored by ATLAS)"
        clean, report = validate_candles(candles, body.timeframe, asset_class=inst.asset_class)
        if len(clean) < 600:
            raise ValueError(f"only {len(clean)} valid {body.timeframe} candles available for {inst.display} in this range. Historical intraday "
                             "data requires a broker data connection (OANDA practice token or MT5 bridge); without one, ATLAS can only "
                             "backtest on bars it has recorded from the live public quote feed.")
        series = CandleSeries.from_candles(body.symbol, body.timeframe, source, clean)
        with session_scope() as db:
            run = db.get(BacktestRun, run_id)
            run.status = "running"
            run.data_quality = _jsonable({**report, "first": clean[0].open_time, "last": clean[-1].open_time, "source": source})
            base_cfg = load_config(db)
        cfg = base_cfg.model_copy(update={
            "costs": base_cfg.costs.model_copy(update={"commission_per_lot_side_usd": body.commission_per_lot_side,
                                                       "gold_commission_per_lot_side_usd": body.commission_per_lot_side}),
            "risk": RiskLimits(**{**base_cfg.risk.model_dump(), "risk_per_trade_pct": body.risk_per_trade_pct})})
        with session_scope() as db:
            from ..models import AppSetting
            mq = (db.get(AppSetting, "market_quotes").value if db.get(AppSetting, "market_quotes") else {}) or {}
        mids = {k: (v["bid"] + v["ask"]) / 2 for k, v in mq.items()}
        p = BTParams(body.symbol, body.strategy, body.timeframe, body.starting_capital, body.spread_pips, {}, body.oos_fraction, mids)

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
