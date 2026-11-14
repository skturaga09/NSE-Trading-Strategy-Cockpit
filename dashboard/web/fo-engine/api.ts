// Client for /api/engine/* (engine/api.py). Same-origin fetches only; the backend refuses anything else (Q-10-3).
// No credential of any kind exists in this module.
import { useQuery } from "@tanstack/react-query";

export type Unavail = { UNAVAILABLE: string };
export type Maybe<T> = T | Unavail;
export type Status = "OK" | "STALE" | "UNAVAILABLE";

export interface Envelope<T> {
  panel: string;
  mode: "LIVE" | "REPLAY";
  now_ns: number;
  status: Status;
  reason: string | null;
  provenance: { source: string; observed_ns: number | null; received_ns: number | null; processed_ns: number | null; tz: string };
  age_s: number | null;
  stale_after_s: number | null;
  config_version: string;
  data: T | null;
}

export interface View { date: string; asOf: number | null }
export interface Session { date: string; open_ns: number; close_ns: number; signals: boolean; dashboard: boolean; status: boolean }

const BASE = "/api/engine";

export async function get<T>(path: string): Promise<T> {
  const r = await fetch(BASE + path, { headers: { Accept: "application/json" }, credentials: "same-origin" });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json() as Promise<T>;
}

export async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(BASE + path, {
    method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json", Accept: "application/json" }, body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json() as Promise<T>;
}

const qs = (v: View, extra: Record<string, string | number | null | undefined> = {}) => {
  const p = new URLSearchParams({ date: v.date });
  if (v.asOf != null) p.set("as_of", String(v.asOf));
  for (const [k, x] of Object.entries(extra)) if (x != null) p.set(k, String(x));
  return "?" + p.toString();
};

// live views poll; a replayed view is fixed at its as_of, so it is fetched once
const poll = (v: View, ms: number) => (v.asOf == null ? ms : false);

export const useSessions = () =>
  useQuery({ queryKey: ["fo", "sessions"], queryFn: () => get<{ today: string; sessions: Session[] }>("/sessions"), refetchInterval: 60_000 });

export const useEnv = <T,>(name: string, v: View, extra: Record<string, string | number | null | undefined> = {}, ms = 15_000) =>
  useQuery({ queryKey: ["fo", name, v, extra], queryFn: () => get<Envelope<T>>(`/${name}${qs(v, extra)}`), refetchInterval: poll(v, ms) });

export const useSignal = <T,>(id: string | null, v: View) =>
  useQuery({ queryKey: ["fo", "signal", id, v], enabled: !!id, refetchInterval: poll(v, 30_000),
    queryFn: () => get<Envelope<T>>(`/signal/${encodeURIComponent(id!)}${qs(v)}`) });

export const usePerformance = <T,>(ledger: "SIMULATED" | "ACTUAL") =>
  useQuery({ queryKey: ["fo", "performance", ledger], refetchInterval: 60_000,
    queryFn: () => get<{ ledger: string; status: Status; reason: string | null; now_ns: number; config_version: string; data: T }>(`/performance?ledger=${ledger}`) });
