from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from atlas.econ import EconEvent
from atlas.instruments import get
from atlas.risk import OpenExposure, RiskContext, TradeRequest, evaluate_trade, gate_status, size_position
from atlas.sessions import session_info
from atlas.trading_config import RiskLimits, TradingConfig

NOW = datetime(2026, 11, 17, 14, 0, tzinfo=timezone.utc)  # London/NY overlap, Tuesday
MIDS = {"EURUSD": 1.10, "GBPUSD": 1.27, "USDJPY": 150.0, "AUDUSD": 0.65, "NZDUSD": 0.60, "USDCAD": 1.37, "USDCHF": 0.88, "XAUUSD": 3800.0}


def ctx(**kw):
    base = dict(equity=10_000, balance=10_000, margin_used=0, start_of_day_equity=10_000, start_of_week_equity=10_000, open_positions=[],
                trades_today=0, consecutive_losses=0, last_loss_at=None, now=NOW)
    base.update(kw)
    return RiskContext(**base)


def req(symbol="EURUSD", side="buy", entry=1.10010, stop=1.09810, target=1.10410, spread=0.00012, **kw):
    inst = get(symbol)
    base = dict(symbol=symbol, side=side, entry=entry, stop=stop, target=target, spread_price=spread, mids=MIDS,
                session=session_info(NOW, inst.currencies, inst.asset_class))
    base.update(kw)
    return TradeRequest(**base)


def failed(d):
    return {c["name"] for c in d.checks if not c["passed"]}


def test_eurusd_sizing_from_pip_value_and_stop():
    d = evaluate_trade(TradingConfig(), ctx(), req())
    assert d.approved, d.blocking
    sz = d.sizing
    # risk $50; stop 20 pips + 0.4 pip stop slippage; $10/pip/lot; $7 commission/lot round trip → 0.23 lots
    assert sz.stop_pips == pytest.approx(20.0)
    assert sz.lots == pytest.approx(0.23)
    assert sz.risk_amount <= 50.0 and sz.risk_amount > 45
    assert sz.net_rr >= 2.0 - 1e-6


def test_gold_sizing_and_margin():
    d = evaluate_trade(TradingConfig(), ctx(), req("XAUUSD", "sell", entry=3800.00, stop=3808.00, target=3784.0, spread=0.35))
    assert d.approved, d.blocking
    sz = d.sizing
    # 80 pips stop ($0.10 pip) ; $10/pip/lot → ~$830/lot incl. slippage/commission → 0.06 lots
    assert sz.lots == pytest.approx(0.05)  # 83 pips (incl. stop slippage) × $10 + $7 commission = $837/lot → 0.0597 floored
    assert sz.margin_usd == pytest.approx(0.05 * 100 * 3800 * 0.05, rel=1e-6)


def test_jpy_cross_uses_conversion():
    d = evaluate_trade(TradingConfig(), ctx(), req("GBPJPY", "buy", entry=190.500, stop=190.200, target=191.300, spread=0.030))
    assert d.sizing.pip_value_usd == pytest.approx(1000 / 150.0)


def test_target_raised_for_net_rr():
    d = evaluate_trade(TradingConfig(), ctx(), req(target=1.10411))
    assert d.sizing.target > 1.10411 or d.sizing.net_rr >= 2


def test_hard_limits():
    for kw in ({"risk_per_trade_pct": 1.5}, {"max_daily_loss_pct": 3}, {"max_weekly_loss_pct": 6}, {"max_open_positions": 4}, {"min_risk_reward": 1.5},
               {"max_effective_leverage": 50}):
        with pytest.raises(ValidationError):
            RiskLimits(**kw)
    with pytest.raises(ValidationError):
        TradingConfig(symbols=["BTCUSD"])
    with pytest.raises(ValidationError):
        RiskLimits(spread_limits_pips={"ETHUSD": 1})


def test_daily_and_weekly_loss_limits():
    assert "daily_loss_limit" in failed(evaluate_trade(TradingConfig(), ctx(equity=9_790), req()))
    d = evaluate_trade(TradingConfig(), ctx(equity=9_480, start_of_day_equity=9_480), req())
    assert "weekly_loss_limit" in failed(d) and d.halt == "weekly_loss_limit"


def test_kill_switch_and_disable():
    assert "kill_switch" in failed(gate_status(TradingConfig(kill_switch=True), ctx()))
    assert "trading_enabled" in failed(gate_status(TradingConfig(trading_enabled=False), ctx()))


def test_max_positions_and_currency_exposure():
    ops = [OpenExposure("GBPUSD", "buy", 0.2, 25_000, 50, 800), OpenExposure("AUDUSD", "buy", 0.3, 20_000, 50, 1000)]
    d = evaluate_trade(TradingConfig(), ctx(open_positions=ops), req())  # third trade short USD → USD -$150 risk
    assert "currency_exposure" in failed(d)
    ops3 = ops + [OpenExposure("USDJPY", "buy", 0.1, 10_000, 50, 300)]
    assert "max_open_positions" in failed(evaluate_trade(TradingConfig(), ctx(open_positions=ops3), req()))
    # an offsetting trade (long USD) is allowed
    d = evaluate_trade(TradingConfig(), ctx(open_positions=ops), req("USDCHF", "buy", entry=0.88010, stop=0.87810, target=0.88500))
    assert "currency_exposure" not in failed(d)


def test_spread_slippage_news_session_and_rollover():
    d = evaluate_trade(TradingConfig(), ctx(), req(spread=0.00030))
    assert "spread" in failed(d)
    ev = EconEvent("Non-Farm Employment Change", "USD", NOW + timedelta(minutes=10), "High")
    assert "news_blackout" in failed(evaluate_trade(TradingConfig(), ctx(), req(news_event=ev)))
    asia = datetime(2026, 11, 17, 2, 0, tzinfo=timezone.utc)
    inst = get("EURUSD")
    d = evaluate_trade(TradingConfig(), ctx(now=asia), req(session=session_info(asia, inst.currencies, "forex")))
    assert "trading_session" in failed(d)
    jpy = get("USDJPY")  # Asia pairs may trade in Tokyo
    d = evaluate_trade(TradingConfig(), ctx(now=asia), req("USDJPY", entry=150.010, stop=149.810, target=150.500, spread=0.012,
                                                           session=session_info(asia, jpy.currencies, "forex")))
    assert "trading_session" not in failed(d)
    roll = datetime(2026, 11, 17, 22, 2, tzinfo=timezone.utc)
    d = evaluate_trade(TradingConfig(), ctx(now=roll), req(session=session_info(roll, inst.currencies, "forex")))
    assert "rollover_window" in failed(d)


def test_mandatory_stop_both_sides():
    assert "mandatory_stop" in failed(evaluate_trade(TradingConfig(), ctx(), req(stop=1.1010)))
    assert "mandatory_stop" in failed(evaluate_trade(TradingConfig(), ctx(), req(side="sell", entry=1.1, stop=1.099)))


def test_size_never_increases_after_losses():
    cfg, eu = TradingConfig(), get("EURUSD")
    a = size_position(cfg, eu, "buy", 10_000, 0, 0, 0, 1.1, 1.098, 1.104, 0.0001, MIDS)
    b = size_position(cfg, eu, "buy", 10_000, 0, 0, 2, 1.1, 1.098, 1.104, 0.0001, MIDS)
    c = size_position(cfg, eu, "buy", 9_000, 0, 0, 0, 1.1, 1.098, 1.104, 0.0001, MIDS)
    assert b.lots < a.lots and c.lots < a.lots and b.risk_amount <= a.risk_amount / 2 + 1e-9


def test_min_lot_and_leverage_caps():
    d = evaluate_trade(TradingConfig(), ctx(equity=300, balance=300, start_of_day_equity=300, start_of_week_equity=300), req())
    assert "min_lot" in failed(d)
    cfg = TradingConfig.model_validate({"risk": {"max_effective_leverage": 2}})
    sz = size_position(cfg, get("EURUSD"), "buy", 10_000, 0, 0, 0, 1.1, 1.0999, 1.1003, 0.0, MIDS)  # 1-pip stop → huge size
    assert sz.notional_usd <= 2 * 10_000 + 1e-6 and any("leverage" in n for n in sz.notes)
