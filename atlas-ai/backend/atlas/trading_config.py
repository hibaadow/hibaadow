"""Runtime trading configuration (persisted in the database, editable by admins).

Hard ceilings are enforced by validators and cannot be raised from the UI or API.
Only XAU/USD and the supported FX pairs can be configured — anything else is rejected.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from .instruments import DEFAULT_UNIVERSE, INSTRUMENTS, is_supported, normalize
from .models import AppSetting

HARD_MAX_RISK_PER_TRADE_PCT = 1.0
HARD_MAX_DAILY_LOSS_PCT = 2.0
HARD_MAX_WEEKLY_LOSS_PCT = 5.0
HARD_MAX_OPEN_POSITIONS = 3
HARD_MIN_RR = 2.0
HARD_MAX_LEVERAGE = 30.0

SUPPORTED_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")
STRATEGY_NAMES = ("trend_pullback", "breakout_retest", "liquidity_sweep", "supply_demand", "gold_session")


class RiskLimits(BaseModel):
    risk_per_trade_pct: float = Field(0.5, gt=0, le=HARD_MAX_RISK_PER_TRADE_PCT)
    max_daily_loss_pct: float = Field(2.0, gt=0, le=HARD_MAX_DAILY_LOSS_PCT)
    max_weekly_loss_pct: float = Field(5.0, gt=0, le=HARD_MAX_WEEKLY_LOSS_PCT)
    max_open_positions: int = Field(3, ge=1, le=HARD_MAX_OPEN_POSITIONS)
    max_risk_per_currency_pct: float = Field(1.0, gt=0, le=3.0)  # open risk sharing one currency (e.g. USD)
    max_effective_leverage: float = Field(10.0, gt=0, le=HARD_MAX_LEVERAGE)  # total notional / equity
    min_margin_level_pct: float = Field(300.0, ge=100, le=10_000)  # equity / used margin after the trade
    min_risk_reward: float = Field(2.0, ge=HARD_MIN_RR, le=10.0)
    spread_limits_pips: dict[str, float] = Field(default_factory=lambda: {s: i.max_spread_pips for s, i in INSTRUMENTS.items()})
    max_slippage_pips: dict[str, float] = Field(default_factory=lambda: {s: max(1.0, i.slippage_pips * 4) for s, i in INSTRUMENTS.items()})
    consecutive_loss_cooldown: int = Field(3, ge=1, le=20)
    cooldown_minutes: int = Field(120, ge=0, le=7 * 24 * 60)
    max_daily_trades: int = Field(8, ge=0, le=100)
    max_data_staleness_seconds: int = Field(30, ge=5, le=600)
    max_reference_divergence_pips: float = Field(15.0, gt=0, le=500)

    @field_validator("spread_limits_pips", "max_slippage_pips")
    @classmethod
    def _per_symbol(cls, v: dict):
        out = {}
        for k, val in v.items():
            if not is_supported(k):
                raise ValueError(f"{k} is not a gold/forex instrument")
            if not (0 < float(val) <= 200):
                raise ValueError(f"{k}: limit must be between 0 and 200 pips")
            out[normalize(k)] = float(val)
        return out


class NewsFilter(BaseModel):
    enabled: bool = True
    minutes_before: int = Field(30, ge=0, le=240)
    minutes_after: int = Field(30, ge=0, le=240)
    central_bank_extra_minutes: int = Field(30, ge=0, le=240)
    flatten_before_high_impact: bool = False  # optionally close positions ahead of high-impact events


class SessionFilter(BaseModel):
    allowed_sessions: list[str] = Field(default_factory=lambda: ["London", "New York"])
    allow_asia_for_asia_pairs: bool = True  # JPY/AUD/NZD pairs may trade in Tokyo/Sydney
    avoid_rollover: bool = True
    close_before_weekend: bool = True  # flat by Friday 16:30 New York

    @field_validator("allowed_sessions")
    @classmethod
    def _s(cls, v):
        bad = [x for x in v if x not in ("Sydney", "Tokyo", "London", "New York")]
        if bad:
            raise ValueError(f"unknown sessions {bad}")
        return v


class CostModel(BaseModel):
    commission_per_lot_side_usd: float = Field(3.5, ge=0, le=50)  # ECN-style; set 0 for spread-only accounts
    gold_commission_per_lot_side_usd: float = Field(3.5, ge=0, le=50)
    slippage_multiplier: float = Field(1.0, ge=0, le=10)  # scales each instrument's modelled slippage
    news_slippage_multiplier: float = Field(3.0, ge=1, le=20)


class AutomationConfig(BaseModel):
    scanning_enabled: bool = True
    signal_generation_enabled: bool = True
    auto_trading: bool = False  # automatic execution in the current mode (paper by default)
    scan_interval_seconds: int = Field(30, ge=10, le=3600)
    ai_commentary_enabled: bool = False


class TradingConfig(BaseModel):
    mode: Literal["paper", "demo", "live"] = "paper"
    trading_enabled: bool = True
    kill_switch: bool = False
    kill_switch_action: Literal["keep_protective", "flatten"] = "keep_protective"
    paper_starting_capital: float = Field(10_000.0, gt=0, le=1e9)
    paper_leverage: float = Field(30.0, ge=1, le=HARD_MAX_LEVERAGE)  # paper account leverage cap (ESMA retail majors)
    symbols: list[str] = Field(default_factory=lambda: list(DEFAULT_UNIVERSE))
    primary_timeframe: Literal["5m", "15m"] = "5m"
    enabled_strategies: list[str] = Field(default_factory=lambda: list(STRATEGY_NAMES))
    min_confidence_to_trade: int = Field(60, ge=0, le=100)
    risk: RiskLimits = Field(default_factory=RiskLimits)
    news: NewsFilter = Field(default_factory=NewsFilter)
    sessions: SessionFilter = Field(default_factory=SessionFilter)
    costs: CostModel = Field(default_factory=CostModel)
    automation: AutomationConfig = Field(default_factory=AutomationConfig)
    live_confirmed: bool = False

    @field_validator("symbols")
    @classmethod
    def _symbols(cls, v: list[str]):
        out = []
        for s in v:
            if not isinstance(s, str) or not is_supported(s):
                raise ValueError(f"{s!r} is not supported — ATLAS trades XAU/USD and selected forex pairs only")
            n = normalize(s)
            if n not in out:
                out.append(n)
        if not out:
            raise ValueError("at least one instrument is required")
        return out

    @field_validator("enabled_strategies")
    @classmethod
    def _strategies(cls, v: list[str]):
        bad = [s for s in v if s not in STRATEGY_NAMES]
        if bad:
            raise ValueError(f"unknown strategies: {bad}")
        return v

    @model_validator(mode="after")
    def _live(self):
        if self.mode != "live":
            self.live_confirmed = False if self.mode == "paper" else self.live_confirmed
        return self


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
