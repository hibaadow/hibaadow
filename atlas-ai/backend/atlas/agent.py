"""ATLAS gold & forex trading agent.

Loops
-----
* fast  — quotes, operator commands, position monitoring (ALWAYS runs: even when scanning is paused,
          the kill switch is engaged or the market is quiet), portfolio gates, heartbeat
* scan  — candles 1m/5m/15m/1h/4h, currency strength, strategies → AI analyst → risk → execution
* slow  — economic calendar, US10Y, persistence, integration health, broker account & reconciliation
"""
from __future__ import annotations

import asyncio
import time
import traceback
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import delete, select

from . import analysis as an
from . import indicators as ind
from .brokers.public import PublicSource
from .commentary import Commentator
from .config import get_settings
from .db import session_scope
from .decision import EXIT, MarketContext, atr_percentile, evaluate, strategy_track_record
from .econ import EconService, blackout, currency_strength, upcoming
from .events import get_bus
from .execution.broker import BrokerExecutor
from .execution.paper import ExecEvent, PaperExecutor
from .instruments import INSTRUMENTS
from .logging import get_logger
from .marketdata.service import MarketDataService
from .models import ActivityEvent, AppSetting, Command, Decision, IntegrationStatus, Position, PortfolioSnapshot, RiskEvent, Signal, StrategyConfig
from .portfolio import get_account, open_positions, risk_context, snapshot
from .risk import TradeRequest, evaluate_trade, gate_status
from .sessions import NY, session_info
from .strategies.base import StrategyContext, htf_trend
from .strategies.library import STRATEGIES, for_symbol
from .trading_config import TradingConfig, load_config

log = get_logger("atlas.agent")


def utcnow():
    return datetime.now(timezone.utc)


def put_setting(db, key: str, value) -> None:
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=value))
    else:
        row.value = value


def make_source(name: str):
    if name == "oanda":
        from .brokers.oanda import OandaClient
        return OandaClient()
    if name == "mt5":
        from .brokers.mt5 import MT5Client
        return MT5Client()
    return PublicSource()


class TradingAgent:
    def __init__(self, market: MarketDataService | None = None, econ: EconService | None = None, broker=None):
        s = get_settings()
        with session_scope() as db:
            self.cfg = load_config(db)
            get_account(db, "paper", self.cfg.paper_starting_capital)
        if market is None:
            src = make_source(s.data_source)
            market = MarketDataService(self.cfg.symbols, src, PublicSource() if s.data_source != "public" else None)
        self.md = market
        self.econ = econ or EconService()
        self._broker = broker
        self.paper = PaperExecutor(self.cfg.costs)
        self.broker_exec: BrokerExecutor | None = None
        self.commentator = Commentator()
        self.bus = get_bus()
        self.lock = asyncio.Lock()
        self._tasks: list[asyncio.Task] = []
        self._evaluated: dict[tuple[str, str], int] = {}
        self._rows: dict[str, dict] = {}
        self._halt_notified: dict[str, str] = {}
        self._flattened = False
        self._paused_notified = False
        self._last_snapshot = 0.0
        self.broker_account: dict | None = None
        self.strength: dict[str, float] = {}
        self._started = time.time()
        self.cycle = 0
        self.last_scan: float | None = None
        self.last_error: str | None = None
        self.clock = utcnow  # injectable for deterministic tests

    # ------------------------------------------------------------------ helpers
    async def publish(self, kind: str, payload: dict) -> None:
        await self.bus.publish({"type": kind, "ts": utcnow().isoformat(), "data": payload})

    def activity(self, db, kind: str, message: str, symbol: str | None = None, explanation: str | None = None, data: dict | None = None):
        ev = ActivityEvent(kind=kind, symbol=symbol, message=message, explanation=explanation, data=_jsonable(data or {}))
        db.add(ev)
        db.flush()
        payload = {"id": ev.id, "ts": ev.ts.isoformat(), "kind": kind, "symbol": symbol, "message": message, "explanation": explanation, "data": ev.data}
        asyncio.get_event_loop().create_task(self.publish("activity", payload))
        return ev

    def risk_event(self, db, kind: str, severity: str, message: str, data: dict | None = None):
        db.add(RiskEvent(kind=kind, severity=severity, message=message, data=_jsonable(data or {})))
        self.activity(db, "risk", message, data={"risk_kind": kind, "severity": severity})

    def quotes(self):
        return {s: st.quote for s, st in self.md.state.items() if st.quote}

    @property
    def broker(self):
        if self._broker is None:
            s = get_settings()
            if s.broker == "oanda" and s.oanda_configured:
                from .brokers.oanda import OandaClient
                self._broker = self.md.source if isinstance(self.md.source, OandaClient) else OandaClient()
            elif s.broker == "mt5" and s.mt5_configured:
                from .brokers.mt5 import MT5Client
                self._broker = self.md.source if isinstance(self.md.source, MT5Client) else MT5Client()
        return self._broker

    def executor_for(self, cfg: TradingConfig):
        if cfg.mode == "paper":
            return self.paper
        if self.broker is None:
            return None
        if self.broker_exec is None or self.broker_exec.mode != cfg.mode:
            self.broker_exec = BrokerExecutor(self.broker, cfg.mode, cfg.costs)
        return self.broker_exec

    def mode_problems(self, cfg: TradingConfig) -> list[str]:
        s = get_settings()
        if cfg.mode == "paper":
            return []
        out = []
        if s.broker == "none":
            out.append("no broker configured (ATLAS_BROKER=oanda|mt5)")
        if s.broker == "oanda" and not s.oanda_configured:
            out.append("OANDA token/account id missing")
        if s.broker == "mt5" and not s.mt5_configured:
            out.append("MT5 bridge URL missing")
        if cfg.mode == "live":
            if not s.live_trading_allowed:
                out.append("ATLAS_LIVE_TRADING_ALLOWED is false")
            if not cfg.live_confirmed:
                out.append("live trading not confirmed by an admin")
        env = (self.broker_account or {}).get("environment")
        if env and env != cfg.mode:
            out.append(f"connected broker account is {env.upper()}, but mode is {cfg.mode.upper()}")
        return out

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        with session_scope() as db:
            n = self.md.load_public_history(db)
            self.activity(db, "system", f"ATLAS gold & forex agent started — mode {self.cfg.mode.upper()}, data source {self.md.venue}",
                          explanation=(f"Instruments: {', '.join(INSTRUMENTS[s].display for s in self.cfg.symbols)}. "
                                       + (f"Loaded {n} stored 1-minute bars built from the public quote feed. " if self.md.venue == "public" else "")
                                       + "Paper trading is the default; demo/live require broker credentials and explicit activation."))
        for coro, name in ((self._fast_loop(), "fast"), (self._scan_loop(), "scan"), (self._slow_loop(), "slow")):
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
        await self.econ.close()
        if self._broker is not None and self._broker is not self.md.source:
            await self._broker.close()

    def reload_config(self, db) -> TradingConfig:
        new = load_config(db)
        if new.symbols != self.cfg.symbols:
            self.md.set_symbols(new.symbols)
        self.paper.cm = new.costs
        if not new.kill_switch:
            self._flattened = False
        self.cfg = new
        return new

    # ------------------------------------------------------------------ fast loop
    async def _fast_loop(self) -> None:
        while True:
            t0 = time.time()
            try:
                await self.fast_tick()
            except Exception as e:  # noqa: BLE001
                self.last_error = f"fast loop: {type(e).__name__}: {e}"
                log.exception("fast loop error")
            interval = get_settings().public_quote_interval_seconds if self.md.venue == "public" else 3.0
            await asyncio.sleep(max(0.5, interval - (time.time() - t0)))

    async def fast_tick(self, refresh: bool = True) -> None:
        if refresh:
            await self.md.refresh_quotes()
        async with self.lock:
            with session_scope() as db:
                cfg = self.reload_config(db)
                await self._process_commands(db, cfg)
                await self._monitor_positions(db, cfg)
                self._check_portfolio_gates(db, cfg)
                if time.time() - self._last_snapshot >= 60:
                    snapshot(db, get_account(db, cfg.mode, cfg.paper_starting_capital), self.quotes(), self.broker_account)
                    self._last_snapshot = time.time()
                put_setting(db, "market_quotes", {s: {"bid": q.bid, "ask": q.ask, "ts": q.ts, "venue": q.venue} for s, q in self.quotes().items()})
                put_setting(db, "agent_heartbeat", self.heartbeat())
        await self.publish("quotes", {s: {"bid": q.bid, "ask": q.ask, "ts": q.ts} for s, q in self.quotes().items()})

    def heartbeat(self) -> dict:
        return {"ts": time.time(), "started": self._started, "cycle": self.cycle, "last_scan": self.last_scan, "mode": self.cfg.mode,
                "data_source": self.md.venue, "scanning": self.cfg.automation.scanning_enabled, "auto_trading": self.cfg.automation.auto_trading,
                "kill_switch": self.cfg.kill_switch, "trading_enabled": self.cfg.trading_enabled, "last_error": self.last_error,
                "mode_problems": self.mode_problems(self.cfg)}

    def _news(self, sym: str, cfg: TradingConfig, now: datetime):
        if not cfg.news.enabled:
            return None
        return blackout(self.econ.events, sym, now, cfg.news.minutes_before, cfg.news.minutes_after, cfg.news.central_bank_extra_minutes)

    async def _monitor_positions(self, db, cfg: TradingConfig) -> None:
        acct = get_account(db, cfg.mode, cfg.paper_starting_capital)
        mids = self.md.mids()
        now = self.clock()
        ex = self.executor_for(cfg)
        for pos in open_positions(db, acct):
            st = self.md.state.get(pos.symbol)
            if st is None or st.quote is None or st.quote.age() > cfg.risk.max_data_staleness_seconds:
                continue  # never act on stale prices (broker-held stops still protect demo/live positions)
            if pos.mode == "paper":
                events = self.paper.on_tick(db, acct, pos, st.quote, mids, news=self._news(pos.symbol, cfg, now) is not None)
            elif ex is not None and pos.mode == cfg.mode:
                events = await ex.on_tick(db, acct, pos, st.quote, mids)
            else:
                events = []
            self._narrate(db, events)
        reason = None
        if cfg.kill_switch and cfg.kill_switch_action == "flatten" and not self._flattened:
            reason = "emergency stop — flatten all"
        ny = now.astimezone(NY)
        if reason is None and cfg.sessions.close_before_weekend and ny.weekday() == 4 and (ny.hour, ny.minute) >= (16, 30):
            reason = "flat before the weekend close (gap risk)"
        for pos in open_positions(db, acct):
            r = reason
            if r is None and cfg.news.flatten_before_high_impact:
                e = blackout(self.econ.events, pos.symbol, now, cfg.news.minutes_before, 0, cfg.news.central_bank_extra_minutes)
                if e and e.time > now:
                    r = f"flatten ahead of {e.currency} {e.title}"
            if r:
                await self._close(db, cfg, acct, pos, r)
        if reason and reason.startswith("emergency"):
            self._flattened = True
            self.risk_event(db, "kill_switch_flatten", "critical", "Emergency stop: all positions closed at market")

    async def _close(self, db, cfg, acct, pos: Position, reason: str) -> None:
        st = self.md.state.get(pos.symbol)
        if pos.mode == "paper":
            if st and st.quote:
                self._narrate(db, self.paper.close_position(db, acct, pos, st.quote, self.md.mids(), reason))
        else:
            ex = self.executor_for(cfg)
            if ex is not None:
                self._narrate(db, await ex.close_position(db, acct, pos, reason))

    def _narrate(self, db, events: list[ExecEvent]) -> None:
        for e in events:
            kind = {"stop_moved": "stop_adjust", "duplicate": "risk", "rejected": "risk"}.get(e.kind, "execution")
            expl = None
            if e.kind == "stop_moved":
                expl = "Protective stop adjusted by rule: breakeven at +1R, +1R after TP1."
            elif e.kind == "closed" and e.position_id:
                pos = db.get(Position, e.position_id)
                if pos and pos.risk_amount:
                    expl = f"Net P&L ${pos.net_pnl:+,.2f} after ${pos.fees_paid:,.2f} commission ({pos.net_pnl / pos.risk_amount:+.2f}R)."
            self.activity(db, kind, e.message, symbol=e.symbol or None, explanation=expl, data={"position_id": e.position_id, **e.data})
        if events:
            asyncio.get_event_loop().create_task(self.publish("positions", {"changed": [e.position_id for e in events]}))

    def _check_portfolio_gates(self, db, cfg: TradingConfig) -> None:
        acct = get_account(db, cfg.mode, cfg.paper_starting_capital)
        ctx = risk_context(db, acct, self.quotes(), now=self.clock(), broker_account=self.broker_account, leverage=cfg.paper_leverage)
        g = gate_status(cfg, ctx)
        if g.halt:
            key = f"{g.halt}:{ctx.now.date().isoformat()}"
            if self._halt_notified.get(g.halt) != key:
                self._halt_notified[g.halt] = key
                detail = next((c["detail"] for c in g.checks if c["name"] == g.halt), "")
                self.risk_event(db, g.halt, "critical", f"{g.halt.replace('_', ' ').title()} reached — no new positions ({detail})", {"equity": ctx.equity})

    async def _process_commands(self, db, cfg: TradingConfig) -> None:
        cmds = db.execute(select(Command).where(Command.status == "pending").order_by(Command.id).limit(20)).scalars().all()
        acct = get_account(db, cfg.mode, cfg.paper_starting_capital)
        for c in cmds:
            try:
                if c.kind == "close_position":
                    pos = db.get(Position, int(c.payload.get("position_id", 0)))
                    if not pos or pos.status != "open":
                        c.result = "position not open"
                    else:
                        await self._close(db, cfg, get_account(db, pos.mode, cfg.paper_starting_capital), pos, f"manual close by {c.requested_by}")
                        c.result = "closed" if pos.status == "closed" else "close requested"
                elif c.kind == "flatten_all":
                    for pos in open_positions(db, acct):
                        await self._close(db, cfg, acct, pos, f"flatten all by {c.requested_by}")
                    c.result = "flattened"
                elif c.kind == "reset_paper":
                    paper = get_account(db, "paper", cfg.paper_starting_capital)
                    if open_positions(db, paper):
                        c.result = "close open paper positions before resetting"
                    else:
                        cap = float(c.payload.get("capital") or cfg.paper_starting_capital)
                        paper.starting_capital = paper.cash = cap
                        paper.reset_at = utcnow()
                        db.execute(delete(PortfolioSnapshot).where(PortfolioSnapshot.account_id == paper.id))
                        self.activity(db, "system", f"Paper account reset to ${cap:,.2f} by {c.requested_by}")
                        c.result = "reset"
                elif c.kind == "refresh_calendar":
                    asyncio.get_event_loop().create_task(self.econ.refresh(force=True))
                    c.result = "refresh started"
                else:
                    c.result = f"unknown command {c.kind}"
                c.status = "done"
            except Exception as e:  # noqa: BLE001
                c.status, c.result = "failed", str(e)[:300]
            c.processed_at = utcnow()

    # ------------------------------------------------------------------ scan loop
    async def _scan_loop(self) -> None:
        await asyncio.sleep(3)
        while True:
            cfg = self.cfg
            t0 = time.time()
            try:
                if cfg.automation.scanning_enabled:
                    self._paused_notified = False
                    await self.scan_once()
                elif not self._paused_notified:
                    with session_scope() as db:
                        self.activity(db, "system", "Market scanning paused — open positions are still monitored")
                    self._paused_notified = True
            except Exception as e:  # noqa: BLE001
                self.last_error = f"scan loop: {type(e).__name__}: {e}"
                log.exception("scan loop error")
            await asyncio.sleep(max(5, cfg.automation.scan_interval_seconds - (time.time() - t0)))

    def _context(self, sym: str, cfg: TradingConfig, now_ms: int) -> StrategyContext | None:
        primary = self.md.series(sym, cfg.primary_timeframe)
        if primary is None or len(primary) < 30:
            return None
        return StrategyContext(sym, primary, self.md.series(sym, "1h"), self.md.series(sym, "4h"), now_ms, self.strength.get("USD"),
                               self.strength, (self.econ.us10y or {}).get("trend"))

    async def scan_once(self) -> None:
        cfg = self.cfg
        self.cycle += 1
        tfs = ("1m", cfg.primary_timeframe, "15m", "1h", "4h")
        for sym in self.md.symbols:
            await self.md.refresh_candles(sym, tfs)
        await self.md.refresh_reference()
        closes = {s: ser.c for s in self.md.symbols if (ser := self.md.series(s, "1h")) is not None}
        self.strength = currency_strength(closes, 24) if closes else {}
        now = self.clock()
        for sym in cfg.symbols:
            async with self.lock:
                with session_scope() as db:
                    await self._scan_symbol(db, sym, cfg, now)
        self.last_scan = time.time()
        rows = [self._rows[s] for s in cfg.symbols if s in self._rows]
        with session_scope() as db:
            put_setting(db, "analysis_snapshot", _jsonable({"ts": time.time(), "strength": self.strength, "rows": rows,
                                                            "us10y": self.econ.us10y, "source": self.md.venue}))
        await self.publish("scanner", {"rows": _jsonable(rows)})

    def _symbol_row(self, sym, cfg, ctx, readiness, sess, now) -> dict:
        inst = INSTRUMENTS[sym]
        st = self.md.state[sym]
        q = st.quote
        row = {"symbol": sym, "display": inst.display, "asset_class": inst.asset_class, "bid": q.bid if q else None, "ask": q.ask if q else None,
               "mid": q.mid if q else None, "spread_pips": round(inst.to_pips(q.ask - q.bid), 2) if q else None,
               "spread_limit": cfg.risk.spread_limits_pips.get(sym, inst.max_spread_pips), "session": sess.label, "market_open": sess.market_open,
               "data_ok": readiness.ok, "data_issues": readiness.reasons, "signal": "NO TRADE", "direction": None, "confidence": 0, "strategy": None,
               "risk_rating": "unknown", "updated": time.time(), "digits": inst.digits,
               "bars": {tf: len(st.candles.get(tf, [])) for tf in ("1m", "5m", "15m", "1h", "4h")}}
        if ctx is None:
            return row
        p = ctx.primary
        rsi = ind.rsi(p.c, 14)
        atr = ind.atr(p.h, p.l, p.c, 14)
        h1, h4 = htf_trend(ctx.htf), htf_trend(ctx.htf2, 40)
        stc = an.market_structure(p.h, p.l, p.c)
        lv = an.day_levels(p.t, p.h, p.l, int(now.timestamp() * 1000))
        ch = (ctx.htf.c[-1] / ctx.htf.c[-25] - 1) * 100 if ctx.htf is not None and len(ctx.htf) > 24 else None
        row.update(rsi=_r(rsi[-1], 1), atr=_r(atr[-1], inst.digits + 1), atr_pips=_r(inst.to_pips(atr[-1]), 1), atr_pct=_r(atr[-1] / p.c[-1] * 100, 4),
                   trend_1h=h1["trend"], trend_4h=h4["trend"], structure=stc.trend, change_24h_pct=_r(ch, 3), levels=lv,
                   atr_percentile=_r(atr_percentile(atr), 2))
        return row

    async def _scan_symbol(self, db, sym: str, cfg: TradingConfig, now: datetime) -> None:
        inst = INSTRUMENTS[sym]
        st = self.md.state[sym]
        now_ms = int(now.timestamp() * 1000)
        ctx = self._context(sym, cfg, now_ms)
        sess = session_info(now, inst.currencies if inst.asset_class == "forex" else ("XAU", "USD"), inst.asset_class)
        readiness = self.md.readiness(sym, (cfg.primary_timeframe, "1h"), cfg.risk.max_data_staleness_seconds, cfg.risk.max_reference_divergence_pips,
                                      now=now)
        row = self._symbol_row(sym, cfg, ctx, readiness, sess, now)
        self._rows[sym] = row
        if ctx is None:
            return
        q = st.quote
        news = self._news(sym, cfg, now)
        ups = upcoming(self.econ.events, sym, now, 24)
        mctx = MarketContext(sym, q.bid if q else None, q.ask if q else None, row["spread_pips"], row["spread_limit"], row.get("atr_percentile"),
                             sess, readiness.ok, readiness.reasons, self.strength, (self.econ.us10y or {}).get("trend"), ups, news, now)
        acct = get_account(db, cfg.mode, cfg.paper_starting_capital)
        held = next((x for x in open_positions(db, acct) if x.symbol == sym), None)
        candle_time = int(ctx.primary.t[-1])
        if any(self._evaluated.get((sym, n)) != candle_time for n in cfg.enabled_strategies):
            self.activity(db, "scan", f"Analysing {inst.display} — {cfg.primary_timeframe} structure {row.get('structure')}, 1h {row.get('trend_1h')}, "
                          f"4h {row.get('trend_4h')}, RSI {row.get('rsi')}, spread {row.get('spread_pips')} pips, {sess.label}", symbol=sym)
        params = {r.name: r.params for r in db.execute(select(StrategyConfig)).scalars()}
        best, notes = None, []
        for strat in for_symbol(cfg.enabled_strategies, sym, params):
            sig = strat.evaluate(ctx)
            ev = evaluate(sig, mctx, strategy_track_record(db, strat.name) if sig.direction in ("buy", "sell") else None,
                          held.side if held else None)
            new = self._evaluated.get((sym, strat.name)) != candle_time
            self._evaluated[(sym, strat.name)] = candle_time
            if ev.classification == EXIT and held is not None and held.strategy == strat.name and held.status == "open":
                self.activity(db, "decision", f"EXIT {inst.display}: {strat.label} exit conditions met", symbol=sym, explanation=ev.explanation)
                await self._close(db, cfg, acct, held, f"strategy exit: {'; '.join(sig.reasons)}")
                continue
            if sig.direction not in ("buy", "sell"):
                if new:
                    notes.append(f"{strat.label}: {ev.classification} — {'; '.join(sig.reasons)}")
                continue
            if best is None or ev.confidence > best[1].confidence:
                best = (sig, ev, new)
        if best:
            row.update(signal=best[1].classification, confidence=best[1].confidence, strategy=best[0].strategy, direction=best[0].direction.upper())
        elif notes:
            row["signal"] = "WAIT" if any(": WAIT" in n for n in notes) else "NO TRADE"
        row["risk_rating"] = _risk_rating(row, readiness.ok, news is not None)
        if notes:
            self.activity(db, "analysis", f"{inst.display}: no actionable setup this bar", symbol=sym, explanation=" | ".join(notes))
        if not best or not best[2]:
            return
        sig, ev, _ = best
        srow = Signal(symbol=sym, timeframe=sig.timeframe, strategy=sig.strategy, direction=sig.direction, candle_time=sig.candle_time, entry=sig.entry,
                      stop=sig.stop, targets=sig.targets, strength=sig.strength, features=_jsonable(sig.features), reasons=sig.reasons)
        db.add(srow)
        db.flush()
        drow = Decision(signal_id=srow.id, symbol=sym, strategy=sig.strategy, classification=ev.classification, confidence=ev.confidence,
                        direction=sig.direction.upper(), timeframe=sig.timeframe, entry=sig.entry, stop_loss=sig.stop, take_profit=sig.targets[0],
                        take_profit_2=sig.targets[1] if len(sig.targets) > 1 else None, risk_reward=_r(sig.rr, 2),
                        score_breakdown=_jsonable(ev.breakdown), risk_flags=ev.risk_flags, explanation=ev.explanation,
                        evidence=sig.evidence, events=ev.events, invalidation=sig.invalidation)
        db.add(drow)
        db.flush()
        self.activity(db, "signal", f"{sig.direction.upper()} {inst.display} · {STRATEGIES[sig.strategy].label}: {ev.classification} (confidence {ev.confidence})",
                      symbol=sym, explanation=ev.explanation, data={"decision_id": drow.id})
        await self._maybe_trade(db, cfg, acct, sym, sig, ev, drow, readiness, sess, news)

    async def _maybe_trade(self, db, cfg: TradingConfig, acct, sym, sig, ev, drow: Decision, readiness, sess, news) -> None:
        inst = INSTRUMENTS[sym]
        q = self.md.state[sym].quote
        side = sig.direction
        if q is None:
            drow.rejected_reason = "no live quote"
            return
        problems = self.mode_problems(cfg)
        if problems:
            drow.rejected_reason = f"{cfg.mode} mode not available: " + "; ".join(problems)
            self.activity(db, "risk", f"{inst.display}: {drow.rejected_reason}", symbol=sym)
            return
        ctx = risk_context(db, acct, self.quotes(), now=self.clock(), broker_account=self.broker_account, leverage=cfg.paper_leverage)
        sr = sig.features.get("support") if side == "sell" else sig.features.get("resistance")
        req = TradeRequest(sym, side, q.ask if side == "buy" else q.bid, sig.stop, sig.targets[0], q.ask - q.bid, self.md.mids(), sess, news,
                           sr.get("price") if isinstance(sr, dict) else None, readiness.ok, readiness.reasons)
        rd = evaluate_trade(cfg, ctx, req)
        if rd.sizing:
            sz = rd.sizing
            drow.lots, drow.risk_amount, drow.take_profit, drow.est_costs = sz.lots, round(sz.risk_amount, 2), sz.target, sz.costs
            drow.risk_reward = round(sz.net_rr, 2)
        drow.score_breakdown = _jsonable({**(drow.score_breakdown or {}), "risk_checks": rd.checks})
        if not ev.actionable:
            drow.rejected_reason = f"analyst classification {ev.classification}"
            return
        if ev.confidence < cfg.min_confidence_to_trade:
            drow.rejected_reason = f"confidence {ev.confidence} below threshold {cfg.min_confidence_to_trade}"
            self.activity(db, "decision", f"Rejecting {side.upper()} {inst.display}: {drow.rejected_reason}", symbol=sym)
            return
        if not rd.approved:
            drow.rejected_reason = "; ".join(rd.blocking)
            self.activity(db, "risk", f"Rejecting {side.upper()} {inst.display}: {rd.blocking[0]}", symbol=sym,
                          explanation="All risk checks: " + "; ".join(f"{c['name']}={'ok' if c['passed'] else 'FAIL'}" for c in rd.checks))
            return
        if not cfg.automation.auto_trading:
            drow.rejected_reason = "automatic trading is off — proposal recorded for review"
            self.activity(db, "decision", f"{inst.display} {side.upper()} proposal passed all risk checks — not executed (automatic trading off)", symbol=sym)
            return
        ex = self.executor_for(cfg)
        if ex is None:
            drow.rejected_reason = f"{cfg.mode} mode not available: no executor"
            self.activity(db, "risk", f"{inst.display}: execution blocked — {drow.rejected_reason}", symbol=sym)
            return
        sz = rd.sizing
        sg = 1 if side == "buy" else -1
        r_unit = abs(req.entry - sig.stop)
        tp2 = sig.targets[1] if len(sig.targets) > 1 else None
        if tp2 is None or sg * (tp2 - sz.target) <= 0:
            tp2 = inst.round_price(sz.target + sg * r_unit)
        reason = f"{STRATEGIES[sig.strategy].label}: " + "; ".join(sig.reasons[:3])
        self.activity(db, "risk", f"Sizing {inst.display}: {sz.lots:.2f} lots — stop {sz.stop_pips:.1f} pips × ${sz.pip_value_usd:.2f}/pip/lot, "
                      f"risk ${sz.risk_amount:,.2f}, margin ${sz.margin_usd:,.2f}, est. costs ${sz.costs.get('total_usd', 0):,.2f}", symbol=sym)
        common = dict(symbol=sym, side=side, strategy=sig.strategy, lots=sz.lots, stop=sig.stop, tp1=sz.target, tp2=tp2, quote=q, mids=self.md.mids(),
                      candle_time=sig.candle_time, decision_id=drow.id, risk_amount=sz.risk_amount, reason=reason)
        if cfg.mode == "paper":
            pos, events = self.paper.open_position(db, acct, news=news is not None, **common)
        else:
            pos, events = await ex.open_position(db, acct, max_slippage_pips=cfg.risk.max_slippage_pips.get(sym, inst.slippage_pips * 4), **common)
        if pos is not None and pos.status == "open":
            drow.executed, drow.position_id = True, pos.id
            if cfg.automation.ai_commentary_enabled and self.commentator.enabled:
                asyncio.get_event_loop().create_task(self._commentary(drow.id, sig, ev, rd))
        self._narrate(db, events)

    async def _commentary(self, decision_id: int, sig, ev, rd) -> None:
        facts = {"signal": sig.to_dict(), "classification": ev.classification, "confidence_0_100": ev.confidence,
                 "confidence_note": "setup-quality score, not a probability", "score_breakdown": ev.breakdown, "risk_flags": ev.risk_flags,
                 "economic_events": ev.events, "risk_checks": rd.checks, "sizing": rd.sizing}
        text = await self.commentator.explain(_jsonable(facts))
        if text:
            with session_scope() as db:
                d = db.get(Decision, decision_id)
                if d:
                    d.ai_commentary = text
                    self.activity(db, "ai", f"AI analyst commentary — {INSTRUMENTS[sig.symbol].display}", symbol=sig.symbol, explanation=text)

    # ------------------------------------------------------------------ slow loop
    async def _slow_loop(self) -> None:
        await asyncio.sleep(1)
        n = 0
        while True:
            try:
                await self.slow_tick(prune=n % 30 == 0)
                n += 1
            except Exception as e:  # noqa: BLE001
                self.last_error = f"slow loop: {type(e).__name__}: {e}"
                log.exception("slow loop error")
            await asyncio.sleep(60)

    async def slow_tick(self, prune: bool = False) -> None:
        await self.econ.refresh()
        await self._broker_sync()
        with session_scope() as db:
            self.md.persist_public_bars(db)
            for sym in self.md.symbols:
                self.md.persist(db, sym)
            extra = {"forexfactory_calendar": self.econ.ff.health(), "fred": self.econ.fred.health(), "anthropic": self.commentator.status()}
            if self._broker is not None and self._broker is not self.md.source:
                extra.update(self._broker.health())
            self.md.write_integration_status(db, extra)
            put_setting(db, "macro_snapshot", _jsonable({"ts": time.time(), "events": [e.to_dict() for e in self.econ.events],
                                                         "events_fetched": self.econ.events_fetched, "us10y": self.econ.us10y, "strength": self.strength}))
            if self.broker_account:
                put_setting(db, "broker_account", self.broker_account)
            if prune:
                cutoff = db.execute(select(ActivityEvent.id).order_by(ActivityEvent.id.desc()).offset(20000).limit(1)).scalar_one_or_none()
                if cutoff:
                    db.execute(delete(ActivityEvent).where(ActivityEvent.id <= cutoff))

    async def _broker_sync(self) -> None:
        if get_settings().broker == "none" or self.broker is None:
            return
        try:
            a = await self.broker.account()
            self.broker_account = {"broker": a.broker, "environment": a.environment, "currency": a.currency, "balance": a.balance, "equity": a.equity,
                                   "margin_used": a.margin_used, "margin_free": a.margin_free, "leverage": a.leverage, "ts": time.time()}
            with session_scope() as db:
                row = db.get(IntegrationStatus, f"{a.broker}_account") or IntegrationStatus(name=f"{a.broker}_account")
                row.status, row.last_ok, row.last_error = "ok", utcnow(), None
                row.details = {"environment": a.environment}
                db.merge(row)
        except Exception as e:  # noqa: BLE001
            self.broker_account = None
            log.warning("broker account sync failed", extra={"data": {"error": str(e)[:200]}})
            return
        cfg = self.cfg
        ex = self.executor_for(cfg)
        if ex is None or cfg.mode == "paper":
            return
        async with self.lock:
            with session_scope() as db:
                acct = get_account(db, cfg.mode)
                acct.cash = self.broker_account["balance"]
                self._narrate(db, await ex.reconcile(db, acct, open_positions(db, acct)))


def _risk_rating(row: dict, data_ok: bool, news: bool) -> str:
    if not data_ok or news:
        return "high"
    score = 0
    ap = row.get("atr_percentile")
    score += 2 if ap is not None and ap > 0.9 else (1 if ap is not None and ap > 0.75 else 0)
    if row.get("spread_pips") is not None and row.get("spread_limit"):
        score += 2 if row["spread_pips"] > row["spread_limit"] else (1 if row["spread_pips"] > 0.6 * row["spread_limit"] else 0)
    sess = row.get("session") or ""
    score += 0 if ("London" in sess or "New York" in sess or "overlap" in sess) else 1
    return "low" if score <= 1 else ("medium" if score <= 3 else "high")


def _r(x, nd=4):
    try:
        v = float(x)
        return None if v != v or v in (float("inf"), float("-inf")) else round(v, nd)
    except (TypeError, ValueError):
        return None


def _jsonable(x):
    import dataclasses
    import math

    if dataclasses.is_dataclass(x) and not isinstance(x, type):
        return _jsonable(dataclasses.asdict(x))
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, (np.floating, float)):
        v = float(x)
        return None if math.isnan(v) or math.isinf(v) else v
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.bool_):
        return bool(x)
    if isinstance(x, datetime):
        return x.isoformat()
    return x
