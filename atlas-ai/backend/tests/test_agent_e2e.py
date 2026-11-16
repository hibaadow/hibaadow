"""End-to-end paper-trading workflow through the real agent, with a deterministic market-data feed."""
import asyncio
import time

import numpy as np
import pytest
from sqlalchemy import select

from atlas.agent import TradingAgent
from atlas.db import session_scope
from atlas.decision import BUY, Evaluation
from atlas.marketdata.service import MarketDataService
from atlas.marketdata.types import Depth, MarketStats, Quote
from atlas.models import ActivityEvent, Command, Decision, Position, PortfolioSnapshot, RiskEvent
from atlas.portfolio import get_account
from atlas.strategies.base import Signal
from atlas.trading_config import load_config, save_config
from tests.conftest import make_series


class FakeMD(MarketDataService):
    def __init__(self, symbols):
        super().__init__(symbols, use_ws=False)
        n = 600
        step = 300_000
        start = (int(time.time() * 1000) // step - n) * step
        closes = 100 * np.exp(np.cumsum(np.random.default_rng(1).normal(0, 0.003, n)))
        for sym in symbols:
            st = self.state[sym]
            for tf, stp in (("5m", 300_000), ("1m", 60_000), ("1h", 3_600_000), ("4h", 14_400_000)):
                s0 = (int(time.time() * 1000) // stp - n) * stp
                _, cs = make_series(closes, symbol=sym, tf=tf, start=s0, vol=np.full(n, 50_000.0))
                st.candles[tf] = cs
                st.quality[tf] = {"usable": True, "issues": []}
            st.stats = MarketStats(sym, "test", 1.0, 1e7, 1e9, 110, 90)
            st.depth = Depth(sym, 5e6, 5e6)
        self.set_price(100.0)

    def set_price(self, bid, sym="SOLUSDC"):
        self.state[sym].quote = Quote(sym, "test", bid, bid * 1.0001, bid)

    async def refresh_quotes(self):  # keep injected prices fresh
        for st in self.state.values():
            if st.quote:
                st.quote.ts = time.time()

    async def refresh_candles(self, *a, **k):
        return None


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def make_agent(**cfg_updates):
    with session_scope() as db:
        cfg = load_config(db)
        cfg = cfg.model_copy(update={"symbols": ["SOLUSDC", "BTCUSDC"], **cfg_updates})
        cfg.automation.auto_paper_trading = True
        cfg.min_liquidity_usd = 100_000
        save_config(db, cfg)
    return TradingAgent(market=FakeMD(["SOLUSDC", "BTCUSDC"]))


def long_signal(candle=1, stop=98.0):
    return Signal("momentum", "SOLUSDC", "5m", "long", candle, 100.0, stop, [104.0, 106.0], 0.8, {}, ["test setup"])


async def trade(agent, candle=1, stop=98.0):
    with session_scope() as db:
        cfg = agent.reload_config(db)
        acct = get_account(db, "paper", cfg.paper_starting_capital)
        d = Decision(symbol="SOLUSDC", strategy="momentum", classification=BUY, confidence=70, explanation="t")
        db.add(d)
        db.flush()
        ev = Evaluation(BUY, 70, {}, [], "test", True)
        ready = agent.md.readiness("SOLUSDC", ("5m",), 30, 1.5)
        await agent._maybe_trade(db, cfg, acct, "SOLUSDC", long_signal(candle, stop), ev, d, ready, None)
        return d.id


def positions(status=None):
    with session_scope() as db:
        q = select(Position)
        if status:
            q = q.where(Position.status == status)
        return db.execute(q).scalars().all()


def test_paper_workflow_open_monitor_stop_out():
    agent = make_agent()

    async def flow():
        did = await trade(agent)
        (p,) = positions("open")
        assert p.qty > 0 and p.stop_price == 98.0
        agent.md.set_price(102.5)  # +1R → breakeven
        await agent.fast_tick()
        (p,) = positions("open")
        assert p.stop_price > p.entry_price
        agent.md.set_price(99.0)  # through the breakeven stop
        await agent.fast_tick()
        (p,) = positions("closed")
        with session_scope() as db:
            d = db.get(Decision, did)
            assert d.executed and d.outcome in ("win", "loss", "flat")
            kinds = [e.kind for e in db.execute(select(ActivityEvent)).scalars()]
            assert "execution" in kinds and "stop_adjust" in kinds
            assert db.execute(select(PortfolioSnapshot)).first() is not None

    run(flow())


def test_duplicate_signal_does_not_double_trade():
    agent = make_agent()

    async def flow():
        await trade(agent, candle=7)
        await trade(agent, candle=7)
        assert len(positions()) == 1

    run(flow())


def test_kill_switch_blocks_new_orders_and_flattens():
    agent = make_agent()

    async def flow():
        await trade(agent, candle=1)
        with session_scope() as db:
            cfg = load_config(db)
            cfg.kill_switch = True
            cfg.kill_switch_action = "flatten"
            save_config(db, cfg)
        await agent.fast_tick()
        assert positions("open") == [] and len(positions("closed")) == 1
        did = await trade(agent, candle=2)
        with session_scope() as db:
            d = db.get(Decision, did)
            assert not d.executed and "kill_switch" in d.rejected_reason
            assert db.execute(select(RiskEvent).where(RiskEvent.kind == "kill_switch_flatten")).first()

    run(flow())


def test_kill_switch_keep_protective_still_monitors_stops():
    agent = make_agent()

    async def flow():
        await trade(agent, candle=1)
        with session_scope() as db:
            cfg = load_config(db)
            cfg.kill_switch = True
            cfg.automation.scanning_enabled = False
            save_config(db, cfg)
        await agent.fast_tick()
        assert len(positions("open")) == 1  # kept, protected
        agent.md.set_price(97.0)
        await agent.fast_tick()
        assert len(positions("closed")) == 1  # stop still enforced while paused + killed

    run(flow())


def test_daily_loss_limit_stops_new_positions():
    agent = make_agent()

    async def flow():
        with session_scope() as db:
            acct = get_account(db, "paper", 10_000)
            acct.cash = 9_700  # -3% vs start-of-day snapshot below
            from datetime import datetime, timedelta, timezone
            db.add(PortfolioSnapshot(account_id=acct.id, ts=datetime.now(timezone.utc).replace(hour=0, minute=0) - timedelta(seconds=1),
                                     equity=10_000, cash=10_000, positions_value=0, unrealized=0, realized_total=0))
        await agent.fast_tick()
        did = await trade(agent, candle=3)
        with session_scope() as db:
            d = db.get(Decision, did)
            assert not d.executed and "daily_loss_limit" in d.rejected_reason
            assert db.execute(select(RiskEvent).where(RiskEvent.kind == "daily_loss_limit")).first()
        assert positions() == []

    run(flow())


def test_stale_data_blocks_trading():
    agent = make_agent()

    async def flow():
        agent.md.state["SOLUSDC"].quote.ts = time.time() - 600
        did = await trade(agent, candle=4)
        with session_scope() as db:
            assert "market_data" in db.get(Decision, did).rejected_reason

    run(flow())


def test_manual_close_command():
    agent = make_agent()

    async def flow():
        await trade(agent, candle=5)
        (p,) = positions("open")
        with session_scope() as db:
            db.add(Command(kind="close_position", payload={"position_id": p.id}, requested_by="tester"))
        await agent.fast_tick()
        (p,) = positions("closed")
        assert "manual close" in p.exit_reason

    run(flow())


def test_scan_once_runs_strategies_on_closed_data():
    agent = make_agent()

    async def flow():
        await agent.scan_once()
        with session_scope() as db:
            from atlas.models import AppSetting
            snap = db.get(AppSetting, "scanner_snapshot").value
            rows = {r["symbol"]: r for r in snap["rows"]}
            assert rows["SOLUSDC"]["rsi"] is not None and rows["SOLUSDC"]["signal"]
            assert db.execute(select(ActivityEvent).where(ActivityEvent.kind == "scan")).first()

    run(flow())
