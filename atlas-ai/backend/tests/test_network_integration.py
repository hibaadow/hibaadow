"""Opt-in integration tests against REAL public data (ATLAS_NETWORK_TESTS=1). Uses the test database only.

The trade 'proposals' here are explicit test fixtures used to exercise the paper execution path with
live gold/forex quotes; nothing is written to the production database.
"""
import asyncio
import os

import pytest

from atlas.brokers.public import PublicSource
from atlas.db import session_scope
from atlas.econ import EconService
from atlas.execution.paper import PaperExecutor
from atlas.instruments import CONVERSION_PAIRS, INSTRUMENTS
from atlas.portfolio import get_account
from atlas.trading_config import TradingConfig

pytestmark = pytest.mark.skipif(os.environ.get("ATLAS_NETWORK_TESTS") != "1", reason="set ATLAS_NETWORK_TESTS=1 to hit live public APIs")


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def test_live_quotes_for_gold_and_forex():
    async def go():
        src = PublicSource()
        try:
            qs = await src.quotes(list(INSTRUMENTS))
        finally:
            await src.close()
        assert set(qs) == set(INSTRUMENTS), f"missing quotes: {set(INSTRUMENTS) - set(qs)}"
        for sym, q in qs.items():
            inst = INSTRUMENTS[sym]
            assert q.ask >= q.bid > 0
            assert inst.to_pips(q.ask - q.bid) < 50, f"{sym} spread implausible"
        assert 500 < qs["XAUUSD"].mid < 20_000 and 0.5 < qs["EURUSD"].mid < 2
        return qs

    run(go())


@pytest.mark.parametrize("sym,side", [("XAUUSD", "buy"), ("XAUUSD", "sell"), ("EURUSD", "buy"), ("USDJPY", "sell"), ("EURGBP", "buy")])
def test_paper_round_trip_on_live_quotes(sym, side):
    async def go():
        src = PublicSource()
        try:
            qs = await src.quotes([sym, *CONVERSION_PAIRS.values()])
            mids = {s: q.mid for s, q in qs.items()}
            q = qs[sym]
            inst = INSTRUMENTS[sym]
            sg = 1 if side == "buy" else -1
            ref = q.ask if side == "buy" else q.bid
            stop = inst.round_price(ref - sg * 200 * inst.pip_size)
            with session_scope() as db:
                acct = get_account(db, "paper", 10_000)
                ex = PaperExecutor(TradingConfig().costs)
                pos, _ = ex.open_position(db, acct, symbol=sym, side=side, strategy="integration_test", lots=0.1, stop=stop,
                                          tp1=inst.round_price(ref + sg * 400 * inst.pip_size), tp2=None, quote=q, mids=mids,
                                          candle_time=hash((sym, side)) % 10**9, decision_id=None, risk_amount=20.0, reason="integration test fixture")
                assert sg * (pos.entry_price - ref) >= 0, "fills are never better than the executable side"
                q2 = (await src.quotes([sym]))[sym]
                ex.close_position(db, acct, pos, q2, mids, "integration test close")
                assert pos.status == "closed" and pos.commission > 0
                # P&L in USD = side × price change × lots × contract × quote→USD rate − commission
                assert acct.cash == pytest.approx(10_000 + pos.net_pnl, abs=1e-6)
                assert abs(pos.net_pnl) < 500
        finally:
            await src.close()

    run(go())


def test_calendar_and_yields_live():
    async def go():
        e = EconService()
        try:
            await e.refresh(force=True)
        finally:
            await e.close()
        assert e.events, "economic calendar empty"
        assert all(ev.currency in ("USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF", "ALL") for ev in e.events)
        assert e.us10y and 0 < e.us10y["value"] < 20

    run(go())
