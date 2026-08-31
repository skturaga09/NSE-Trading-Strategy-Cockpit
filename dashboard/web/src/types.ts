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
  ideas_source?: string;
  themes_live?: boolean;
  top_themes?: { theme: string; conviction: number; driver: string }[];
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
  allow_after_hours?: boolean;
  signal?: Record<string, unknown>;
}

export interface MarketSession {
  is_open: boolean;
  session: string;
  now_ist: string;
  message: string;
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

// --- Breakout radar ---
export interface BreakoutLeg {
  entry: number;
  stop: number;
  target?: number;
  target1?: number;
  target2?: number;
  gross_rr: number | null;
  net_reward: number;
  net_profit_pct: number;
  friction: number;
}
export interface Breakout {
  symbol: string;
  state: "BROKEN_OUT" | "IMMINENT";
  ltp: number;
  pivot: number;
  above_pivot_pct: number;
  composite_score: number;
  rs: number;
  qty: number;
  positional: BreakoutLeg;
  intraday: BreakoutLeg;
}
export interface BreakoutsResponse {
  generated_at: string;
  source: string;
  is_live?: boolean;
  count: number;
  breakouts: Breakout[];
}

// --- VCP Screener ---
export interface VcpCandidate {
  symbol: string;
  composite_score: number;
  trend_score: number;
  contraction_count: number;
  t1_depth_pct: number;
  t2_depth_pct: number;
  t3_depth_pct: number;
  volume_dryup_score: number;
  pivot_price: number;
  current_price: number;
  distance_to_pivot_pct: number;
  relative_strength_score: number;
  status: string;
  rs_vs_index_6m_pct?: number;
}
export interface VcpResponse {
  universe: string;
  total_screened: number;
  candidates_count: number;
  price_source: string;
  screening?: boolean;
  candidates: VcpCandidate[];
}

// --- Options & Greeks ---
export interface Greeks {
  delta: number | null;
  gamma: number | null;
  theta: number | null;
  vega: number | null;
  rho: number | null;
}
export interface OptionsForm {
  spot: number;
  strike: number;
  days_to_expiry: number;
  volatility: number; // decimal (0.15)
  option_type: "CALL" | "PUT";
}
export interface OptionsResponse {
  spot: number;
  strike: number;
  days_to_expiry: number;
  implied_volatility: number;
  option_type: string;
  calculated_price: number | null;
  engine: string;
  error?: string;
  greeks: Greeks;
}

// --- Weekly F&O Planner ---
export interface FnoPlan {
  macro_conviction_score: number;
  dominant_theme: string;
  selected_instrument: string;
  trade_card: {
    instrument: string;
    direction: string;
    underlying_spot: number;
    entry_zone: string;
    stop_loss_price: number;
    target_1: number;
    target_2: number;
    recommended_lots: number;
    total_capital_required: string;
    gtt_levels: { sl_trigger: number; t1_trigger: number; t2_trigger: number };
    risk_reward_ratio: string;
    rules: string[];
  };
}

// --- Backtest ---
export interface BacktestForm {
  total_trades: number;
  win_rate: number;
  avg_win_pct: number;
  avg_loss_pct: number;
  max_drawdown_pct: number;
  years_tested: number;
  num_parameters: number;
  avg_trade_value: number;
  trade_type: string;
  brokerage_per_trade: number;
  slippage_tested: boolean;
  include_india_costs: boolean;
}
export interface BacktestDimension {
  name: string;
  score: number;
  max_score: number;
  details: string;
}
export interface BacktestRedFlag {
  severity: "critical" | "warning" | "info";
  message: string;
  recommendation: string;
}
export interface BacktestResponse {
  total_score: number | null;
  max_possible: number;
  percentage: number;
  verdict: string;
  verdict_detail: string;
  adjusted_expectancy_pct: number;
  dimensions: BacktestDimension[];
  red_flags: BacktestRedFlag[];
  error?: string;
}

// --- Trade Journal / Attribution ---
export interface ExpectancyStat {
  trades: number;
  win_rate?: number;
  avg_win_r?: number;
  avg_loss_r?: number;
  expectancy_r?: number;
  avg_mfe_r?: number;
  avg_mae_r?: number;
  net_pnl?: number;
  group?: string;
  sufficient?: boolean;
}
export interface AttributionResponse {
  generated_at: string;
  min_sample: number;
  open_trades: number;
  overall: ExpectancyStat;
  by_source: ExpectancyStat[];
  by_conviction: ExpectancyStat[];
  by_regime: ExpectancyStat[];
}
export interface JournalTrade {
  order_id: string;
  ts_entry: string;
  source: string | null;
  symbol: string;
  plan_type: string | null;
  entry_price: number | null;
  stop: number | null;
  target: number | null;
  conviction: number | null;
  regime: string | null;
  sector: string | null;
  ts_exit: string | null;
  exit_price: number | null;
  exit_reason: string | null;
  r_multiple: number | null;
  net_pnl: number | null;
  net_pnl_pct: number | null;
  mfe_r: number | null;
  mae_r: number | null;
  holding_mins: number | null;
  outcome: string | null;
  status: string;
}
export interface JournalRecentResponse {
  trades: JournalTrade[];
}

// --- Intraday decision log ---
export interface DecisionRow {
  id: number;
  ts: string;
  underlying: string | null;
  expiry: string | null;
  regime: string | null;
  setup: string | null;
  direction: string | null;
  verdict: string | null;
  decision: string | null;
  gates_failed: string | null;
  planned_entry: number | null;
  planned_stop: number | null;
  planned_target: number | null;
  planned_risk: number | null;
  permitted_lots: number | null;
}
export interface DecisionsResponse {
  decisions: DecisionRow[];
  summary: {
    total: number;
    counts: Record<string, number>;
    candidates: number;
    rejected: number;
    rejection_rate: number | null;
  };
}

// --- Intraday live context (auto-fill) ---
export interface IntradayContext {
  timestamp_ist: string;
  underlying: string;
  is_live: boolean;
  source: string;
  spot: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  prev_close: number | null;
  vix: number | null;
  gap: number | null;
}

// --- Intraday ATM option chain (auto-fill) ---
export interface OptionLeg {
  symbol: string;
  ltp: number | null;
  prev_close: number | null;
  bid: number | null;
  ask: number | null;
  spread: number | null;
  volume: number | null;
  oi: number | null;
  iv: number | null;
}
export interface OptionChainRow {
  strike: number;
  atm: boolean;
  call: OptionLeg | null;
  put: OptionLeg | null;
}
export interface OptionChain {
  underlying: string;
  timestamp: string;
  is_live: boolean;
  source: string;
  spot: number | null;
  atm: number | null;
  expiry: string | null;
  lot_size: number | null;
  rows: OptionChainRow[];
}

// --- Intraday F&O scanner (recommendations) ---
export interface FnoCandidate {
  symbol: string;
  ltp: number;
  prev_close: number;
  pct_change: number;
  vs_vwap_pct: number | null;
  range_pos: number | null;
  gap_pct: number | null;
  volume: number | null;
  score: number;
  bias: "LONG" | "SHORT";
  lot_size: number | null;
  move: number;
  pnl_per_lot: number | null;
}
export interface FnoScan {
  timestamp: string;
  is_live: boolean;
  source: string;
  universe: number;
  scanned?: number;
  longs: FnoCandidate[];
  shorts: FnoCandidate[];
}

// --- Overnight swing scan ---
export interface OiBuildup {
  label: string;
  lean: "bullish" | "bearish";
  oi: number;
  oi_chg_pct: number | null;
}
export interface SwingPlan {
  entry: number;
  stop: number;
  target: number;
  stop_pct: number;
  per_lot_risk: number;
  max_lots: number;
  notional_1lot: number;
  fits: boolean;
}
export interface SwingCandidate {
  symbol: string;
  ltp: number;
  prev_close: number;
  pct_change: number;
  range_pos: number;
  vs_vwap_pct: number;
  range_pct: number;
  score: number;
  lot_size: number;
  expiry: string;
  bias: "LONG" | "SHORT";
  buildup: OiBuildup | null;
  plan: SwingPlan;
}
export interface SwingScan {
  timestamp: string;
  is_live: boolean;
  source: string;
  risk: number;
  universe: number;
  scanned?: number;
  constructive: SwingCandidate[];
  weak: SwingCandidate[];
}

// --- Exit monitor ---
export interface ExitNotify {
  channel: "none" | "ntfy" | "telegram";
  ntfy_topic: string;
  telegram_token: string;
  telegram_chat_id: string;
}
export interface RatchetTier {
  above: number;
  trail: number;
}
export interface ExitConfig {
  target_pct: number;
  stop_pct: number;
  trail_pct: number;
  trail_arm_pct: number;
  ratchet_enabled: boolean;
  ratchet_tiers: RatchetTier[];
  pullback_alert_pct: number;
  time_exit: string;
  summary_every_min: number;
  kite_link: string;
  notify: ExitNotify;
}
export interface ExitPosition {
  symbol: string;
  qty: number;
  is_option: boolean;
  entry: number;
  ltp: number;
  pnl: number;
  pnl_pct: number;
  peak_pct: number;
  product: string;
  signal: "HOLD" | "STOP" | "TARGET" | "TRAIL" | "TIME";
  reason: string;
}
export interface ExitsStatus {
  timestamp: string;
  config: ExitConfig;
  positions: ExitPosition[];
  actionable: ExitPosition[];
}
