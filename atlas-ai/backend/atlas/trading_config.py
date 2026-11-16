"""Runtime trading configuration (persisted in the database, editable from the UI).

All limits are validated server-side. Hard ceilings (e.g. max risk per trade 1%)
cannot be raised from the UI: they are enforced by the validators below.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from .models import AppSetting

HARD_MAX_RISK_PER_TRADE_PCT = 1.0
HARD_MAX_DAILY_LOSS_PCT = 2.0
HARD_MAX_WEEKLY_LOSS_PCT = 5.0
HARD_MAX_OPEN_POSITIONS = 3
HARD_MIN_RR = 2.0

SUPPORTED_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")
DEFAULT_SYMBOLS = ["SOLUSDC", "BTCUSDC", "ETHUSDC", "JUPUSDC", "WIFUSDC", "BONKUSDC", "JTOUSDC", "RAYUSDC", "PYTHUSDC"]
STRATEGY_NAMES = ("trend_following", "momentum", "breakout", "vwap_reversion")


class RiskLimits(BaseModel):
    risk_per_trade_pct: float = Field(0.5, gt=0, le=HARD_MAX_RISK_PER_TRADE_PCT)
    max_daily_loss_pct: float = Field(2.0, gt=0, le=HARD_MAX_DAILY_LOSS_PCT)
    max_weekly_loss_pct: float = Field(5.0, gt=0, le=HARD_MAX_WEEKLY_LOSS_PCT)
    max_open_positions: int = Field(3, ge=1, le=HARD_MAX_OPEN_POSITIONS)
    max_portfolio_exposure_pct: float = Field(60.0, gt=0, le=100.0)
    max_position_exposure_pct: float = Field(25.0, gt=0, le=100.0)
    min_risk_reward: float = Field(2.0, ge=HARD_MIN_RR, le=10.0)
    max_slippage_bps: float = Field(25.0, gt=0, le=200.0)
    max_spread_bps: float = Field(15.0, gt=0, le=200.0)
    consecutive_loss_cooldown: int = Field(3, ge=1, le=20)
    cooldown_minutes: int = Field(120, ge=0, le=7 * 24 * 60)
    max_daily_trades: int = Field(10, ge=0, le=200)
    max_data_staleness_seconds: int = Field(30, ge=5, le=600)
    max_venue_divergence_pct: float = Field(1.5, gt=0, le=10.0)


class TradingHours(BaseModel):
    enabled: bool = False
    start_hour_utc: int = Field(0, ge=0, le=23)
    end_hour_utc: int = Field(24, ge=1, le=24)
    weekdays: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4, 5, 6])

    @model_validator(mode="after")
    def _check(self):
        if self.end_hour_utc <= self.start_hour_utc:
            raise ValueError("end_hour_utc must be after start_hour_utc")
        if any(d < 0 or d > 6 for d in self.weekdays):
            raise ValueError("weekdays must be 0 (Mon) .. 6 (Sun)")
        return self


class FeeModel(BaseModel):
    taker_fee_bps: float = Field(10.0, ge=0, le=100)
    maker_fee_bps: float = Field(10.0, ge=0, le=100)
    base_slippage_bps: float = Field(2.0, ge=0, le=100)
    impact_coefficient: float = Field(0.1, ge=0, le=10)  # bps per 1% of 1-min volume consumed
    max_participation_pct: float = Field(10.0, gt=0, le=100)  # partial fill cap per tick vs 1-min volume


class AutomationConfig(BaseModel):
    scanning_enabled: bool = True
    signal_generation_enabled: bool = True
    auto_paper_trading: bool = False
    scan_interval_seconds: int = Field(30, ge=10, le=3600)
    token_scanner_enabled: bool = True
    token_scan_interval_seconds: int = Field(300, ge=60, le=86400)
    ai_commentary_enabled: bool = False


class TradingConfig(BaseModel):
    mode: Literal["paper", "live"] = "paper"
    trading_enabled: bool = True  # global disable switch for NEW orders
    kill_switch: bool = False  # emergency stop (sticky until an admin resumes)
    kill_switch_action: Literal["keep_protective", "flatten"] = "keep_protective"
    paper_starting_capital: float = Field(10_000.0, gt=0, le=1e9)
    symbols: list[str] = Field(default_factory=lambda: list(DEFAULT_SYMBOLS))
    primary_timeframe: Literal["5m", "15m"] = "5m"
    enabled_strategies: list[str] = Field(default_factory=lambda: list(STRATEGY_NAMES))
    min_liquidity_usd: float = Field(250_000.0, ge=0)  # order-book depth within ±1%
    min_volume_24h_usd: float = Field(1_000_000.0, ge=0)
    min_confidence_to_trade: int = Field(60, ge=0, le=100)
    risk: RiskLimits = Field(default_factory=RiskLimits)
    hours: TradingHours = Field(default_factory=TradingHours)
    fees: FeeModel = Field(default_factory=FeeModel)
    automation: AutomationConfig = Field(default_factory=AutomationConfig)
    live_confirmed: bool = False  # explicit user acknowledgement required to arm live mode

    @field_validator("symbols")
    @classmethod
    def _symbols(cls, v: list[str]):
        out = []
        for s in v:
            s = s.strip().upper()
            if not s.isalnum() or not (5 <= len(s) <= 20) or not s.endswith(("USDC", "USDT")):
                raise ValueError(f"invalid symbol {s!r}; use exchange format like SOLUSDC")
            if s not in out:
                out.append(s)
        if not out:
            raise ValueError("at least one symbol is required")
        return out[:30]

    @field_validator("enabled_strategies")
    @classmethod
    def _strategies(cls, v: list[str]):
        bad = [s for s in v if s not in STRATEGY_NAMES]
        if bad:
            raise ValueError(f"unknown strategies: {bad}")
        return v


KEY = "trading_config"


def load_config(db: Session) -> TradingConfig:
    row = db.get(AppSetting, KEY)
    if row is None:
        cfg = TradingConfig()
        db.add(AppSetting(key=KEY, value=cfg.model_dump()))
        db.flush()
        return cfg
    return TradingConfig.model_validate(row.value)


def save_config(db: Session, cfg: TradingConfig, user: str | None = None) -> TradingConfig:
    row = db.get(AppSetting, KEY)
    data = cfg.model_dump()
    if row is None:
        db.add(AppSetting(key=KEY, value=data, updated_by=user))
    else:
        row.value = data
        row.updated_by = user
    db.flush()
    return cfg
