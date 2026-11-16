# Architecture

## Processes
* **api** (`uvicorn atlas.api.app:app`): REST, WebSocket fan-out, auth, backtest jobs, static UI.
* **worker** (`python -m atlas.worker`): the only process that places orders. With `ATLAS_EMBEDDED_WORKER=true` it runs inside the API process (single-process mode).
* **PostgreSQL**: the source of truth for config, signals, decisions, orders, fills, positions, snapshots, risk events, activity, backtests and audit.
* **Redis**: pub/sub for real-time events (activity, quotes, scanner, positions) from worker to API to browsers.

The API never executes trades. Operator actions such as closing a position or flattening are queued in the `commands`
table and processed by the worker on its next fast tick (≤ 3 s). Configuration changes (kill switch, limits) are read by the worker every tick.

## Module map (`backend/atlas`)
| Module | Responsibility |
|---|---|
| `marketdata/http.py` | Rate-limited, retrying HTTP client |
| `marketdata/providers.py` | Binance / Coinbase / Kraken adapters |
| `marketdata/ws.py` | Reconnecting Coinbase/Kraken ticker feeds |
| `marketdata/validation.py` | Candle validation, gaps, duplicates, staleness |
| `marketdata/service.py` | Per-symbol state, refresh cadence, readiness checks, persistence |
| `indicators.py` | Causal EMA/SMA/RSI/MACD/ATR/ADX/VWAP/pivots/S&R |
| `strategies/library.py` | Strategies A–D, structured `Signal` output |
| `strategies/token_scanner.py` | Strategy E — Solana token safety scanner |
| `decision.py` | Scoring, classification, calibration, track-record penalty |
| `commentary.py` | Optional Claude narrative (post-decision, advisory) |
| `risk.py` | Portfolio gates, trade checks, position sizing |
| `execution/costs.py` | Fee and slippage model |
| `execution/rules.py` | Stop/target/breakeven/time-stop rules (pure) |
| `execution/paper.py` | Paper broker (fills, partials, protective orders, accounting) |
| `execution/live.py` | Jupiter live executor (gated) |
| `portfolio.py` | Accounts, mark-to-market, metrics, analytics |
| `backtest.py` | Backtester, OOS split, walk-forward |
| `agent.py` | Orchestrator loops and activity narration |
| `api/` | FastAPI routes, backtest jobs, WebSocket |
| `security.py` | Passwords, sessions, RBAC, CSRF, rate limiting, audit |

## Decision pipeline for one symbol (every closed 5 m bar)
1. Refresh candles (1m, 5m, 1h, 4h), validate them, and compute readiness (fresh, complete, venues agree).
2. Each enabled strategy returns a `Signal` (`long` / `exit` / `none` + reasons + features).
3. `decision.evaluate` scores long signals across nine factors, applies an exposure penalty and a track-record penalty, adds risk flags, and classifies the result.
4. The best long candidate is persisted (`signals`, `decisions`) and narrated.
5. If it is actionable, above the threshold, and auto paper trading is on: `risk.evaluate_trade` checks every rule and sizes the order.
6. If approved: the paper broker places the entry, then protective stop, TP1 and TP2. Otherwise the decision records the blocking reasons.
7. The fast loop marks positions to market and applies the position rules on every quote.
