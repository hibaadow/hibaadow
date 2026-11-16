# ATLAS AI — User Guide

## Roles
| Role | Can |
|---|---|
| viewer | See everything except the audit log and user management |
| trader | + toggle scanning / auto paper trading, close positions, flatten, run backtests, engage emergency stop, trigger token scans |
| admin | + edit settings & strategy parameters, release kill switch, re-enable trading, reset paper account, arm/disarm live trading, manage users, view audit log |

## Pages

### Overview
Portfolio value, available capital, open positions, realised/unrealised P&L, daily/weekly/monthly P&L, win rate,
profit factor, max drawdown, total trades and average win/loss. These are computed from the database for the
current mode only. The **Risk gates** panel shows each portfolio-level check and whether new trades are allowed right now.

### Market Scanner
One row per asset in the universe. Price, 24 h change and volume come from the execution venue. Market cap is shown
only when DexScreener's price agrees with the exchange within 3 %. Depth ±1 % is order-book liquidity, RSI and ATR
are on the 5 m timeframe, and trend comes from the 1 h chart. Each row also shows the best signal across strategies
(classification + confidence), a risk rating and data freshness. Click a column header to sort; use the filters to narrow.

Classifications: **STRONG BUY CANDIDATE** (≥ 75), **BUY CANDIDATE** (≥ 60), **WAIT** (setup developing or score
45–59), **NO TRADE**, **EXIT** (exit conditions for an open position), **HIGH RISK** (data, liquidity, spread or
volatility flags). Confidence is a deterministic quality score, *not* a probability. Its measured calibration is on **Performance**.

### Trading Terminal
Candles (1m–4h) with EMA 9/21/50/200, session VWAP, volume and RSI. For an open position the chart draws ENTRY / STOP
/ TP1 / TP2 lines; otherwise it shows the latest signal's levels. The side panel shows position size, entry, stop,
targets, R:R, capital at risk, fees and the stop-adjustment history. Open orders and active positions are listed below.

### AI Activity
A live stream of everything the agent does: scans, per-strategy analysis (with the reason each one passed or not),
signals and scores, risk rejections (with every check), sizing, fills, stop moves, exits, token scans and system events.
Filter by event type or symbol, pause the stream, and load older events.

### Trade Journal
Every closed trade: entry and exit, size, fees, slippage, gross and net P&L, R multiple, duration, strategy, and entry and
exit reasons. Click a row to see its fills (with reference price and slippage) and the decision that opened it.
**Export CSV** exports whatever the current filter shows.

### Performance
Paper and live are separate tabs and are never combined. The page shows the equity curve (1-minute, daily, weekly,
monthly), drawdown history, the R-multiple distribution, a strategy comparison, results by asset and by trading session,
fees and slippage totals, and the confidence-calibration table.

### Backtesting
Choose symbol, strategy, timeframe, date range, capital, fees, slippage, spread and risk, then run. Results show
net return, win rate, profit factor, max drawdown, Sharpe/Sortino, expectancy, average trade return and holding time,
in-sample vs out-of-sample, walk-forward folds (with parameters chosen in-sample) and every trade. Tick several runs to compare them.

### Solana Tokens
New Solana tokens with a 0–100 risk score and flags: active mint or freeze authority, Token-2022 transfer fees, hooks or
permanent delegate, low liquidity, very new pool, no sells / buy-sell imbalance (honeypot pattern), wash-trading turnover,
holder concentration, no Jupiter sell route, and unverified LP lock. **These tokens are never traded.**

### Settings & Risk
Risk limits, trading mode, kill switch, live-trading preflight, automation toggles, universe and filters, enabled
strategies, fee and slippage model, trading hours, integration health, strategy parameters, users, and the audit log.

## Typical workflow
1. Backtest each strategy on the assets you care about and check the **out-of-sample** and **walk-forward** numbers, not just the full-period return.
2. Disable strategies with negative walk-forward expectancy (Settings → Enabled strategies).
3. Turn on auto paper trading and let it run for weeks. Compare paper results to the backtest. Large gaps usually mean the cost model or the regime doesn't match.
4. Only then consider live trading (see the README section "Live trading: what remains").
