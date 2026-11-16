# Integrations

All market-data integrations use **public, keyless endpoints**. Each provider has its own token-bucket rate limiter,
exponential back-off, `Retry-After` handling for 418/429, and validation of response shape and content-type. Health is
written to `integration_status` and shown on Settings → Integrations.

| Provider | Base URL (env var) | Used for | Limits / notes |
|---|---|---|---|
| Binance spot market data | `ATLAS_BINANCE_REST_URL` = `https://data-api.binance.vision` | klines 1m/5m/15m/1h/4h, `bookTicker`, `depth` (±1 % liquidity), `ticker/24hr`; backtest history (paged 1000 bars) | Public mirror of Binance market data. `api.binance.com` and the Binance WebSocket are geo-blocked in some regions, so they are not required. |
| Coinbase Exchange | `ATLAS_COINBASE_REST_URL`, `ATLAS_COINBASE_WS_URL` | REST candle fallback (1m–1h); WebSocket `ticker` for reference prices | USD books (USDC is unified into USD on Coinbase). |
| Kraken | `ATLAS_KRAKEN_REST_URL`, `ATLAS_KRAKEN_WS_URL` (v2) | REST OHLC fallback (incl. 4h); WebSocket ticker for reference prices | 1 req/s budget on REST. |
| DexScreener | `ATLAS_DEXSCREENER_URL` | `/token-profiles/latest/v1`, `/token-boosts/latest/v1` discovery; `/tokens/v1/solana/{mints}` pair data; market cap enrichment | ~60 req/min. Market caps are only accepted when the pair price agrees with the exchange within 3 %. |
| Jupiter | `ATLAS_JUPITER_URL` = `https://lite-api.jup.ag` | `/swap/v1/quote` sell-route probe (honeypot signal); live: `/swap/v1/quote` + `/swap/v1/swap` | The free lite tier is rate-limited. For production live trading, use a Jupiter API key tier (`api.jup.ag`) by changing the URL. |
| Solana RPC | `ATLAS_SOLANA_RPC_URL` | `getAccountInfo` (jsonParsed mint: authorities, Token-2022 extensions), `getTokenLargestAccounts`; live: `simulateTransaction`, `sendTransaction`, `getSignatureStatuses`, `getBlockHeight`, `getTokenAccountsByOwner` | The public endpoint returns 429 for holder queries. Use a dedicated provider (Helius, Triton, QuickNode, Alchemy) for reliable results. |
| Anthropic Claude | `ANTHROPIC_API_KEY`, `ATLAS_AI_COMMENTARY_MODEL` | 2–4 sentence commentary on executed decisions, generated from the structured facts only | Optional. Uses server-side refusal fallbacks. Never influences execution. |

## Data-quality protections
* Closed candles only. The still-forming bar is dropped before any decision.
* Candles with invalid OHLC (NaN, negative, high < low, > 60 % range) are rejected and counted. Duplicates are removed, misaligned timestamps are dropped, and gaps are detected. A series becomes **unusable** when > 2 % of bars are missing or the latest closed bar is older than 2 intervals; a targeted backfill is attempted once.
* If the primary venue fails, the **whole** series is replaced from one fallback venue (venues are never mixed within a series), and the quality report records it.
* Quotes older than `max_data_staleness_seconds` block new trades and pause stop processing until fresh data arrives.
* Cross-venue divergence above `max_venue_divergence_pct` (Binance vs Coinbase/Kraken reference ticks) blocks trading on that symbol, as a guard against manipulated or broken data.

## Changing providers
Every adapter lives in `backend/atlas/marketdata/providers.py` and exposes `candles()`, `quote()`, and optionally
`stats_24h()` and `depth()`. To add a venue, implement those methods and pass the instance to `MarketDataService(primary=...)`.

## Live execution setup (Solana / Jupiter)
1. Create a dedicated wallet: `solana-keygen new -o solana-keypair.json` (fund it with only what you are prepared to lose).
2. `chmod 600 solana-keypair.json` and mount it read-only into the worker (see `docker-compose.yml`).
3. Set `ATLAS_SOLANA_KEYPAIR_PATH`, `ATLAS_LIVE_TRADING_ALLOWED=true`, and a dedicated `ATLAS_SOLANA_RPC_URL`.
4. In the UI: Settings → Trading mode → type the confirmation phrase → **Arm live trading**. Preflight lists anything still missing.
5. Live-tradable symbols: SOL, JUP, WIF, BONK, JTO, RAY, PYTH (native SPL mints). BTC and ETH are excluded on Solana on purpose (wrapped assets).
