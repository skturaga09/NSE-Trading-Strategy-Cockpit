// API response types mirroring the Python backend (dashboard/app.py).

export type BiasLabel = "BULLISH" | "BEARISH" | "NEUTRAL";

export interface MarketBias {
  bias: BiasLabel;
  score: number;
  drivers: string[];
  regime: string;
}

export interface MarketHealth {
  score: number;
  regime: string;
  advance_decline: string;
  stocks_above_200dma_pct: number;
  new_52w_highs: number;
  new_52w_lows: number;
  nifty_last?: number | null;
  nifty_50dma?: number | null;
  nifty_200dma?: number | null;
}

export interface TradeIdea {
  rank: number;
  type: "EQUITY_MOMENTUM" | "INDEX_FNO";
  symbol: string;
  direction: string;
  action: string;
  conviction: number;
  rationale: string[];
  tradeable?: boolean;
  is_option?: boolean;
  product?: string;
  transaction_type?: string;
  // levels (present when concrete/tradeable)
  entry_price?: number;
  stop_loss?: number;
  target?: number;
  suggested_qty?: number;
  qty?: number;
  entry_zone?: string;
  instrument?: string;
  theme?: string;
}

export interface Recommendations {
  generated_at: string;
  market_bias: MarketBias;
  market_health: MarketHealth;
  is_live: boolean;
  data_source: string;
  as_of: string | null;
  headline: string;
  ideas: TradeIdea[];
}

export interface PlaceTradeRequest {
  mode: string;
  symbol: string;
  quantity: number;
  price: number;
  stop_loss_price?: number | null;
  target_price?: number | null;
  is_option: boolean;
  product: string;
  order_type: string;
  transaction_type: string;
  strategy_origin: string;
  available_margin: number;
}

export interface PlaceTradeResponse {
  success: boolean;
  order_id?: string;
  message?: string;
  mode?: string;
  sliced_orders_executed?: number;
  errors?: string[];
}

// --- Plumbing & Orders ---

export interface PositionsSummary {
  total_pnl: number;
  unrealized_pnl: number;
  realized_pnl: number;
  active_count: number;
  closed_count: number;
  total_trades: number;
  win_rate_pct: number;
  total_capital_invested: number;
  last_updated: string;
  data_source: string;
}

export interface Position {
  order_id: string;
  timestamp: string;
  strategy_origin?: string;
  symbol: string;
  transaction_type: string;
  product: string;
  quantity: number;
  entry_price: number;
  current_price: number;
  pnl: number;
  gross_pnl?: number;
  friction_costs?: number;
  pnl_pct: number;
  stop_loss_price?: number | null;
  target_price?: number | null;
  status: string;
  is_option?: boolean;
}

export interface PositionsResponse {
  summary: PositionsSummary;
  trades: Position[];
}

export type DiagStatus = "PASSED" | "WARNING" | "FAILED";

export interface Diagnostic {
  check_name: string;
  status: DiagStatus;
  message: string;
  details?: Record<string, unknown>;
}

export interface CostBreakdown {
  trade_value: number;
  brokerage: number;
  stt: number;
  stamp_duty: number;
  exchange_charges: number;
  sebi_charges: number;
  gst: number;
  total_friction: number;
  friction_pct: number;
  break_even_points: number;
}

export interface ValidateResponse {
  is_valid: boolean;
  suggested_limit_price?: number;
  sliced_orders: { slice_number: number; quantity: number }[];
  cost_breakdown: CostBreakdown | null;
  warnings: string[];
  errors: string[];
  diagnostics: Diagnostic[];
}

export interface OrderForm {
  symbol: string;
  transaction_type: string;
  product: string;
  order_type: string;
  is_option: boolean;
  quantity: number;
  price: number;
  stop_loss_price: number;
  available_margin: number;
}

export interface SimpleResponse {
  success: boolean;
  message?: string;
}
