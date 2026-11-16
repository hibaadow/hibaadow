# ATLAS AI — Autonomous Crypto Day-Trading Agent

ATLAS AI is a full-stack trading system. It monitors crypto markets on live public
data, generates signals from four independent strategies, scores them with an
explainable decision engine, and enforces strict risk limits. It then **paper-trades
automatically** with realistic fills. It also scans newly launched Solana tokens for
rug-pull and honeypot warning signs (it never trades them).

> **Paper trading is the default.** Live trading is built (Solana / Jupiter) but
> stays disabled until a server operator *and* an admin explicitly arm it.
> Nothing here is financial advice. Backtest and paper results do not prove future profitability.

---

## Contents

1. [Architecture](#architecture)
2. [Quick start (Docker)](#quick-start-docker)
3. [Local development](#local-development)
4. [Configuration](#configuration)
5. [Using the app](#using-the-app)
6. [Integrations](#integrations)
7. [Risk management](#risk-management)
8. [Backtesting methodology](#backtesting-methodology)
9. [Security](#security)
10. [Testing](#testing)
11. [Live trading: what remains](#live-trading-what-remains)
12. [Known limitations](#known-limitations)

More detail: [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) · [`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md) · [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

---

## Architecture

```
            ┌──────────────────────── worker (python -m atlas.worker) ───────────────────────┐
 Binance ───┤ Market data service ─► Strategy engine (A–D) ─► AI decision ─► Risk engine ─► Execution
 Coinbase ──┤  validation, gaps,      trend / momentum /        engine         hard limits     paper | live(Jupiter)
 Kraken  ───┤  staleness, x-venue     breakout / VWAP           0–100 score,   sizing          │
 (REST+WS)  │  divergence checks                                classification                 ▼
 DexScreener┤ Token scanner (E) ─ Solana RPC / Jupiter honeypot probe            Position monitor (every ~3 s)
            └───────────────┬─────────────────────────────────────────────────────────────────┘
                            │ PostgreSQL (all state)        Redis pub/sub (live events)
            ┌───────────────┴──────────── api (FastAPI + static Next.js UI) ─────────────────┐
            │ REST /api/*  ·  WebSocket /api/ws  ·  auth/RBAC  ·  backtest jobs  ·  audit log    │
            └─────────────────────────────────────────────────────────────────────────────────┘
```

| Layer | Tech | Location |
|---|---|---|
| Frontend | Next.js 15 (static export), TypeScript, Tailwind v4, TradingView Lightweight Charts 5 | `frontend/` |
| API | FastAPI, WebSockets, cookie sessions (JWT, httpOnly), RBAC | `backend/atlas/api/` |
| Trading engine | Python asyncio worker | `backend/atlas/agent.py` |
| Market data | httpx (REST, rate-limited, retries), websockets (Coinbase/Kraken) | `backend/atlas/marketdata/` |
| Strategies | numpy/scipy indicators, 4 strategies + Solana scanner | `backend/atlas/strategies/`, `indicators.py` |
| Decision / risk | deterministic scoring, hard risk limits | `decision.py`, `risk.py` |
| Execution | paper simulator; Jupiter live executor | `backend/atlas/execution/` |
| Backtester | event-driven, walk-forward | `backend/atlas/backtest.py` |
| Storage | PostgreSQL 16 + Alembic migrations; Redis 7 pub/sub | `models.py`, `migrations/` |

---

## Quick start (Docker)

Requirements: Docker 24+ with Compose.

```bash
cd atlas-ai
cp .env.example .env
# edit .env: set POSTGRES_PASSWORD, ATLAS_SECRET_KEY (64 random bytes), ATLAS_ADMIN_PASSWORD (10+ chars)
python3 -c "import secrets; print(secrets.token_urlsafe(64))"   # → ATLAS_SECRET_KEY
docker compose up -d --build
```

Open **http://localhost:8000** and sign in with `ATLAS_ADMIN_USERNAME` / `ATLAS_ADMIN_PASSWORD`.
Once you've signed in, remove `ATLAS_ADMIN_PASSWORD` from `.env` (it is only used when no users exist yet).

Services: `postgres`, `redis`, `api` (UI + REST + WebSocket on port 8000), `worker` (trading engine).
Logs: `docker compose logs -f worker`. The API binds to `127.0.0.1` only. Put a TLS reverse proxy
(Caddy, nginx, Traefik) in front of it and set `ATLAS_COOKIE_SECURE=true` for any remote access.

---

## Local development

Requirements: Python 3.11+, Node 20+, PostgreSQL 14+, Redis 6+ (Redis is optional in single-process mode).

```bash
# 1. database
createuser -P atlas            # choose a password
createdb -O atlas atlas
createdb -O atlas atlas_test   # for the test-suite

# 2. backend
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp ../.env.example .env        # set ATLAS_ENV=development, ATLAS_DATABASE_URL, ATLAS_SECRET_KEY, ATLAS_ADMIN_PASSWORD
                               # ATLAS_EMBEDDED_WORKER=true runs the engine inside the API process
uvicorn atlas.api.app:app --port 8000       # migrations run automatically on start

# 3. frontend (hot reload on :3000, proxies /api to :8000)
cd ../frontend
npm ci
NEXT_PUBLIC_WS_URL=ws://localhost:8000/api/ws npm run dev
```

**Or serve the production UI from the API:** `cd frontend && npm run build`, then set
`ATLAS_FRONTEND_DIST=/abs/path/to/frontend/out` in `backend/.env` and open http://localhost:8000.

**Separate worker** (production topology): set `ATLAS_EMBEDDED_WORKER=false` on the API and run
`python -m atlas.worker` with the same environment. Events reach browsers through Redis.

Admin CLI:
```bash
python -m atlas.cli create-user alice --role trader     # prompts for password
python -m atlas.cli init-db                             # apply migrations
alembic upgrade head                                    # same, via Alembic
```

---

## Configuration

Server settings are environment variables (see [`.env.example`](.env.example)). Secrets are only ever read
from the environment or mounted files. They are never stored in the database, sent to the frontend, or written to logs.

Trading settings (risk limits, universe, strategies, automation, fees, trading hours) are stored in
PostgreSQL. They are edited on **Settings & Risk** (admin only) and validated server-side; the hard ceilings
cannot be exceeded. The engine picks up changes within ~3 seconds.

| Setting | Default | Hard limit |
|---|---|---|
| Risk per trade | 0.5 % of equity | ≤ 1 % |
| Max daily loss | 2 % | ≤ 2 % |
| Max weekly loss | 5 % | ≤ 5 % |
| Max open positions | 3 | ≤ 3 |
| Min reward : risk (net of fees + slippage) | 2.0 | ≥ 2.0 |
| Max portfolio / position exposure | 60 % / 25 % | ≤ 100 % (spot only, no leverage) |
| Max slippage / spread | 25 / 15 bps | |
| Cooldown | 120 min after 3 consecutive losses | |
| Max daily trades | 10 | |
| Min order-book depth ±1 % / 24 h volume | $250k / $1M | |
| Fees (taker / maker) | 10 / 10 bps | |
| Paper starting capital | 10,000 USDC | |

---

## Using the app

**Start paper trading**
1. Sign in → **Overview**. Check that *Agent running* and *Live feed* are green.
2. Turn on **Auto paper trading** (top right). *Market scanning* is on by default.
3. Watch **AI Activity**. Every scan, rejection, sizing step, order, fill and stop adjustment is logged with its reason.
4. Open positions appear on **Overview** and **Trading Terminal** (with entry, stop and TP lines on the chart).
5. Closed trades appear in the **Trade Journal** (searchable, CSV export) and in **Performance**.

The agent only trades when a signal is classified **BUY** or **STRONG BUY**, clears the confidence threshold
(default 60) and passes **every** risk check. Long stretches with no trades are normal and intended.

**Emergency stop.** The red button in the top bar gives two choices: *Halt new orders* (keeps protective stops and
targets working) or *Halt + flatten* (closes everything at market). Any trader can engage it; only an admin can
release it. Automatic paper trading stays off until it is re-enabled by hand.

**Global trading switch** (Settings): disables new orders without the emergency semantics.

Pages: Overview · Market Scanner · Trading Terminal · AI Activity · Trade Journal · Performance ·
Backtesting · Solana Tokens · Settings & Risk. See [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md).

---

## Integrations

| Integration | Status | Credentials |
|---|---|---|
| Binance spot market data (`data-api.binance.vision`): candles 1m–4h, book ticker, depth, 24h stats | **Connected**, primary venue | none |
| Coinbase Exchange REST + WebSocket ticker | **Connected**: REST candle fallback, live reference ticks | none |
| Kraken REST + WebSocket v2 ticker | **Connected**: REST candle fallback, live reference ticks | none |
| DexScreener: new-token discovery, pair liquidity/volume, market cap | **Connected** | none |
| Jupiter (`lite-api.jup.ag`): sell-route/honeypot probe; live swap routing | **Connected** (quotes) | none for quotes |
| Solana RPC (public mainnet): mint/freeze authority, Token-2022 extensions, holders | **Connected**, but holder queries are rate-limited | optional dedicated RPC URL |
| Claude API: optional decision commentary | Needs `ANTHROPIC_API_KEY` | API key |
| Live execution (Jupiter swaps signed with a local keypair) | **Disabled** by default | keypair file + operator gate |

Binance's main API and WebSocket (`api.binance.com`, `stream.binance.com`) are geo-blocked in some regions. ATLAS
uses the official public market-data mirror for REST. Real-time ticks come from Coinbase and Kraken WebSockets, which
also drive a **cross-venue divergence check**: if venues disagree by more than 1.5 %, trading on that symbol is blocked.
See [`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md) for endpoints, limits and how to change providers.

---

## Risk management

The risk engine (`backend/atlas/risk.py`) has the final say on every new order. Neither strategies nor AI commentary can bypass it.

* Kill switch, global trading switch, trading hours.
* Daily and weekly loss limits on **equity**, so unrealised P&L counts. When a limit trips, new positions stop and a critical risk event is logged.
* Cooldown after consecutive losses. Max open positions, max daily trades, one position per symbol.
* **Mandatory stop-loss.** Size is computed from the stop distance **including fees and modelled slippage**. Risk is a fraction of *current* equity and is **halved after two consecutive losses**. Size is never increased to recover losses. No martingale, no leverage. Notional is capped by exposure limits and available cash.
* Minimum **net** reward:risk of 2.0. If a strategy's target is too close after costs, TP1 is moved out. If structural resistance sits below the required target, the trade is rejected.
* Spread, estimated slippage, order-book depth and 24 h volume limits.
* **Stale or inconsistent data blocks trading:** candle gaps, stale bars, stale quotes, or cross-venue divergence.

Position management (shared by paper trading and backtests, `execution/rules.py`): stop is checked before
targets; stop moves to breakeven at +1R; TP1 (≥ 2R net) sells 50 % and raises the stop to +1R; TP2 sells the rest;
strategy exit signals and time stops (no progress after 4 h, max hold 24 h) close the position.

---

## Backtesting methodology

* Strategies see only **closed** bars, using the same 500-bar window as the live engine. Higher-timeframe bars become visible only once complete.
* Signals at bar *i* close fill at bar *i+1* **open** + half spread + modelled slippage + taker fee. Targets fill only when price trades through them (maker fee). Stops are checked before targets inside a bar, and gaps fill at the open.
* The daily loss limit, cooldown, sizing and position rules are identical to paper trading.
* Results report **in-sample vs out-of-sample** (last 30 % by default) and **walk-forward** evaluation. Parameters are optimised on each training window and evaluated on the next unseen window, and the walk-forward efficiency is reported.
* Tests prove that changing future bars does not change past trades (`tests/test_backtest.py`).

At this build's default settings, all four strategies had **negative expectancy** on recent SOL/USDC 5-minute data
after 10 bps fees. The system reports this as-is. Use the backtester and walk-forward results to judge whether any
configuration deserves paper trading, and never assume a strategy is profitable.

---

## Security

* Authentication: bcrypt passwords (min 10 chars), account lockout after 5 failures, login rate limiting.
  Sessions are signed JWTs in an **httpOnly, SameSite=Strict** cookie (Secure behind HTTPS). `POST /api/auth/logout-all` (and any password change) rotates the session version and signs out every session.
* RBAC: `viewer` (read-only), `trader` (controls, close positions, backtests, emergency stop), `admin` (settings, users, live arming, release kill switch, audit log).
* CSRF: every state-changing request needs a custom header that cross-site pages cannot send. CORS is limited to configured origins, and WebSocket origins are checked.
* API rate limiting, request size limits, security headers (CSP, X-Frame-Options DENY, nosniff), `Cache-Control: no-store` on API responses.
* Every control action is recorded in the audit log, and secret values are stripped from audit records and logs.
* Untrusted external data: response shape and content-type are validated, OHLC is sanity-checked, token metadata is sanitised (HTML and bidi characters stripped, only https URLs kept), and Solana mint addresses are validated. Third-party market caps that disagree with exchange prices are discarded, and CSV exports are protected against formula injection.
* Duplicate-order prevention: deterministic `client_order_id` with a unique DB constraint, plus an in-flight guard for live swaps. Live orders are persisted before sending.
* Secrets come from the environment only and never reach the frontend bundle. Seed phrases are never accepted, stored or sent to any AI model.
* Dependency checks: `pip-audit -r backend/requirements.txt` and `npm audit` (run in CI, see `.github/workflows/ci.yml`).

---

## Testing

```bash
cd backend && pytest                    # 92 tests: indicators, validation, strategies, risk, sizing, costs,
                                        # paper execution, portfolio accounting, backtester (incl. look-ahead),
                                        # HTTP failure handling, token scanner, API/auth/RBAC, agent end-to-end
ATLAS_NETWORK_TESTS=1 pytest tests/test_network_integration.py   # hits live public APIs (opt-in)
cd frontend && npm test && npm run lint && npm run build
```

Tests use the `atlas_test` database (override with `ATLAS_TEST_DATABASE_URL`) and rebuild it through the Alembic migrations.

---

## Live trading: what remains

The live path (`backend/atlas/execution/live.py`) implements: Jupiter quote, price-impact guard, swap build, local
signing, RPC simulation, send, confirmation polling with blockhash-expiry handling, duplicate prevention, failure
handling, and an emergency shutdown that shares the kill switch. Before using it with real funds:

1. **Test on small amounts with a dedicated hot wallet.** The live path has unit-level coverage but has **not** been run against mainnet in this build.
2. Reconcile fills from on-chain balance deltas (`token_balance`). Live accounting currently records *quoted* amounts.
3. Use a dedicated Solana RPC with priority-fee support, and set compute-unit pricing for congested periods.
4. Stops for spot DEX swaps are **client-side**: if the worker stops, so does stop protection. Run it supervised with alerting, or use an exchange that supports native stop orders.
5. Live tracks a separate account and ledger (`mode=live`) and is never mixed with paper results. Fund it, set `ATLAS_LIVE_TRADING_ALLOWED=true`, mount the keypair (chmod 600), and arm it from Settings by typing the confirmation phrase.
6. Get legal and tax advice for your jurisdiction.

---

## Known limitations

* Spot, long-only by design (no shorting without margin).
* Public Solana RPC rate-limits `getTokenLargestAccounts`, so holder concentration often shows "unverified". Configure a dedicated RPC.
* Liquidity lock/burn cannot be verified generically from public APIs and is always reported as unverified.
* Several Solana ecosystem USDC books on Binance are thin (< $250k depth), so the liquidity rule correctly blocks them.
* The in-memory API rate limiter is per process. Use a shared limiter or gateway if you run several API replicas.
* AI commentary needs an Anthropic API key. Without one, the deterministic explanations are still shown for every decision.
