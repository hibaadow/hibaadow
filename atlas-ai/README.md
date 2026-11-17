# ATLAS AI — Gold & Forex Day-Trading Agent

ATLAS AI is a day-trading platform for **XAU/USD (gold)** and **forex** only. It analyses gold and ten
currency pairs across 1m/5m/15m/1h/4h. Five confluence strategies feed an explainable AI analyst. A strict risk
engine sizes positions from pip value, contract size and stop distance, and the agent trades a **paper account by
default**. It can be connected to **MetaTrader 5** (via MetaApi — no Windows — or a Windows bridge) or **OANDA** demo accounts, and to live accounts only after
explicit activation. MT5 works **without Windows** through MetaApi's cloud terminal (ideal for Mac users).

> ATLAS does not trade cryptocurrency, indices, stocks, or any commodity other than gold. Every symbol outside the
> 11 supported instruments is rejected by configuration, API, strategies and the MT5 bridge.
> Leveraged FX/CFD trading carries a high risk of loss. Nothing here is financial advice.

| Market | Instruments |
|---|---|
| **GOLD** | XAU/USD |
| **FOREX** | EUR/USD, GBP/USD, USD/JPY, GBP/JPY, AUD/USD, USD/CAD, USD/CHF, NZD/USD, EUR/GBP, EUR/JPY |

More detail: [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) · [`docs/BROKERS.md`](docs/BROKERS.md) · [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · [`bridge/README.md`](bridge/README.md)

---

## Architecture

```
                    ┌──────────────────── worker (python -m atlas.worker) ─────────────────────┐
 OANDA v20 ─────────┤ Market data ─► 5 strategies ─► AI analyst ─► Risk engine ─► Execution     │
 MT5 (bridge) ──────┤ candles/quotes  confluence    BUY/SELL,      lots, pip      paper | broker │
 Swissquote quotes ─┤ validation,     ≥3 evidence   confidence,    value, margin, demo | live    │
 (no-credential)    │ market hours    categories    invalidation   news, sessions               │
 Econ. calendar ────┤ Calendar · central banks · US10Y (FRED) · currency strength (derived)     │
                    └───────────────┬───────────────────────────────────────────────────────────┘
                                    │ PostgreSQL (all state)       Redis pub/sub (live events)
                    ┌───────────────┴────────── api (FastAPI + static Next.js UI) ──────────────┐
                    │ REST /api/* · WebSocket /api/ws · auth/RBAC · backtests · audit log        │
                    └────────────────────────────────────────────────────────────────────────────┘
```

| Layer | Tech | Location |
|---|---|---|
| Frontend | Next.js 15 (static export), TypeScript, Tailwind v4, Lightweight Charts 5 | `frontend/` |
| API | FastAPI, WebSockets, httpOnly cookie sessions, RBAC, CSRF header | `backend/atlas/api/` |
| Engine | asyncio worker: analysis, AI analyst, risk, execution, monitoring | `backend/atlas/agent.py` |
| Instruments | contract size, pip size, digits, lots, margin, USD conversion | `backend/atlas/instruments.py` |
| Data & brokers | public quotes + bar builder, OANDA v20, MT5 bridge client | `backend/atlas/brokers/`, `marketdata/` |
| Macro | economic calendar, central-bank detection, news blackout, US10Y, currency strength | `backend/atlas/econ.py` |
| Sessions | DST-aware Sydney/Tokyo/London/New York, market hours, rollover | `backend/atlas/sessions.py` |
| Strategies | trend pullback, breakout/retest, liquidity sweep, supply/demand, gold session model | `backend/atlas/strategies/` |
| Risk | lot sizing, margin/leverage, currency exposure, loss limits | `backend/atlas/risk.py` |
| Execution | paper broker; broker executor (OANDA/MT5) with broker-held SL/TP | `backend/atlas/execution/` |
| Backtester | long/short, lots, per-bar spread, walk-forward | `backend/atlas/backtest.py` |
| Storage | PostgreSQL 16 + Alembic; Redis 7 | `models.py`, `migrations/` |
| MT5 bridge | FastAPI service beside the MT5 terminal (Windows) | `bridge/mt5_bridge.py` |

---

## Quick start (Docker)

```bash
cd atlas-ai
cp .env.example .env
# set POSTGRES_PASSWORD, ATLAS_SECRET_KEY (python3 -c "import secrets; print(secrets.token_urlsafe(64))"), ATLAS_ADMIN_PASSWORD
docker compose up -d --build
```

Open **http://localhost:8000** and sign in. Without broker credentials, ATLAS runs in **paper mode on live public
gold/FX quotes**. Strategies start producing signals once enough bars have accumulated (see
[Data sources](#data-sources)). For instant history, add OANDA practice credentials (free) or an MT5 bridge.

## Local development

```bash
createuser -P atlas && createdb -O atlas atlas && createdb -O atlas atlas_test
cd backend && python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp ../.env.example .env          # ATLAS_ENV=development, ATLAS_DATABASE_URL, ATLAS_SECRET_KEY, ATLAS_ADMIN_PASSWORD
uvicorn atlas.api.app:app --port 8000          # applies migrations; runs the engine in-process
cd ../frontend && npm ci && NEXT_PUBLIC_WS_URL=ws://localhost:8000/api/ws npm run dev   # http://localhost:3000
```

To serve the production UI from the API instead, run `npm run build` and set `ATLAS_FRONTEND_DIST=<abs path>/frontend/out`.
For the production topology, set `ATLAS_EMBEDDED_WORKER=false` on the API and run `python -m atlas.worker`.

---

## Data sources

| Source | Credentials | Provides | Notes |
|---|---|---|---|
| **Swissquote public quote feed** | none | live bid/ask for all 11 instruments | ATLAS uses the median spread profile (conservative). Bars are **built from sampled quotes** (every 10 s) and stored, so history accumulates from first start: ~12 h before 5m strategies have 150 bars, ~2.5 days for the 1h trend filter. Not suitable for backtesting until weeks of bars exist. |
| **OANDA v20** | API token + account id | bid/ask candles (M1–H4, years of history), live prices, account, execution | Practice (demo) host by default. |
| **MetaTrader 5 via MetaApi** | MetaApi token + account id (MT5 login entered at MetaApi) | broker candles (with spread), prices, account, execution | **No Windows needed.** Your broker's own prices and contract specs. |
| **MetaTrader 5 via Windows bridge** | MT5 terminal + ATLAS bridge on Windows | same as above | For users who run their own Windows terminal/VPS. |
| **ForexFactory calendar export** | none | this week's economic events, impact, forecast/previous | Refreshed every 30 min. Central-bank decisions and speeches are detected. |
| **FRED DGS10** | none | US 10-year Treasury yield (daily) | Gold macro context. |
| Currency strength | — | derived from ATLAS's own FX quotes | Not an external index. |

When a broker is the data source, the public feed still runs as an **independent reference**. A broker price that
diverges by more than the configured number of pips blocks trading on that instrument (bad-data protection).

---

## Strategies (all two-sided: BUY and SELL)

Every tradeable signal needs **at least three independent evidence categories** (trend, structure, momentum,
level, liquidity, volume, VWAP, session, macro), so no trade is ever triggered by a single indicator. Stops are ATR-based
beyond a structural level (clamped to 0.8–3 ATR). Targets must reach ≥ 2R **net of costs**.

| Strategy | Logic |
|---|---|
| Trend following · pullback | 1h/4h EMA21/50 trend, entry-TF EMA alignment, pullback into EMA21 value area, resumption candle, RSI/MACD momentum, London-anchored VWAP side |
| Breakout · retest | ≤4.5-ATR consolidation, momentum breakout candle, retest that holds, tick-volume confirmation, false-breakout filter |
| Liquidity sweep | stop-run through prior-day high/low, Asian high/low or swing levels, close back inside, market-structure shift, reversal candle, session |
| Supply & demand | fresh zone (base + ≥2-ATR impulse), first return with rejection, HTF alignment, room to the opposing level |
| **Gold session model (XAU/USD only)** | London/NY opening windows, Asian-range sweep-and-reclaim or accepted breakout, USD strength and US10Y trend as confluence, round-number levels |

## AI trading analyst

Every proposal records: instrument, **BUY/SELL**, entry, stop-loss, take-profit (TP1/TP2), reward:risk (net),
position size in lots, estimated costs (spread + commission + slippage, in USD), supporting evidence, relevant
economic events (24 h), invalidation conditions, and a **0–100 confidence score**. The score is a setup-quality
ranking, not a probability. Its calibration against realised outcomes is shown on the AI Analyst page.

Classifications: STRONG BUY / BUY / STRONG SELL / SELL CANDIDATE, WAIT, NO TRADE, EXIT, HIGH RISK. The analyst
records rejected proposals with the reason (low confidence, a failed risk check, automatic trading off, mode not
available). Optional Claude commentary is generated from the structured facts only and never changes a decision.

## Risk management

| Control | Default | Hard limit |
|---|---|---|
| Risk per trade | 0.5 % of equity | ≤ 1 % |
| Daily / weekly loss (equity incl. unrealised) | 2 % / 5 % | ≤ 2 % / ≤ 5 % |
| Simultaneous positions | 3 | ≤ 3 |
| Net reward:risk after costs | 2.0 | ≥ 2.0 |
| Net risk per currency (directional) | 1 % | ≤ 3 % |
| Effective leverage (total notional / equity) | 10:1 | ≤ 30:1 |
| Post-trade margin level | ≥ 300 % | |
| Spread / slippage limits | per instrument, in pips (e.g. EUR/USD 1.5 / 1, XAU/USD 8 / 6) | |
| Cooldown | 120 min after 3 consecutive losses | |
| News blackout | 30 min before → 30 min after high-impact events (+30 min for central banks) | |
| Sessions | new trades in London & New York (JPY/AUD/NZD pairs also in Asia); no entries ±10 min around rollover; flat before the weekend | |

**Sizing:** lots = risk budget ÷ [(stop pips + stop slippage) × pip value in USD + round-trip commission], **rounded
down** to the lot step. If the result is below the broker minimum, the trade is rejected rather than rounded up. Risk is
halved after two consecutive losses and never increased to recover losses: **no martingale**. Pip values use live
conversion rates (e.g. EUR/GBP pips are converted with GBP/USD, JPY crosses with USD/JPY). Gold: 1 lot = 100 oz,
pip = $0.10. FX: 1 lot = 100,000 base units, pip = 0.0001 (0.01 for JPY).

**Emergency stop:** *halt new orders* (positions keep SL/TP and stay monitored) or *halt + flatten*. Any trader can
engage it; only an admin can release it.

## Execution modes

| Mode | Default | What happens |
|---|---|---|
| **Paper** | ✅ | Internal simulator on live quotes: buys at ask + slippage, sells at bid − slippage, commission per lot, gap-aware stops, limit TPs only on trade-through, P&L converted to USD. |
| **Demo** | | Orders go to your broker **demo** account (OANDA practice or MT5 demo). SL and final TP are attached at the broker. ATLAS manages TP1 partials, breakeven and +1R stop moves through the broker API, and reconciles every minute. |
| **Live** | ❌ disabled | Same as demo on a real-money account. Requires `ATLAS_LIVE_TRADING_ALLOWED=true`, a live broker account, and an admin typing the confirmation phrase. Arming live leaves automatic trading **off** until it is turned on separately. |

Paper, demo, live and backtest results are stored and displayed separately and are never combined.

## Backtesting

Backtests use broker history (OANDA/MT5) or bars ATLAS has recorded from the public feed. Signals fill at the next
bar's open with half-spread + slippage; per-bar spreads from broker bid/ask data are used when available. Stops are
checked before targets, gaps fill at the open, and commission is charged per lot. Sizing and position rules are the
same as live. Reports include in-sample vs out-of-sample results and walk-forward optimisation. **Not replayed:** the
historical news blackout and session filter (no reliable calendar archive is wired in). Cross-pair pip values use the
current conversion rate, and the report flags this.

## Security

bcrypt passwords, lockout and login rate limiting; httpOnly SameSite=Strict JWT session cookie; RBAC (viewer/trader/admin);
a CSRF header on mutations; CORS and WebSocket origin checks; API rate limits; CSP and other security headers; an audit log
of all control actions; secrets redacted from logs. Broker tokens and MT5 credentials come from the environment or the
MT5 terminal only. They are never stored in the database, never sent to the frontend, and never sent to the AI.
Untrusted feed data is shape- and sanity-checked: crossed books and implausible bars are rejected, and cross-source
divergence blocks trading. Duplicate orders are prevented with deterministic client ids (DB-unique, OANDA
`clientExtensions`, MT5 comment check in the bridge), and broker orders are persisted before they are sent.

## Testing

```bash
cd backend && pytest                       # 112 tests (instruments, pip values, margin, sessions/DST, calendar, validation,
                                           # strategies, AI analyst, risk, paper broker, backtester, OANDA/MT5 adapters,
                                           # API/RBAC, agent end-to-end for XAU/USD and forex)
ATLAS_NETWORK_TESTS=1 pytest tests/test_network_integration.py   # live public quotes, paper round trips, calendar, FRED
cd frontend && npm test && npm run lint && npm run build
pip-audit -r backend/requirements.txt && (cd frontend && npm audit --omit=dev)
```

## What requires credentials

| Capability | Needs |
|---|---|
| Paper trading on live quotes, calendar, US10Y, dashboard | nothing |
| Full candle history (instant strategy warm-up, backtests over any range) | MetaApi (MT5), OANDA, or the MT5 Windows bridge |
| Demo account trading | MT5 demo account via **MetaApi (no Windows)**, OANDA practice account, or MT5 + Windows bridge |
| Live account trading | live broker account + `ATLAS_LIVE_TRADING_ALLOWED=true` + admin arming |
| AI commentary | `ANTHROPIC_API_KEY` |

See [`docs/BROKERS.md`](docs/BROKERS.md) for step-by-step OANDA and MT5 setup.
