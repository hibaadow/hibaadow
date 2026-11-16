"""Opt-in integration tests against REAL public market data (run with ATLAS_NETWORK_TESTS=1).

They use the test database only. The 'signal' here is an explicit test fixture used to exercise
the execution path with live quotes — it is never written to the production database.
"""
import asyncio
import os
import time

import pytest
from sqlalchemy import select

from atlas.db import session_scope
from atlas.execution.paper import PaperExecutor
from atlas.marketdata.service import MarketDataService
from atlas.models import Execution
from atlas.portfolio import get_account
from atlas.strategies.token_scanner import TokenScanner
from atlas.trading_config import TradingConfig

pytestmark = pytest.mark.skipif(os.environ.get("ATLAS_NETWORK_TESTS") != "1", reason="set ATLAS_NETWORK_TESTS=1 to hit live APIs")


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def test_live_market_data_is_valid_and_fresh():
    async def go():
        md = MarketDataService(["SOLUSDC", "BTCUSDC"], use_ws=False)
        try:
            await md.refresh_quotes()
            await md.refresh_stats()
            await md.refresh_depth("SOLUSDC")
            await md.refresh_candles("SOLUSDC", ("1m", "5m", "1h"))
            r = md.readiness("SOLUSDC", ("1m", "5m", "1h"), 30, 1.5)
            assert r.ok, r.reasons
            st = md.state["SOLUSDC"]
            assert st.quote.ask >= st.quote.bid > 0 and st.stats.volume_quote_24h > 0 and st.depth.liquidity_usd > 0
            assert len(st.candles["5m"]) >= 400 and st.quality["5m"]["missing_bars"] == 0
        finally:
            await md.stop()

    run(go())


def test_paper_fill_against_live_quote():
    async def go():
        md = MarketDataService(["SOLUSDC"], use_ws=False)
        try:
            await md.refresh_quotes()
            await md.refresh_candles("SOLUSDC", ("1m",))
            st = md.state["SOLUSDC"]
            q = st.quote
            mqv = sum(c.quote_volume for c in st.candles["1m"][-5:]) / 5
            with session_scope() as db:
                acct = get_account(db, "paper", 10_000)
                ex = PaperExecutor(TradingConfig().fees)
                pos, ev = ex.open_position(db, acct, symbol="SOLUSDC", strategy="integration_test", qty=1.0, entry_ref=q.ask,
                                           stop=q.bid * 0.98, tp1=q.ask * 1.05, tp2=q.ask * 1.08, quote=q, minute_qv=mqv,
                                           candle_time=int(time.time()), decision_id=None, risk_amount=2.0, reason="integration test fixture")
                fill = db.execute(select(Execution)).scalars().first()
                assert fill.price >= q.ask and fill.reference_price == q.ask
                await md.refresh_quotes()
                ev = ex.close_position(db, acct, pos, md.state["SOLUSDC"].quote, mqv, "integration test close")
                assert pos.status == "closed" and pos.fees_paid > 0
                assert acct.cash == pytest.approx(10_000 + pos.net_pnl, abs=1e-6)
        finally:
            await md.stop()

    run(go())


def test_token_scanner_live():
    async def go():
        sc = TokenScanner()
        try:
            reports = await sc.scan(limit=3)
            assert reports, "no tokens discovered"
            for r in reports:
                assert r.risk_level in ("moderate", "elevated", "high", "extreme")
                assert "liquidity_lock" in r.checks
        finally:
            await sc.close()

    run(go())
