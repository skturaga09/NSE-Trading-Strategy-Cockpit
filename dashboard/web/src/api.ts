import type {
  Recommendations,
  PlaceTradeRequest,
  PlaceTradeResponse,
  PositionsResponse,
  ValidateResponse,
  OrderForm,
  SimpleResponse,
  VcpResponse,
  OptionsForm,
  OptionsResponse,
  BacktestForm,
  BacktestResponse,
  FnoPlan,
  BreakoutsResponse,
  MarketSession,
  AttributionResponse,
  JournalRecentResponse,
  DecisionsResponse,
  IntradayContext,
  OptionChain,
  FnoScan,
  SwingScan,
  ExitsStatus,
  ExitConfig,
} from "./types";

// All requests go to /api/* and are proxied to the Python backend (see vite.config.ts).

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
  return res.json() as Promise<T>;
}

async function postJSON<TReq, TRes>(path: string, body: TReq): Promise<TRes> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok && res.status !== 400) {
    throw new Error(`POST ${path} failed: ${res.status}`);
  }
  return res.json() as Promise<TRes>;
}

export const api = {
  getRecommendations: () =>
    getJSON<Recommendations>("/api/strategy/recommendations"),

  placeTrade: (req: PlaceTradeRequest) =>
    postJSON<PlaceTradeRequest, PlaceTradeResponse>("/api/trade/place", req),

  getPositions: () =>
    getJSON<PositionsResponse>(`/api/trade/positions?_t=${Date.now()}`),

  validateTrade: (form: OrderForm) =>
    postJSON<OrderForm, ValidateResponse>("/api/plumbing/validate-trade", form),

  squareOff: (order_id: string) =>
    postJSON<{ order_id: string }, SimpleResponse>("/api/trade/square-off", { order_id }),

  squareOffAll: () =>
    postJSON<Record<string, never>, SimpleResponse>("/api/trade/square-off-all", {}),

  clearAll: () =>
    postJSON<Record<string, never>, SimpleResponse>("/api/trade/clear-all", {}),

  vcpScreen: (universe: string) =>
    postJSON<{ universe: string }, VcpResponse>("/api/strategy/vcp-screen", { universe }),

  optionsPricing: (form: OptionsForm) =>
    postJSON<OptionsForm, OptionsResponse>("/api/options/pricing", form),

  backtestEvaluate: (form: BacktestForm) =>
    postJSON<BacktestForm, BacktestResponse>("/api/backtest/evaluate", form),

  getFnoPlan: () =>
    postJSON<Record<string, never>, FnoPlan>("/api/strategy/fno-plan", {}),

  getBreakouts: () => getJSON<BreakoutsResponse>("/api/strategy/breakouts"),

  getSession: () => getJSON<MarketSession>("/api/market/session"),

  getAttribution: () =>
    getJSON<AttributionResponse>(`/api/journal/attribution?_t=${Date.now()}`),

  getJournalRecent: () =>
    getJSON<JournalRecentResponse>(`/api/journal/recent?_t=${Date.now()}`),

  refreshZerodha: () =>
    postJSON<Record<string, never>, { success: boolean; message: string }>(
      "/api/zerodha/refresh", {}),

  importKiteTrades: () =>
    postJSON<Record<string, never>, { success: boolean; message: string; imported?: number }>(
      "/api/journal/import-kite", {}),

  logDecision: (d: Record<string, unknown>) =>
    postJSON<Record<string, unknown>, { success: boolean; id: number }>("/api/journal/decision", d),

  getDecisions: () =>
    getJSON<DecisionsResponse>(`/api/journal/decisions?_t=${Date.now()}`),

  getIntradayContext: (underlying: string) =>
    getJSON<IntradayContext>(`/api/intraday/context?underlying=${underlying}&_t=${Date.now()}`),

  getOptionChain: (underlying: string) =>
    getJSON<OptionChain>(`/api/intraday/optionchain?underlying=${underlying}&_t=${Date.now()}`),

  getFnoScan: () =>
    getJSON<FnoScan>(`/api/intraday/fno-scan?_t=${Date.now()}`),

  getSwingScan: () =>
    getJSON<SwingScan>(`/api/swing/scan?_t=${Date.now()}`),

  getExitsStatus: () =>
    getJSON<ExitsStatus>(`/api/exits/status?_t=${Date.now()}`),

  getExitConfig: () =>
    getJSON<ExitConfig>(`/api/exits/config?_t=${Date.now()}`),

  setExitConfig: (patch: Partial<ExitConfig>) =>
    postJSON<Partial<ExitConfig>, ExitConfig>("/api/exits/config", patch),

  testExitAlert: () =>
    postJSON<Record<string, never>, { success: boolean; channel?: string; message?: string }>("/api/exits/test-alert", {}),

  sendExitSummary: () =>
    postJSON<Record<string, never>, { success: boolean; channel?: string; message?: string }>("/api/exits/summary-now", {}),
};
