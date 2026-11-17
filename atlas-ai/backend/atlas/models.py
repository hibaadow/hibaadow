"""Persistent data model."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


TS = DateTime(timezone=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(16), default="viewer")  # admin | trader | viewer
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    last_login: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    session_version: Mapped[int] = mapped_column(Integer, default=1)


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow, onupdate=utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)


class StrategyConfig(Base):
    __tablename__ = "strategy_configs"
    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow, onupdate=utcnow)


class IntegrationStatus(Base):
    __tablename__ = "integration_status"
    name: Mapped[str] = mapped_column(String(48), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="unknown")  # ok | degraded | down | unconfigured
    last_ok: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow, onupdate=utcnow)


class Candle(Base):
    __tablename__ = "candles"
    venue: Mapped[str] = mapped_column(String(16), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(24), primary_key=True)
    timeframe: Mapped[str] = mapped_column(String(4), primary_key=True)
    open_time: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # ms epoch
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)  # tick volume / sample count
    quote_volume: Mapped[float] = mapped_column(Float, default=0.0)
    spread: Mapped[float] = mapped_column(Float, default=0.0)


class MarketDataRef(Base):
    __tablename__ = "market_data_refs"
    __table_args__ = (UniqueConstraint("venue", "symbol", "timeframe"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    venue: Mapped[str] = mapped_column(String(16))
    symbol: Mapped[str] = mapped_column(String(24))
    timeframe: Mapped[str] = mapped_column(String(4))
    first_open_time: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_open_time: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    candle_count: Mapped[int] = mapped_column(Integer, default=0)
    gaps: Mapped[int] = mapped_column(Integer, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, default=0)
    invalid: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="unknown")  # ok | stale | gaps | invalid
    last_validated: Mapped[datetime | None] = mapped_column(TS, nullable=True)


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mode: Mapped[str] = mapped_column(String(8), unique=True)  # paper | demo | live (never mixed)
    quote_asset: Mapped[str] = mapped_column(String(8), default="USD")  # account currency
    starting_capital: Mapped[float] = mapped_column(Float)
    cash: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    reset_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)


class Signal(Base):
    __tablename__ = "signals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)
    symbol: Mapped[str] = mapped_column(String(24), index=True)
    timeframe: Mapped[str] = mapped_column(String(4))
    strategy: Mapped[str] = mapped_column(String(32), index=True)
    direction: Mapped[str] = mapped_column(String(8))  # buy | sell | exit | none
    candle_time: Mapped[int] = mapped_column(BigInteger)
    entry: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop: Mapped[float | None] = mapped_column(Float, nullable=True)
    targets: Mapped[list] = mapped_column(JSON, default=list)
    strength: Mapped[float] = mapped_column(Float, default=0.0)
    features: Mapped[dict] = mapped_column(JSON, default=dict)
    reasons: Mapped[list] = mapped_column(JSON, default=list)


class Decision(Base):
    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signals.id"), nullable=True)
    symbol: Mapped[str] = mapped_column(String(24), index=True)
    strategy: Mapped[str] = mapped_column(String(32))
    classification: Mapped[str] = mapped_column(String(24))
    confidence: Mapped[int] = mapped_column(Integer)
    direction: Mapped[str | None] = mapped_column(String(4), nullable=True)  # BUY | SELL
    timeframe: Mapped[str | None] = mapped_column(String(4), nullable=True)
    entry: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit_2: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_reward: Mapped[float | None] = mapped_column(Float, nullable=True)
    lots: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    est_costs: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    events: Mapped[list] = mapped_column(JSON, default=list)
    invalidation: Mapped[list] = mapped_column(JSON, default=list)
    score_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    risk_flags: Mapped[list] = mapped_column(JSON, default=list)
    explanation: Mapped[str] = mapped_column(Text)
    ai_commentary: Mapped[str | None] = mapped_column(Text, nullable=True)
    executed: Mapped[bool] = mapped_column(Boolean, default=False)
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    position_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(8), nullable=True)  # win | loss | flat
    outcome_r: Mapped[float | None] = mapped_column(Float, nullable=True)


class Position(Base):
    __tablename__ = "positions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    mode: Mapped[str] = mapped_column(String(8), index=True)
    symbol: Mapped[str] = mapped_column(String(24), index=True)
    strategy: Mapped[str] = mapped_column(String(32))
    side: Mapped[str] = mapped_column(String(4), default="buy")  # buy | sell
    broker_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    commission: Mapped[float] = mapped_column(Float, default=0.0)
    swap: Mapped[float] = mapped_column(Float, default=0.0)
    pip_value_usd: Mapped[float] = mapped_column(Float, default=0.0)  # per 1.0 lot at entry
    status: Mapped[str] = mapped_column(String(12), default="pending", index=True)  # pending | open | closed | cancelled
    opened_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    qty: Mapped[float] = mapped_column(Float, default=0.0)  # LOTS currently open
    initial_qty: Mapped[float] = mapped_column(Float, default=0.0)
    planned_qty: Mapped[float] = mapped_column(Float, default=0.0)
    entry_price: Mapped[float] = mapped_column(Float, default=0.0)  # average fill
    planned_entry: Mapped[float] = mapped_column(Float, default=0.0)
    stop_price: Mapped[float] = mapped_column(Float)
    initial_stop: Mapped[float] = mapped_column(Float)
    tp1: Mapped[float] = mapped_column(Float)
    tp2: Mapped[float | None] = mapped_column(Float, nullable=True)
    tp1_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    risk_amount: Mapped[float] = mapped_column(Float, default=0.0)
    fees_paid: Mapped[float] = mapped_column(Float, default=0.0)
    slippage_cost: Mapped[float] = mapped_column(Float, default=0.0)
    gross_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    net_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    exit_value: Mapped[float] = mapped_column(Float, default=0.0)
    exit_qty: Mapped[float] = mapped_column(Float, default=0.0)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_reason: Mapped[str] = mapped_column(Text, default="")
    exit_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_favorable: Mapped[float] = mapped_column(Float, default=0.0)
    max_adverse: Mapped[float] = mapped_column(Float, default=0.0)
    last_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_history: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_order_id: Mapped[str] = mapped_column(String(64), unique=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    mode: Mapped[str] = mapped_column(String(8), index=True)
    position_id: Mapped[int | None] = mapped_column(ForeignKey("positions.id"), nullable=True, index=True)
    symbol: Mapped[str] = mapped_column(String(24))
    side: Mapped[str] = mapped_column(String(4))  # buy | sell
    type: Mapped[str] = mapped_column(String(12))  # market | limit | stop
    purpose: Mapped[str] = mapped_column(String(12))  # entry | stop | tp1 | tp2 | exit
    qty: Mapped[float] = mapped_column(Float)
    filled_qty: Mapped[float] = mapped_column(Float, default=0.0)
    limit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="new", index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    venue: Mapped[str] = mapped_column(String(16), default="paper")
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    fees: Mapped[float] = mapped_column(Float, default=0.0)
    expires_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow, onupdate=utcnow)


class Execution(Base):
    __tablename__ = "executions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    ts: Mapped[datetime] = mapped_column(TS, default=utcnow)
    qty: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    reference_price: Mapped[float] = mapped_column(Float)
    fee: Mapped[float] = mapped_column(Float)
    slippage_bps: Mapped[float] = mapped_column(Float)
    slippage_cost: Mapped[float] = mapped_column(Float)
    liquidity: Mapped[str] = mapped_column(String(6))  # maker | taker
    tx_signature: Mapped[str | None] = mapped_column(String(128), nullable=True)


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"
    __table_args__ = (Index("ix_snap_acct_ts", "account_id", "ts"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    ts: Mapped[datetime] = mapped_column(TS, default=utcnow)
    equity: Mapped[float] = mapped_column(Float)
    cash: Mapped[float] = mapped_column(Float)
    positions_value: Mapped[float] = mapped_column(Float)
    unrealized: Mapped[float] = mapped_column(Float)
    realized_total: Mapped[float] = mapped_column(Float)


class RiskEvent(Base):
    __tablename__ = "risk_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)
    kind: Mapped[str] = mapped_column(String(48))
    severity: Mapped[str] = mapped_column(String(8))  # info | warn | critical
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class ActivityEvent(Base):
    __tablename__ = "activity_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    symbol: Mapped[str | None] = mapped_column(String(24), nullable=True)
    message: Mapped[str] = mapped_column(Text)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class BacktestRun(Base):
    __tablename__ = "backtest_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="queued")
    params: Mapped[dict] = mapped_column(JSON)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    oos_metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    walk_forward: Mapped[dict] = mapped_column(JSON, default=dict)
    equity_curve: Mapped[list] = mapped_column(JSON, default=list)
    trades: Mapped[list] = mapped_column(JSON, default=list)
    data_quality: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str | None] = mapped_column(String(128), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ScreenshotAnalysis(Base):
    """Chart Coach result. Images are NOT stored — only their SHA-256 hashes."""

    __tablename__ = "screenshot_analyses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    instrument: Mapped[str | None] = mapped_column(String(12), nullable=True)
    ai_recommendation: Mapped[str | None] = mapped_column(String(10), nullable=True)
    final: Mapped[str] = mapped_column(String(10))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_hashes: Mapped[list] = mapped_column(JSON, default=list)
    result: Mapped[dict] = mapped_column(JSON, default=dict)


class Command(Base):
    """Queue of operator commands from the API to the trading worker."""

    __tablename__ = "commands"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(TS, default=utcnow)
    kind: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(12), default="pending", index=True)
    requested_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
