from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from atlas.risk import OpenExposure, RiskContext, TradeRequest, evaluate_trade, gate_status, size_position
from atlas.trading_config import RiskLimits, TradingConfig


def ctx(**kw):
    base = dict(equity=10_000, cash=10_000, start_of_day_equity=10_000, start_of_week_equity=10_000, open_positions=[],
                trades_today=0, consecutive_losses=0, last_loss_at=None)
    base.update(kw)
    return RiskContext(**base)


def req(**kw):
    base = dict(symbol="SOLUSDC", entry=100.0, stop=98.0, target=104.0, spread_bps=1.0, minute_quote_volume=5_000_000,
                liquidity_usd=5_000_000, volume_24h_usd=500_000_000)
    base.update(kw)
    return TradeRequest(**base)


def failed(d):
    return {c["name"] for c in d.checks if not c["passed"]}


def test_default_trade_approved_and_sized_to_risk():
    cfg = TradingConfig()
    d = evaluate_trade(cfg, ctx(), req())
    assert d.approved, d.blocking
    # risk is 0.5% of equity INCLUDING fees + slippage
    assert d.risk_amount == pytest.approx(50.0, rel=1e-3)
    assert d.qty * (100 - 98) < 50  # raw stop-distance risk is lower because costs are included
    assert d.net_rr >= 2.0 - 1e-9


def test_target_raised_to_meet_min_rr_after_costs():
    d = evaluate_trade(TradingConfig(), ctx(), req(target=104.0))
    assert d.target > 104.0  # 2R gross is < 2R net after fees
    assert any(c["name"] == "target_adjusted" for c in d.checks) or any("TP1 raised" in c["detail"] for c in d.checks)


def test_resistance_before_target_blocks():
    d = evaluate_trade(TradingConfig(), ctx(), req(resistance=103.0))
    assert not d.approved and "room_to_target" in failed(d)


def test_hard_limits_cannot_be_exceeded():
    with pytest.raises(ValidationError):
        RiskLimits(risk_per_trade_pct=1.5)
    with pytest.raises(ValidationError):
        RiskLimits(max_daily_loss_pct=3)
    with pytest.raises(ValidationError):
        RiskLimits(max_open_positions=5)
    with pytest.raises(ValidationError):
        RiskLimits(min_risk_reward=1.5)


def test_daily_loss_limit_halts_trading():
    d = evaluate_trade(TradingConfig(), ctx(equity=9_790, cash=9_790), req())
    assert not d.approved and "daily_loss_limit" in failed(d) and d.halt == "daily_loss_limit"


def test_weekly_loss_limit():
    c = ctx(equity=9_480, cash=9_480, start_of_day_equity=9_480)
    d = evaluate_trade(TradingConfig(), c, req())
    assert "weekly_loss_limit" in failed(d)


def test_kill_switch_and_global_disable():
    cfg = TradingConfig(kill_switch=True)
    assert "kill_switch" in failed(gate_status(cfg, ctx()))
    cfg = TradingConfig(trading_enabled=False)
    assert "trading_enabled" in failed(gate_status(cfg, ctx()))


def test_max_positions_and_duplicate_symbol():
    ops = [OpenExposure("BTCUSDC", 1000, 50), OpenExposure("ETHUSDC", 1000, 50), OpenExposure("SOLUSDC", 1000, 50)]
    d = evaluate_trade(TradingConfig(), ctx(open_positions=ops), req())
    assert {"max_open_positions", "one_position_per_symbol"} <= failed(d)


def test_cooldown_after_consecutive_losses():
    now = datetime.now(timezone.utc)
    d = gate_status(TradingConfig(), ctx(consecutive_losses=3, last_loss_at=now - timedelta(minutes=10), now=now))
    assert "loss_cooldown" in failed(d)
    d = gate_status(TradingConfig(), ctx(consecutive_losses=3, last_loss_at=now - timedelta(minutes=500), now=now))
    assert "loss_cooldown" not in failed(d)


def test_size_never_increases_after_losses():
    cfg = TradingConfig()
    a = size_position(cfg, 10_000, 10_000, 0, 0, 100, 98, 104, 1, 5e6)
    b = size_position(cfg, 10_000, 10_000, 0, 2, 100, 98, 104, 1, 5e6)
    c = size_position(cfg, 9_500, 9_500, 0, 0, 100, 98, 104, 1, 5e6)
    assert b.qty < a.qty and c.qty < a.qty
    assert b.risk_amount == pytest.approx(a.risk_amount / 2, rel=1e-6)


def test_spot_only_no_leverage_cash_cap():
    cfg = TradingConfig()
    # very tight stop would require huge notional → capped by exposure/cash
    s = size_position(cfg, 10_000, 1_000, 0, 0, 100, 99.99, 101, 1, 5e9)
    assert s.notional <= 1_000 * 0.98 + 1e-6


def test_mandatory_stop_and_market_quality_checks():
    cfg = TradingConfig()
    assert "mandatory_stop" in failed(evaluate_trade(cfg, ctx(), req(stop=101)))
    d = evaluate_trade(cfg, ctx(), req(spread_bps=50, liquidity_usd=10_000, volume_24h_usd=1000, data_ready=False, data_issues=["stale"]))
    assert {"spread", "liquidity", "volume_24h", "market_data"} <= failed(d)


def test_slippage_limit():
    d = evaluate_trade(TradingConfig(), ctx(), req(minute_quote_volume=300))
    assert "slippage" in failed(d)


def test_trading_hours():
    cfg = TradingConfig.model_validate({"hours": {"enabled": True, "start_hour_utc": 13, "end_hour_utc": 21}})
    t = datetime(2026, 1, 5, 3, tzinfo=timezone.utc)
    assert "trading_hours" in failed(gate_status(cfg, ctx(now=t)))
    t = datetime(2026, 1, 5, 14, tzinfo=timezone.utc)
    assert "trading_hours" not in failed(gate_status(cfg, ctx(now=t)))
