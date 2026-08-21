import type {
  Recommendations,
  PlaceTradeRequest,
  PlaceTradeResponse,
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
};
