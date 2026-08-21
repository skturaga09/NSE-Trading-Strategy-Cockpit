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
};
