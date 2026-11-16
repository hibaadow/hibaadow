"""The ATLAS trading agent: orchestrates market data → strategies → AI decision →
risk → execution → monitoring, and narrates every step to the activity feed.

Loops
-----
* fast loop (~3s): quotes, position monitoring (ALWAYS runs, even when scanning
  is paused or the kill switch is engaged), operator commands, heartbeat
* scan loop (configurable): candle refresh, strategy evaluation, decisions, entries
* slow loop (60s): 24h stats, depth, persistence, integration health, snapshots
* token loop (configurable): Solana new-token safety scanner (never trades)
"""
from __future__ import annotations

import asyncio
import time
import traceback
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from .commentary import Commentator
from .db import session_scope
from .decision import EXIT, MarketContext, PortfolioContext, evaluate, strategy_track_record
from .events import get_bus
from .execution.costs import estimate
from .execution.live import JupiterLiveExecutor, preflight
from .execution.paper import ExecEvent, PaperExecutor
from .logging import get_logger
from .marketdata.http import ProviderClient, ProviderError
from .marketdata.providers import split_symbol
from .marketdata.service import MarketDataService
from .models import ActivityEvent, AppSetting, Command, Decision, IntegrationStatus, Position, RiskEvent, Signal, StrategyConfig, TokenScan
from .portfolio import get_account, mark, open_positions, risk_context, snapshot
from .risk import TradeRequest, evaluate_trade, gate_status
from .strategies.base import StrategyContext, htf_trend
from .strategies.library import STRATEGIES, build
from .strategies.token_scanner import TokenScanner
from .trading_config import TradingConfig, load_config, save_config
from . import indicators as ind

log = get_logger("atlas.agent")
REGIME_SYMBOL = "BTCUSDC"
FAST_INTERVAL = 3.0


def utcnow():
    return datetime.now(timezone.utc)


def put_setting(db, key: str, value) -> None:
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=value))
    else:
        row.value = value


class TradingAgent:
    def __init__(self, market: MarketDataService | None = None):
        with session_scope() as db:
            self.cfg = load_config(db)
            get_account(db, "paper", self.cfg.paper_starting_capital)
        syms = self._universe(self.cfg)
        self.md = market or MarketDataService(syms)
        self.paper = PaperExecutor(self.cfg.fees)
        self.live: JupiterLiveExecutor | None = None
        self.scanner = TokenScanner()
        self.commentator = Commentator()
        self.dex = ProviderClient("dexscreener_enrich", "https://api.dexscreener.com", rate_per_sec=0.5, burst=2)
        self.bus = get_bus()
        self.lock = asyncio.Lock()
        self._tasks: list[asyncio.Task] = []
        self._evaluated: dict[tuple[str, str], int] = {}
        self._scanner_rows: dict[str, dict] = {}
        self._market_caps: dict[str, dict] = {}
        self._halt_notified: dict[str, str] = {}
        self._flattened = False
        self._paused_notified = False
        self._last_snapshot = 0.0
        self._started = time.time()
        self.cycle = 0
        self.last_scan: float | None = None
        self.last_error: str | None = None

    @staticmethod
    def _universe(cfg: TradingConfig) -> list[str]:
        syms = list(cfg.symbols)
        if REGIME_SYMBOL not in syms:
            syms.append(REGIME_SYMBOL)
        return syms

    # ------------------------------------------------------------- utilities
    async def publish(self, kind: str, payload: dict) -> None:
        await self.bus.publish({"type": kind, "ts": utcnow().isoformat(), "data": payload})

    def activity(self, db, kind: str, message: str, symbol: str | None = None, explanation: str | None = None, data: dict | None = None):
        ev = ActivityEvent(kind=kind, symbol=symbol, message=message, explanation=explanation, data=data or {})
        db.add(ev)
        db.flush()
        payload = {"id": ev.id, "ts": ev.ts.isoformat(), "kind": kind, "symbol": symbol, "message": message,
                   "explanation": explanation, "data": data or {}}
        asyncio.get_event_loop().create_task(self.publish("activity", payload))
        return ev

    def risk_event(self, db, kind: str, severity: str, message: str, data: dict | None = None):
        db.add(RiskEvent(kind=kind, severity=severity, message=message, data=data or {}))
        self.activity(db, "risk", message, data={"risk_kind": kind, "severity": severity, **(data or {})})

    def minute_qv(self, symbol: str) -> float | None:
        st = self.md.state.get(symbol)
        if not st or "1m" not in st.candles or not st.candles["1m"]:
            return None
        tail = st.candles["1m"][-5:]
        return sum(c.quote_volume for c in tail) / len(tail)

    def prices(self) -> dict[str, float]:
        return {s: st.quote.bid for s, st in self.md.state.items() if st.quote}

    # ------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        self.md.start_feeds()
        with session_scope() as db:
            self.activity(db, "system", f"ATLAS agent started in {self.cfg.mode.upper()} mode — universe: {', '.join(self.cfg.symbols)}",
                          explanation="Paper trading is the default. Live execution requires explicit operator and admin activation.")
        for coro, name in ((self._fast_loop(), "fast"), (self._scan_loop(), "scan"), (self._slow_loop(), "slow"), (self._token_loop(), "tokens")):
            self._tasks.append(asyncio.create_task(self._guard(coro, name), name=f"agent-{name}"))

    async def _guard(self, coro, name):
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            self.last_error = traceback.format_exc()[-2000:]
            log.error("agent loop crashed", extra={"data": {"loop": name, "error": self.last_error}})
            raise

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self.md.stop()
        await self.scanner.close()
        await self.dex.close()
        if self.live:
            await self.live.close()

    def reload_config(self, db) -> TradingConfig:
        new = load_config(db)
        if new.symbols != self.cfg.symbols:
            self.md.set_symbols(self._universe(new))
        self.paper.fees = new.fees
        if new.kill_switch is False:
            self._flattened = False
        self.cfg = new
        return new

    # ------------------------------------------------------------- fast loop
    async def _fast_loop(self) -> None:
        while True:
            t0 = time.time()
            try:
                await self.fast_tick()
            except Exception as e:  # noqa: BLE001
                self.last_error = f"fast loop: {type(e).__name__}: {e}"
                log.exception("fast loop error")
            await asyncio.sleep(max(0.5, FAST_INTERVAL - (time.time() - t0)))

    async def fast_tick(self, refresh: bool = True) -> None:
        """Quotes → commands → position monitoring → portfolio gates → heartbeat (runs even when scanning is paused)."""
        if refresh:
            await self.md.refresh_quotes()
        async with self.lock:
            with session_scope() as db:
                cfg = self.reload_config(db)
                await self._process_commands(db, cfg)
                await self._monitor_positions(db, cfg)
                self._check_portfolio_gates(db, cfg)
                if time.time() - self._last_snapshot >= 60:
                    acct = get_account(db, cfg.mode, cfg.paper_starting_capital)
                    snapshot(db, acct, self.prices())
                    self._last_snapshot = time.time()
                put_setting(db, "agent_heartbeat", self.heartbeat())
        await self.publish("quotes", {s: {"bid": st.quote.bid, "ask": st.quote.ask, "ts": st.quote.ts}
                                      for s, st in self.md.state.items() if st.quote})

    def heartbeat(self) -> dict:
        return {"ts": time.time(), "started": self._started, "cycle": self.cycle, "last_scan": self.last_scan, "mode": self.cfg.mode,
                "scanning": self.cfg.automation.scanning_enabled, "auto_paper": self.cfg.automation.auto_paper_trading,
                "kill_switch": self.cfg.kill_switch, "trading_enabled": self.cfg.trading_enabled, "last_error": self.last_error,
                "unsupported": self.md.unsupported, "feeds": {f.name: f.health() for f in self.md.feeds}}

    async def _monitor_positions(self, db, cfg: TradingConfig) -> None:
        acct = get_account(db, cfg.mode, cfg.paper_starting_capital)
        for pos in open_positions(db, acct):
            st = self.md.state.get(pos.symbol)
            if st is None or st.quote is None:
                continue
            if st.quote.age() > cfg.risk.max_data_staleness_seconds:
                self.activity(db, "monitor", f"{pos.symbol}: quote stale ({st.quote.age():.0f}s) — holding, protective logic resumes on fresh data",
                              symbol=pos.symbol)
                continue
            if pos.mode == "paper":
                events = self.paper.on_tick(db, acct, pos, st.quote, self.minute_qv(pos.symbol))
            else:
                events = await self._live_tick(db, acct, pos, st.quote)
            self._narrate(db, events)
        if cfg.kill_switch and cfg.kill_switch_action == "flatten" and not self._flattened:
            for pos in open_positions(db, acct):
                st = self.md.state.get(pos.symbol)
                if st and st.quote:
                    self._narrate(db, self.paper.close_position(db, acct, pos, st.quote, self.minute_qv(pos.symbol),
                                                                "emergency kill switch — flatten all"))
            self._flattened = True
            self.risk_event(db, "kill_switch_flatten", "critical", "Kill switch: all positions flattened at market")

    def _narrate(self, db, events: list[ExecEvent]) -> None:
        for e in events:
            kind = {"stop_moved": "stop_adjust", "duplicate": "risk"}.get(e.kind, "execution")
            expl = None
            if e.kind == "stop_moved":
                expl = "Protective stop adjusted according to strategy rules (breakeven at +1R, +1R after TP1)."
            elif e.kind == "closed":
                pos = db.get(Position, e.position_id)
                if pos:
                    expl = (f"Closed {pos.symbol}: net P&L {pos.net_pnl:+.2f} after {pos.fees_paid:.2f} fees "
                            f"({pos.net_pnl / pos.risk_amount:+.2f}R)" if pos.risk_amount else None)
            self.activity(db, kind, e.message, symbol=e.symbol, explanation=expl, data={"position_id": e.position_id, **e.data})
        if events:
            asyncio.get_event_loop().create_task(self.publish("positions", {"changed": [e.position_id for e in events]}))

    def _check_portfolio_gates(self, db, cfg: TradingConfig) -> None:
        acct = get_account(db, cfg.mode, cfg.paper_starting_capital)
        ctx = risk_context(db, acct, self.prices())
        g = gate_status(cfg, ctx)
        if g.halt:
            key = f"{g.halt}:{ctx.now.date().isoformat()}"
            if self._halt_notified.get(g.halt) != key:
                self._halt_notified[g.halt] = key
                detail = next((c["detail"] for c in g.checks if c["name"] == g.halt), "")
                self.risk_event(db, g.halt, "critical", f"{g.halt.replace('_', ' ').title()} reached — no new positions will be opened ({detail})",
                                {"equity": ctx.equity})

    async def _process_commands(self, db, cfg: TradingConfig) -> None:
        cmds = db.execute(select(Command).where(Command.status == "pending").order_by(Command.id).limit(20)).scalars().all()
        acct = get_account(db, cfg.mode, cfg.paper_starting_capital)
        for c in cmds:
            try:
                if c.kind == "close_position":
                    pos = db.get(Position, int(c.payload.get("position_id", 0)))
                    st = self.md.state.get(pos.symbol) if pos else None
                    if not pos or pos.status not in ("open", "pending"):
                        c.result = "position not open"
                    elif not st or not st.quote:
                        c.result = "no quote available; retry shortly"
                        continue
                    else:
                        self._narrate(db, self.paper.close_position(db, acct, pos, st.quote, self.minute_qv(pos.symbol),
                                                                    f"manual close by {c.requested_by}"))
                        c.result = "closed"
                elif c.kind == "flatten_all":
                    for pos in open_positions(db, acct):
                        st = self.md.state.get(pos.symbol)
                        if st and st.quote:
                            self._narrate(db, self.paper.close_position(db, acct, pos, st.quote, self.minute_qv(pos.symbol),
                                                                        f"flatten all by {c.requested_by}"))
                    c.result = "flattened"
                elif c.kind == "scan_tokens":
                    asyncio.get_event_loop().create_task(self.scan_tokens())
                    c.result = "token scan started"
                elif c.kind == "reset_paper":
                    if open_positions(db, acct):
                        c.result = "close open positions before resetting"
                    else:
                        cap = float(c.payload.get("capital") or cfg.paper_starting_capital)
                        paper = get_account(db, "paper", cap)
                        paper.starting_capital = cap
                        paper.cash = cap
                        paper.reset_at = utcnow()
                        from .models import PortfolioSnapshot
                        db.execute(delete(PortfolioSnapshot).where(PortfolioSnapshot.account_id == paper.id))
                        self.activity(db, "system", f"Paper account reset to {cap:,.2f} USDC by {c.requested_by}")
                        c.result = "reset"
                else:
                    c.result = f"unknown command {c.kind}"
                c.status = "done"
            except Exception as e:  # noqa: BLE001
                c.status = "failed"
                c.result = str(e)[:300]
            c.processed_at = utcnow()

    # ------------------------------------------------------------- scan loop
    async def _scan_loop(self) -> None:
        await asyncio.sleep(2)
        while True:
            cfg = self.cfg
            t0 = time.time()
            try:
                if cfg.automation.scanning_enabled:
                    self._paused_notified = False
                    await self.scan_once()
                elif not self._paused_notified:
                    with session_scope() as db:
                        self.activity(db, "system", "Market scanning paused — open positions are still monitored every few seconds")
                    self._paused_notified = True
            except Exception as e:  # noqa: BLE001
                self.last_error = f"scan loop: {type(e).__name__}: {e}"
                log.exception("scan loop error")
            await asyncio.sleep(max(5, cfg.automation.scan_interval_seconds - (time.time() - t0)))

    def _context(self, symbol: str, cfg: TradingConfig) -> StrategyContext | None:
        primary = self.md.series(symbol, cfg.primary_timeframe)
        if primary is None or len(primary) < 50:
            return None
        return StrategyContext(symbol, primary, self.md.series(symbol, "1h"), self.md.series(symbol, "4h"))

    async def scan_once(self) -> None:
        cfg = self.cfg
        self.cycle += 1
        tfs = ("1m", cfg.primary_timeframe, "1h", "4h")
        for sym in list(self.md.state):
            await self.md.refresh_candles(sym, tfs)
        regime = htf_trend(self.md.series(REGIME_SYMBOL, "1h"))["trend"]
        for sym in cfg.symbols:
            if sym in self.md.unsupported:
                continue
            async with self.lock:
                with session_scope() as db:
                    await self._scan_symbol(db, sym, cfg, regime)
        self.last_scan = time.time()
        with session_scope() as db:
            put_setting(db, "scanner_snapshot", {"ts": time.time(), "regime": regime, "rows": list(self._scanner_rows.values())})
        await self.publish("scanner", {"rows": list(self._scanner_rows.values()), "regime": regime})

    async def _scan_symbol(self, db, sym: str, cfg: TradingConfig, regime: str) -> None:
        st = self.md.state[sym]
        ctx = self._context(sym, cfg)
        readiness = self.md.readiness(sym, ("1m", cfg.primary_timeframe, "1h"), cfg.risk.max_data_staleness_seconds,
                                      cfg.risk.max_venue_divergence_pct)
        quote, stats, depth = st.quote, st.stats, st.depth
        row = {"symbol": sym, "base": split_symbol(sym)[0], "price": quote.mid if quote else None,
               "change_24h_pct": stats.price_change_pct_24h if stats else None, "volume_24h_usd": stats.volume_quote_24h if stats else None,
               "market_cap": (self._market_caps.get(sym) or {}).get("market_cap"), "liquidity_usd": depth.liquidity_usd if depth else None,
               "spread_bps": round(quote.spread_bps, 2) if quote else None, "data_ok": readiness.ok, "data_issues": readiness.reasons,
               "rsi": None, "trend": "unknown", "volatility_pct": None, "signal": "NO TRADE", "confidence": 0, "strategy": None,
               "risk_rating": "unknown", "updated": time.time()}
        if ctx is None:
            row["data_issues"] = row["data_issues"] or ["insufficient candles"]
            self._scanner_rows[sym] = row
            return
        p = ctx.primary
        rsi = ind.rsi(p.c, 14)
        atr = ind.atr(p.h, p.l, p.c, 14)
        atr_pct = float(atr[-1] / p.c[-1] * 100)
        trend = htf_trend(ctx.htf)
        row.update(rsi=round(float(rsi[-1]), 2), trend=trend["trend"], volatility_pct=round(atr_pct, 4))
        candle_time = int(p.t[-1])
        acct = get_account(db, cfg.mode, cfg.paper_starting_capital)
        positions = open_positions(db, acct)
        has_pos = next((x for x in positions if x.symbol == sym), None)
        fresh_candle = any(self._evaluated.get((sym, n)) != candle_time for n in cfg.enabled_strategies)
        if fresh_candle:
            self.activity(db, "scan", f"Scanning {sym} — analysing {cfg.primary_timeframe} structure, 1h trend ({trend['trend']}), "
                          f"RSI {rsi[-1]:.1f}, ATR {atr_pct:.2f}%", symbol=sym)
        notional_guess = (acct.cash * cfg.risk.max_position_exposure_pct / 100) * 0.5
        rt_cost = None
        if quote:
            c = estimate(cfg.fees, notional_guess, self.minute_qv(sym), quote.spread_bps)
            rt_cost = 2 * c.total_bps
        mctx = MarketContext(sym, quote.mid if quote else None, quote.spread_bps if quote else None, row["liquidity_usd"],
                             row["volume_24h_usd"], row["change_24h_pct"], atr_pct, regime, readiness.ok, readiness.reasons, rt_cost)
        m = mark(db, acct, self.prices())
        exposure_pct = m["positions_value"] / m["equity"] * 100 if m["equity"] > 0 else 0
        pctx = PortfolioContext([x.symbol for x in positions], exposure_pct, cfg.risk.max_portfolio_exposure_pct)
        best = None
        waits = []
        params = {r.name: r.params for r in db.execute(select(StrategyConfig)).scalars()}
        for name in cfg.enabled_strategies:
            strat = build(name, params.get(name))
            sig = strat.evaluate(ctx)
            ev = evaluate(sig, mctx, pctx, cfg.min_liquidity_usd, cfg.risk.max_spread_bps,
                          strategy_track_record(db, name) if sig.direction == "long" else None, has_pos is not None)
            new = self._evaluated.get((sym, name)) != candle_time
            self._evaluated[(sym, name)] = candle_time
            # exit signal for a position opened by this strategy
            if ev.classification == EXIT and has_pos is not None and has_pos.strategy == name and has_pos.status == "open" and quote:
                self.activity(db, "decision", f"EXIT {sym}: {name} exit conditions met", symbol=sym, explanation=ev.explanation)
                self._narrate(db, self.paper.close_position(db, acct, has_pos, quote, self.minute_qv(sym), f"strategy exit: {'; '.join(sig.reasons)}"))
                continue
            if sig.direction != "long":
                if new:
                    waits.append(f"{STRATEGIES[name].label}: {ev.classification} — {'; '.join(sig.reasons)}")
                continue
            if best is None or ev.confidence > best[1].confidence:
                best = (sig, ev, new)
        if best:
            sig, ev, _ = best
            row.update(signal=ev.classification, confidence=ev.confidence, strategy=sig.strategy)
        elif waits:
            row["signal"] = "WAIT" if any(": WAIT" in w for w in waits) else "NO TRADE"
        row["risk_rating"] = self._risk_rating(row, atr_pct, readiness.ok)
        self._scanner_rows[sym] = row
        if waits:
            self.activity(db, "analysis", f"{sym}: no actionable setup this bar", symbol=sym, explanation=" | ".join(waits))
        if not best or not best[2]:
            return
        sig, ev, _ = best
        srow = Signal(symbol=sym, timeframe=sig.timeframe, strategy=sig.strategy, direction=sig.direction, candle_time=sig.candle_time,
                      entry=sig.entry, stop=sig.stop, targets=sig.targets, strength=sig.strength, features=_jsonable(sig.features), reasons=sig.reasons)
        db.add(srow)
        db.flush()
        drow = Decision(signal_id=srow.id, symbol=sym, strategy=sig.strategy, classification=ev.classification, confidence=ev.confidence,
                        score_breakdown=_jsonable(ev.breakdown), risk_flags=ev.risk_flags, explanation=ev.explanation)
        db.add(drow)
        db.flush()
        self.activity(db, "signal", f"{sig.strategy} signal on {sym}: {ev.classification} (confidence {ev.confidence})", symbol=sym,
                      explanation=ev.explanation, data={"decision_id": drow.id, "entry": sig.entry, "stop": sig.stop, "targets": sig.targets})
        await self._maybe_trade(db, cfg, acct, sym, sig, ev, drow, readiness, has_pos)

    @staticmethod
    def _risk_rating(row: dict, atr_pct: float, data_ok: bool) -> str:
        if not data_ok:
            return "high"
        score = 0
        score += 2 if atr_pct > 1.5 else (1 if atr_pct > 0.6 else 0)
        score += 2 if (row.get("liquidity_usd") or 0) < 250_000 else (1 if (row.get("liquidity_usd") or 0) < 1_000_000 else 0)
        score += 1 if abs(row.get("change_24h_pct") or 0) > 10 else 0
        score += 1 if (row.get("spread_bps") or 0) > 8 else 0
        return "low" if score <= 1 else ("medium" if score <= 3 else "high")

    async def _maybe_trade(self, db, cfg: TradingConfig, acct, sym, sig, ev, drow: Decision, readiness, has_pos) -> None:
        if not ev.actionable:
            drow.rejected_reason = f"classification {ev.classification}"
            return
        if ev.confidence < cfg.min_confidence_to_trade:
            drow.rejected_reason = f"confidence {ev.confidence} below threshold {cfg.min_confidence_to_trade}"
            self.activity(db, "decision", f"Rejecting {sym} {sig.strategy}: {drow.rejected_reason}", symbol=sym)
            return
        if not cfg.automation.auto_paper_trading and cfg.mode == "paper":
            drow.rejected_reason = "automatic paper trading is off (signal only)"
            self.activity(db, "decision", f"{sym}: candidate recorded but not traded — automatic paper trading is off", symbol=sym)
            return
        if cfg.mode == "live":
            problems = preflight(cfg)
            if problems:
                drow.rejected_reason = "live mode not armed: " + "; ".join(problems)
                self.activity(db, "risk", f"{sym}: live execution blocked — {drow.rejected_reason}", symbol=sym)
                return
        st = self.md.state[sym]
        quote = st.quote
        self.activity(db, "risk", f"Calculating position size for {sym} ({cfg.risk.risk_per_trade_pct}% risk, stop {sig.stop:.6g})", symbol=sym)
        ctx = risk_context(db, acct, self.prices())
        res = sig.features.get("resistance")
        req = TradeRequest(sym, quote.ask, sig.stop, sig.targets[0], quote.spread_bps, self.minute_qv(sym),
                           st.depth.liquidity_usd if st.depth else None, st.stats.volume_quote_24h if st.stats else None,
                           res.get("price") if isinstance(res, dict) and sig.strategy != "breakout" else None, readiness.ok, readiness.reasons)
        rd = evaluate_trade(cfg, ctx, req)
        drow.score_breakdown = _jsonable({**drow.score_breakdown, "risk_checks": rd.checks})
        if not rd.approved:
            drow.rejected_reason = "; ".join(rd.blocking)
            self.activity(db, "risk", f"Rejecting {sym} trade: {rd.blocking[0]}", symbol=sym,
                          explanation="Risk engine blocked the trade. All checks: " + "; ".join(f"{c['name']}={'ok' if c['passed'] else 'FAIL'}" for c in rd.checks))
            return
        tp1 = rd.target or sig.targets[0]
        r_unit = quote.ask - sig.stop
        tp2 = max(sig.targets[1] if len(sig.targets) > 1 else 0, tp1 + r_unit) if sig.targets else None
        reason = f"{sig.strategy}: " + "; ".join(sig.reasons[:3])
        if cfg.mode == "paper":
            pos, events = self.paper.open_position(db, acct, symbol=sym, strategy=sig.strategy, qty=rd.qty, entry_ref=quote.ask, stop=sig.stop,
                                                   tp1=tp1, tp2=tp2, quote=quote, minute_qv=self.minute_qv(sym), candle_time=sig.candle_time,
                                                   decision_id=drow.id, risk_amount=rd.risk_amount, reason=reason)
        else:
            pos, events = await self._live_open(db, acct, cfg, sym, sig, rd, tp1, tp2, quote, drow, reason)
        if pos is not None:
            drow.executed = True
            drow.position_id = pos.id
            self.activity(db, "execution", f"Opening {sym} {cfg.mode} position: {rd.qty:.6g} units (${rd.notional:,.2f}), risk ${rd.risk_amount:,.2f}, "
                          f"net R:R {rd.net_rr:.2f}, est. slippage {rd.est_slippage_bps:.1f} bps", symbol=sym, explanation=ev.explanation,
                          data={"position_id": pos.id, "decision_id": drow.id})
            if self.cfg.automation.ai_commentary_enabled and self.commentator.enabled:
                asyncio.get_event_loop().create_task(self._commentary(drow.id, sig, ev, rd))
        self._narrate(db, events)

    async def _commentary(self, decision_id: int, sig, ev, rd) -> None:
        facts = {"signal": sig.to_dict(), "classification": ev.classification, "confidence_0_100": ev.confidence,
                 "confidence_note": "ranking score, not a probability", "score_breakdown": ev.breakdown, "risk_flags": ev.risk_flags,
                 "risk_checks": rd.checks, "position": {"qty": rd.qty, "notional": rd.notional, "risk_amount": rd.risk_amount, "net_rr": rd.net_rr}}
        text = await self.commentator.explain(_jsonable(facts))
        if text:
            with session_scope() as db:
                d = db.get(Decision, decision_id)
                if d:
                    d.ai_commentary = text
                    self.activity(db, "ai", f"AI commentary for {sig.symbol}", symbol=sig.symbol, explanation=text, data={"decision_id": decision_id})

    # ------------------------------------------------------------- live hooks
    async def _live_open(self, db, acct, cfg, sym, sig, rd, tp1, tp2, quote, drow, reason):
        """Live entry via Jupiter. Records orders/positions in 'live' mode; never shares the paper ledger."""
        if self.live is None:
            self.live = JupiterLiveExecutor(cfg)
        self.live.cfg = cfg
        if not self.live.supported(sym):
            drow.rejected_reason = f"{sym} not swappable natively on Solana"
            return None, []
        from .execution.live import SOLANA_MINTS, USDC_DECIMALS, USDC_MINT
        from .models import Execution, Order

        mint, dec = SOLANA_MINTS[split_symbol(sym)[0]]
        coid = self.paper.client_order_id(sym, sig.strategy, sig.candle_time).replace("paper", "live")
        if db.execute(select(Order.id).where(Order.client_order_id == coid)).first():
            return None, [ExecEvent("duplicate", None, sym, f"duplicate live order {coid} prevented", {})]
        pos = Position(account_id=acct.id, mode="live", symbol=sym, strategy=sig.strategy, status="pending", planned_qty=rd.qty,
                       planned_entry=quote.ask, stop_price=sig.stop, initial_stop=sig.stop, tp1=tp1, tp2=tp2, risk_amount=rd.risk_amount,
                       entry_reason=reason, decision_id=drow.id, stop_history=[{"ts": utcnow().isoformat(), "stop": sig.stop, "reason": "initial"}])
        db.add(pos)
        db.flush()
        order = Order(client_order_id=coid, account_id=acct.id, mode="live", position_id=pos.id, symbol=sym, side="buy", type="market",
                      purpose="entry", qty=rd.qty, status="submitted", venue="jupiter")
        db.add(order)
        db.commit()  # persist BEFORE sending so a crash cannot cause a resend
        try:
            fill = await self.live.swap(coid, USDC_MINT, mint, int(rd.notional * 10 ** USDC_DECIMALS), USDC_DECIMALS, dec)
        except Exception as e:  # noqa: BLE001
            order.status = "rejected"
            order.reason = str(e)[:300]
            pos.status = "cancelled"
            self.risk_event(db, "live_order_failed", "warn", f"Live entry for {sym} failed: {str(e)[:200]}")
            return None, []
        order.status, order.external_id, order.filled_qty, order.avg_fill_price = "filled", fill.signature, fill.out_amount, fill.price
        db.add(Execution(order_id=order.id, qty=fill.out_amount, price=fill.price, reference_price=quote.ask, fee=0.0,
                         slippage_bps=abs(fill.price / quote.ask - 1) * 1e4, slippage_cost=abs(fill.price - quote.ask) * fill.out_amount,
                         liquidity="taker", tx_signature=fill.signature))
        pos.qty = pos.initial_qty = fill.out_amount
        pos.entry_price = fill.price
        pos.status = "open"
        pos.opened_at = utcnow()
        return pos, [ExecEvent("opened", pos.id, sym, f"LIVE position open {fill.out_amount:.6g} {sym} @ {fill.price:.6g} (tx {fill.signature[:12]}…)", {})]

    async def _live_tick(self, db, acct, pos, quote) -> list[ExecEvent]:
        """Client-side stop/target enforcement for live positions (exit = swap back to USDC)."""
        from .execution.rules import manage

        st = self.paper._state(pos)
        acts = [a for a in manage(st, quote.bid, quote.bid, quote.bid, time.time(), self.paper.rules) if a.kind != "move_stop"]
        if not acts:
            return []
        if self.live is None:
            self.live = JupiterLiveExecutor(self.cfg)
        from .execution.live import SOLANA_MINTS, USDC_DECIMALS, USDC_MINT

        mint, dec = SOLANA_MINTS[split_symbol(pos.symbol)[0]]
        act = acts[0]
        qty = pos.qty * act.fraction
        try:
            fill = await self.live.swap(f"live-pos{pos.id}-{act.kind}", mint, USDC_MINT, int(qty * 10 ** dec), dec, USDC_DECIMALS)
        except Exception as e:  # noqa: BLE001
            self.risk_event(db, "live_exit_failed", "critical", f"LIVE exit for {pos.symbol} failed: {str(e)[:200]} — will retry")
            return []
        pos.exit_value += fill.out_amount
        pos.exit_qty += qty
        pos.qty -= qty
        if pos.qty <= 1e-12:
            self.paper._finalize(db, pos, act.reason)
        return [ExecEvent("closed" if pos.status == "closed" else "exit_partial", pos.id, pos.symbol, f"LIVE {act.kind}: {act.reason}", {})]

    # ------------------------------------------------------------- slow loop
    async def _slow_loop(self) -> None:
        await asyncio.sleep(1)
        n = 0
        while True:
            try:
                await self.md.refresh_stats()
                for sym in self.md.symbols:
                    await self.md.refresh_depth(sym)
                if n % 10 == 0:
                    await self._enrich_market_caps()
                with session_scope() as db:
                    for sym in self.md.symbols:
                        self.md.persist(db, sym)
                    self.md.write_integration_status(db)
                    for name, h in {**self.scanner.health(), "anthropic": self.commentator.status()}.items():
                        row = db.get(IntegrationStatus, name) or IntegrationStatus(name=name)
                        row.status = h.get("status", "unknown")
                        row.last_error = h.get("last_error") or h.get("detail")
                        row.latency_ms = h.get("latency_ms")
                        db.merge(row)
                    if n % 30 == 0:
                        self._prune(db)
                n += 1
            except Exception as e:  # noqa: BLE001
                self.last_error = f"slow loop: {type(e).__name__}: {e}"
                log.exception("slow loop error")
            await asyncio.sleep(60)

    async def _enrich_market_caps(self) -> None:
        from .execution.live import SOLANA_MINTS

        wanted = {split_symbol(s)[0]: s for s in self.cfg.symbols if split_symbol(s)[0] in SOLANA_MINTS and split_symbol(s)[0] != "SOL"}
        if not wanted:
            return
        mints = {SOLANA_MINTS[b][0]: s for b, s in wanted.items()}
        try:
            rows = await self.dex.get(f"/tokens/v1/solana/{','.join(mints)}")
        except ProviderError:
            return
        best: dict[str, dict] = {}
        for p in rows if isinstance(rows, list) else []:
            sym = mints.get((p.get("baseToken") or {}).get("address"))
            st = self.md.state.get(sym) if sym else None
            try:
                price, mc, fdv = float(p.get("priceUsd")), p.get("marketCap"), p.get("fdv")
            except (TypeError, ValueError):
                continue
            # reject inconsistent third-party data: price must agree with the CEX within 3%, mcap <= fdv
            if not st or not st.quote or abs(price / st.quote.mid - 1) > 0.03 or not mc or (fdv and mc > fdv * 1.01):
                continue
            liq = (p.get("liquidity") or {}).get("usd") or 0
            if sym not in best or liq > best[sym]["dex_liquidity"]:
                best[sym] = {"market_cap": float(mc), "fdv": fdv, "dex_liquidity": liq, "source": "dexscreener"}
        self._market_caps.update(best)

    def _prune(self, db) -> None:
        cutoff = db.execute(select(ActivityEvent.id).order_by(ActivityEvent.id.desc()).offset(20000).limit(1)).scalar_one_or_none()
        if cutoff:
            db.execute(delete(ActivityEvent).where(ActivityEvent.id <= cutoff))

    # ------------------------------------------------------------- token loop
    async def _token_loop(self) -> None:
        await asyncio.sleep(20)
        while True:
            interval = self.cfg.automation.token_scan_interval_seconds
            if self.cfg.automation.token_scanner_enabled:
                try:
                    await self.scan_tokens()
                except Exception as e:  # noqa: BLE001
                    self.last_error = f"token loop: {type(e).__name__}: {e}"
                    log.exception("token loop error")
            await asyncio.sleep(interval)

    async def scan_tokens(self, limit: int = 8) -> int:
        reports = await self.scanner.scan(limit)
        with session_scope() as db:
            recent = {m for (m,) in db.execute(select(TokenScan.mint).where(TokenScan.ts > utcnow() - timedelta(hours=6))).all()}
            for r in reports:
                db.add(TokenScan(mint=r.mint, symbol=r.symbol or "?", name=r.name or "?", pair_address=r.pair_address, dex=r.dex,
                                 price_usd=r.price_usd, liquidity_usd=r.liquidity_usd, volume_24h=r.volume_24h, market_cap=r.market_cap,
                                 fdv=r.fdv, pair_created_at=r.pair_created_at, top10_holder_pct=r.top10_holder_pct,
                                 mint_authority=r.mint_authority, freeze_authority=r.freeze_authority, risk_score=r.risk_score,
                                 risk_level=r.risk_level, flags=r.flags, checks=_jsonable(r.checks)))
                if r.mint not in recent:
                    worst = ", ".join(f["message"] for f in sorted(r.flags, key=lambda f: -f["points"])[:3])
                    self.activity(db, "token_scan", f"New Solana token {r.symbol or r.mint[:6]} — risk {r.risk_level.upper()} ({r.risk_score}/100)",
                                  explanation=f"{worst}. Informational only: new tokens are never traded automatically.",
                                  data={"mint": r.mint, "risk_level": r.risk_level})
        await self.publish("tokens", {"count": len(reports)})
        return len(reports)


def _jsonable(x):
    import math

    import numpy as np

    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, (np.floating, float)):
        v = float(x)
        return None if math.isnan(v) or math.isinf(v) else v
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    if isinstance(x, datetime):
        return x.isoformat()
    return x
