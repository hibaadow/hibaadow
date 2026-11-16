export type Check = { name: string; passed: boolean; detail: string };
export type Mode = "paper" | "demo" | "live";

export type Overview = {
  mode: Mode; currency: string; starting_capital: number; balance: number; equity: number; margin_used: number; margin_free: number;
  margin_level_pct: number | null; notional_exposure: number; effective_leverage: number | null; unrealized_pnl: number; realized_pnl: number;
  open_positions: number; account_source: string; max_drawdown_pct: number; day_pnl: number; day_pnl_pct: number; week_pnl: number; week_pnl_pct: number;
  month_pnl: number; month_pnl_pct: number; total_trades: number; wins: number; losses: number; win_rate: number | null; profit_factor: number | null;
  profit_factor_note?: string; avg_win: number | null; avg_loss: number | null; net_pnl: number; expectancy: number | null; expectancy_r?: number | null;
  fees_paid: number; gates: Check[]; trading_allowed: boolean; halt: string | null; results_label: string; currency_risk: Record<string, number>;
  agent: { alive: boolean; ts?: number; cycle?: number; last_scan?: number | null; last_error?: string | null; data_source?: string; mode_problems?: string[] };
  config: { mode: Mode; kill_switch: boolean; trading_enabled: boolean; scanning: boolean; auto_trading: boolean; risk_per_trade_pct: number; data_source: string };
};

export type MarketRow = {
  symbol: string; display: string; asset_class: "gold" | "forex"; bid: number | null; ask: number | null; mid: number | null; spread_pips: number | null;
  spread_limit: number; session: string; market_open: boolean; data_ok: boolean; data_issues: string[]; signal: string; direction: "BUY" | "SELL" | null;
  confidence: number; strategy: string | null; risk_rating: string; digits: number; rsi?: number | null; atr?: number | null; atr_pips?: number | null;
  trend_1h?: string; trend_4h?: string; structure?: string; change_24h_pct?: number | null; atr_percentile?: number | null; bars?: Record<string, number>;
  levels?: { prev_day_high: number | null; prev_day_low: number | null; asia_high: number | null; asia_low: number | null; asia_complete: boolean };
};

export type Markets = { ts: number | null; source: string; strength: Record<string, number>; us10y: US10Y | null; gold: MarketRow[]; forex: MarketRow[] };
export type US10Y = { value: number; date: string; change_5d_bp: number; trend: string; source: string; history: { date: string; value: number }[] };

export type Position = {
  id: number; mode: Mode; symbol: string; display: string; asset_class: string; digits: number; strategy: string; side: "buy" | "sell"; status: string;
  broker_id: string | null; opened_at: string | null; closed_at: string | null; created_at: string; lots: number; initial_lots: number; entry_price: number;
  exit_price: number | null; stop_price: number; initial_stop: number; tp1: number; tp2: number | null; tp1_hit: boolean; risk_amount: number;
  commission: number; swap: number; fees: number; slippage: number; gross_pnl: number; net_pnl: number; pip_value_usd: number; stop_pips: number | null;
  r_multiple: number | null; rr: number | null; last_price: number | null; unrealized_pnl: number | null; entry_reason: string; exit_reason: string | null;
  duration_s: number | null; decision_id: number | null; stop_history: { ts: string; stop: number; reason: string }[];
};

export type Order = {
  id: number; client_order_id: string; mode: string; position_id: number | null; symbol: string; display: string; side: string; type: string; purpose: string;
  lots: number; filled_lots: number; limit_price: number | null; stop_price: number | null; avg_fill_price: number | null; status: string; fees: number;
  reason: string | null; venue: string; broker_order_id: string | null; created_at: string;
};

export type Activity = { id: number; ts: string; kind: string; symbol: string | null; message: string; explanation: string | null; data: Record<string, unknown> };

export type EconEvent = { title: string; currency: string; time: string; impact: string; forecast: string; previous: string; central_bank: boolean; affects?: string[] };

export type Proposal = {
  id: number; ts: string; symbol: string; display: string; asset_class: string; digits: number; strategy: string; strategy_label: string; timeframe: string | null;
  direction: "BUY" | "SELL" | null; classification: string; confidence: number; entry: number | null; stop_loss: number | null; take_profit: number | null;
  take_profit_2: number | null; risk_reward: number | null; lots: number | null; risk_amount: number | null;
  est_costs: { spread_usd?: number; commission_usd?: number; slippage_usd?: number; total_usd?: number; spread_pips?: number };
  evidence: { category: string; detail: string }[]; events: EconEvent[]; invalidation: string[];
  score_breakdown: Record<string, any>; risk_flags: string[]; explanation: string; ai_commentary: string | null; executed: boolean;
  rejected_reason: string | null; position_id: number | null; outcome: string | null; outcome_r: number | null;
};
