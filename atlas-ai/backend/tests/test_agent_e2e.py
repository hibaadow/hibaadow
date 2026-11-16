"""End-to-end paper-trading workflow for XAU/USD and forex through the real agent (deterministic feed & clock)."""
import asyncio
import time
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import select

from atlas.agent import TradingAgent
from atlas.db import session_scope
from atlas.decision import BUY, SELL, Evaluation
from atlas.econ import EconEvent
from atlas.marketdata.service import MarketDataService
from atlas.marketdata.types import Quote
from atlas.models import ActivityEvent, AppSetting, Command, Decision, Position, PortfolioSnapshot, RiskEvent
from atlas.portfolio import get_account
from atlas.strategies.base import Signal
from atlas.trading_config import load_config, save_config
from tests.conftest import make_series

NOW = datetime(2026, 11, 17, 14, 0, tzinfo=timezone.utc)  # Tuesday, London/NY overlap
PRICES = {"XAUUSD": (3800.00, 3800.35), "EURUSD": (1.10000, 1.10010), "GBPUSD": (1.27000, 1.27012), "USDJPY": (150.000, 150.012),
          "AUDUSD": (0.65000, 0.65012), "NZDUSD": (0.60000, 0.60015), "USDCAD": (1.37000, 1.37015), "USDCHF": (0.88000, 0.88015), "GBPJPY": (190.480, 190.500), "EURGBP": (0.86600, 0.86610), "EURJPY": (165.0, 165.02)}


class NoNetSource:
    name = "test"

    async def quotes(self, symbols):
        return {}

    async def candles(self, *a, **k):
        return []

    def health(self):
        return {}

    async def close(self):
        pass


class FakeMD(MarketDataService):
    def __init__(self, symbols):
        super().__init__(symbols, NoNetSource())
        for sym in self.state:
            p0 = sum(PRICES.get(sym, (1.0, 1.0))) / 2
            for tf, step in (("5m", 300_000), ("1m", 60_000), ("15m", 900_000), ("1h", 3_600_000), ("4h", 14_400_000)):
                start = int(NOW.timestamp() * 1000) // step * step - 400 * step
                closes = p0 * np.exp(np.cumsum(np.random.default_rng(1).normal(0, 0.0004, 400)))
                _, cs = make_series(closes, symbol=sym, tf=tf, start=start)
                self.state[sym].candles[tf] = cs
                self.state[sym].quality[tf] = {"usable": True, "issues": []}
            bid, ask = PRICES.get(sym, (p0, p0 * 1.0001))
            self.set_quote(sym, bid, ask)

    def set_quote(self, sym, bid, ask):
        self.state[sym].quote = Quote(sym, "test", bid, ask, (bid + ask) / 2)

    async def refresh_quotes(self):
        for st in self.state.values():
            if st.quote:
                st.quote.ts = time.time()

    async def refresh_candles(self, *a, **k):
        return None


class FakeEcon:
    def __init__(self, events=()):
        self.events = list(events)
        self.us10y = {"trend": "falling", "value": 4.1}
        self.events_fetched = time.time()

    async def refresh(self, force=False):
        pass

    async def close(self):
        pass


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def make_agent(events=(), clock=NOW, **cfg_updates):
    with session_scope() as db:
        cfg = load_config(db).model_copy(update=cfg_updates)
        cfg.automation.auto_trading = True
        save_config(db, cfg)
    a = TradingAgent(market=FakeMD(load_config_symbols()), econ=FakeEcon(events))
    a.clock = lambda: clock
    return a


def load_config_symbols():
    with session_scope() as db:
        return load_config(db).symbols


async def propose(agent, sym, side, entry, stop, t1, t2, candle=1, strategy="trend_pullback", conf=70):
    with session_scope() as db:
        cfg = agent.reload_config(db)
        acct = get_account(db, cfg.mode, cfg.paper_starting_capital)
        d = Decision(symbol=sym, strategy=strategy, classification=BUY if side == "buy" else SELL, confidence=conf, explanation="t", direction=side.upper())
        db.add(d)
        db.flush()
        sig = Signal(strategy, sym, "5m", side, candle, entry, stop, [t1, t2], 0.8, {}, ["test setup"],
                     [{"category": c, "detail": c} for c in ("trend", "structure", "momentum")], ["close beyond stop"])
        from atlas.sessions import session_info
        from atlas.instruments import INSTRUMENTS
        inst = INSTRUMENTS[sym]
        sess = session_info(agent.clock(), inst.currencies if inst.asset_class == "forex" else ("XAU", "USD"), inst.asset_class)
        ready = agent.md.readiness(sym, ("5m",), 30, 15, min_bars=100, now=agent.clock())
        news = agent._news(sym, cfg, agent.clock())
        await agent._maybe_trade(db, cfg, acct, sym, sig, Evaluation(d.classification, conf, {}, [], "t", True), d, ready, sess, news)
        return d.id


def positions(status=None):
    with session_scope() as db:
        q = select(Position)
        if status:
            q = q.where(Position.status == status)
        return db.execute(q).scalars().all()


def decision(did):
    with session_scope() as db:
        return db.get(Decision, did)


def test_gold_paper_workflow_open_breakeven_stop():
    agent = make_agent()

    async def flow():
        did = await propose(agent, "XAUUSD", "buy", 3800.35, 3792.00, 3817.0, 3825.0)
        d = decision(did)
        assert d.executed, d.rejected_reason
        assert d.lots and d.est_costs["total_usd"] > 0 and d.risk_reward >= 2
        (p,) = positions("open")
        assert p.side == "buy" and p.entry_price > 3800.35 and p.qty == d.lots
        agent.md.set_quote("XAUUSD", 3809.5, 3809.85)  # beyond +1R → breakeven
        await agent.fast_tick()
        (p,) = positions("open")
        assert p.stop_price > p.entry_price
        agent.md.set_quote("XAUUSD", 3799.0, 3799.35)  # through breakeven stop
        await agent.fast_tick()
        (p,) = positions("closed")
        with session_scope() as db:
            kinds = {e.kind for e in db.execute(select(ActivityEvent)).scalars()}
            assert {"execution", "stop_adjust"} <= kinds
            assert db.execute(select(PortfolioSnapshot)).first() is not None
            assert db.get(AppSetting, "market_quotes").value["XAUUSD"]["bid"] == 3799.0

    run(flow())


def test_forex_sell_workflow_take_profits():
    agent = make_agent()

    async def flow():
        did = await propose(agent, "EURUSD", "sell", 1.10000, 1.10200, 1.09550, 1.09400)
        assert decision(did).executed, decision(did).rejected_reason
        (p,) = positions("open")
        assert p.side == "sell" and p.entry_price < 1.10000
        tp1 = p.tp1
        agent.md.set_quote("EURUSD", tp1 - 0.00030, tp1 - 0.00020)
        await agent.fast_tick()
        (p,) = positions("open")
        assert p.tp1_hit and p.qty < p.initial_qty
        agent.md.set_quote("EURUSD", p.tp2 - 0.00030, p.tp2 - 0.00020)
        await agent.fast_tick()
        (p,) = positions("closed")
        assert p.net_pnl > 0

    run(flow())


def test_duplicate_signal_single_order():
    agent = make_agent()

    async def flow():
        await propose(agent, "EURUSD", "buy", 1.1001, 1.0981, 1.1045, 1.1060, candle=9)
        await propose(agent, "EURUSD", "buy", 1.1001, 1.0981, 1.1045, 1.1060, candle=9)
        assert len(positions()) == 1

    run(flow())


def test_news_blackout_blocks_entry():
    nfp = EconEvent("Non-Farm Employment Change", "USD", NOW + timedelta(minutes=15), "High")
    agent = make_agent(events=[nfp])

    async def flow():
        did = await propose(agent, "XAUUSD", "sell", 3800.0, 3808.0, 3783.0, 3775.0)
        assert "news_blackout" in decision(did).rejected_reason
        did = await propose(agent, "EURGBP", "buy", 0.86610, 0.86410, 0.87050, 0.87200)  # no USD exposure → allowed
        assert "news_blackout" not in (decision(did).rejected_reason or "")

    run(flow())


def test_kill_switch_flatten_and_block():
    agent = make_agent()

    async def flow():
        await propose(agent, "EURUSD", "buy", 1.1001, 1.0981, 1.1045, 1.1060)
        with session_scope() as db:
            cfg = load_config(db)
            cfg.kill_switch, cfg.kill_switch_action = True, "flatten"
            save_config(db, cfg)
        await agent.fast_tick()
        assert positions("open") == []
        did = await propose(agent, "GBPUSD", "buy", 1.27012, 1.26812, 1.27500, 1.27700, candle=2)
        assert "kill_switch" in decision(did).rejected_reason
        with session_scope() as db:
            assert db.execute(select(RiskEvent).where(RiskEvent.kind == "kill_switch_flatten")).first()

    run(flow())


def test_kill_switch_keep_protective_still_enforces_stop():
    agent = make_agent()

    async def flow():
        await propose(agent, "USDJPY", "buy", 150.012, 149.812, 150.500, 150.700)
        with session_scope() as db:
            cfg = load_config(db)
            cfg.kill_switch = True
            cfg.automation.scanning_enabled = False
            save_config(db, cfg)
        await agent.fast_tick()
        assert len(positions("open")) == 1
        agent.md.set_quote("USDJPY", 149.700, 149.712)
        await agent.fast_tick()
        assert len(positions("closed")) == 1

    run(flow())


def test_daily_loss_limit():
    agent = make_agent()

    async def flow():
        with session_scope() as db:
            acct = get_account(db, "paper", 10_000)
            acct.cash = 9_700
            db.add(PortfolioSnapshot(account_id=acct.id, ts=NOW.replace(hour=0) - timedelta(minutes=1), equity=10_000, cash=10_000,
                                     positions_value=0, unrealized=0, realized_total=0))
        await agent.fast_tick()
        did = await propose(agent, "EURUSD", "buy", 1.1001, 1.0981, 1.1045, 1.1060)
        assert "daily_loss_limit" in decision(did).rejected_reason
        with session_scope() as db:
            assert db.execute(select(RiskEvent).where(RiskEvent.kind == "daily_loss_limit")).first()

    run(flow())


def test_weekend_flattening():
    fri = datetime(2026, 11, 20, 21, 40, tzinfo=timezone.utc)  # Friday 16:40 New York
    agent = make_agent(clock=fri)

    async def flow():
        agent.clock = lambda: NOW
        await propose(agent, "EURUSD", "buy", 1.1001, 1.0981, 1.1045, 1.1060)
        agent.clock = lambda: fri
        await agent.fast_tick()
        (p,) = positions("closed")
        assert "weekend" in p.exit_reason

    run(flow())


def test_market_closed_blocks_entries():
    sat = datetime(2026, 11, 21, 12, tzinfo=timezone.utc)
    agent = make_agent(clock=sat)

    async def flow():
        did = await propose(agent, "EURUSD", "buy", 1.1001, 1.0981, 1.1045, 1.1060)
        assert "market_open" in decision(did).rejected_reason

    run(flow())


def test_demo_mode_without_broker_is_blocked():
    agent = make_agent(mode="demo")

    async def flow():
        did = await propose(agent, "EURUSD", "buy", 1.1001, 1.0981, 1.1045, 1.1060)
        assert "no broker configured" in decision(did).rejected_reason
        assert positions() == []

    run(flow())


def test_manual_close_command_and_scan():
    agent = make_agent()

    async def flow():
        await propose(agent, "GBPJPY", "sell", 190.500, 190.800, 189.700, 189.400)
        (p,) = positions("open")
        with session_scope() as db:
            db.add(Command(kind="close_position", payload={"position_id": p.id}, requested_by="tester"))
        await agent.fast_tick()
        (p,) = positions("closed")
        assert "manual close" in p.exit_reason
        await agent.scan_once()
        with session_scope() as db:
            snap = db.get(AppSetting, "analysis_snapshot").value
            syms = {r["symbol"] for r in snap["rows"]}
            assert "XAUUSD" in syms and "EURUSD" in syms and not any("BTC" in s for s in syms)
            assert "USD" in snap["strength"]

    run(flow())
