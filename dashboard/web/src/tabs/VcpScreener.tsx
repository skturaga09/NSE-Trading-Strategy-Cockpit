import { useState } from "react";
import { motion } from "motion/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { useMode } from "../App";
import { useToast } from "../components/Toast";
import type { VcpCandidate } from "../types";

const UNIVERSES: [string, string][] = [
  ["nifty50", "Nifty 50"],
  ["nifty200", "Nifty 200"],
  ["nifty500", "Nifty 500"],
];

function statusColor(s: string): string {
  return s === "ACTIONABLE_BREAKOUT_SETUP" ? "var(--green)" : "var(--gold)";
}

export function VcpScreener() {
  const [universe, setUniverse] = useState("nifty50");
  const qc = useQueryClient();
  const { mode, afterHours } = useMode();
  const toast = useToast();

  const { data, isFetching, refetch } = useQuery({
    queryKey: ["vcp", universe],
    queryFn: () => api.vcpScreen(universe),
    // Auto-poll while a real background screen is running, then stop.
    refetchInterval: (q) => (q.state.data?.screening ? 5000 : false),
  });

  const buy = useMutation({
    mutationFn: (c: VcpCandidate) => {
      const price = c.current_price || c.pivot_price;
      return api.placeTrade({
        mode, symbol: c.symbol, quantity: Math.max(1, Math.round(50000 / price)),
        price, stop_loss_price: Math.round(price * 0.95 * 100) / 100,
        target_price: Math.round(price * 1.15 * 100) / 100, is_option: false,
        product: "CNC", order_type: "LIMIT", transaction_type: "BUY",
        strategy_origin: "Minervini VCP Screener", available_margin: 1e7, allow_after_hours: afterHours,
        signal: {
          composite_score: c.composite_score, trend_score: c.trend_score, rs: c.relative_strength_score,
          distance_to_pivot_pct: c.distance_to_pivot_pct, sector: c.status, plan_type: "positional",
        },
      });
    },
    onSuccess: (r, c) => {
      if (r.success) { toast.push(`▲ ${mode.toUpperCase()} · BUY ${c.symbol} @ ₹${c.current_price || c.pivot_price}\n${r.order_id ?? ""}`, "success"); qc.invalidateQueries({ queryKey: ["positions"] }); }
      else toast.push(`✕ ${r.message ?? "rejected"}`, "error");
    },
  });

  return (
    <div className="panel space-y-4 rounded-lg p-6">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line pb-4">
        <div>
          <h2 className="font-display text-lg font-bold text-ink">Minervini VCP Screener</h2>
          <p className="font-mono text-[11px] text-muted">Trend 25% · Contraction 25% · Volume dry-up 20% · Pivot 15% · RS 15%</p>
        </div>
        <div className="flex items-center gap-2 font-mono text-xs">
          <select value={universe} onChange={(e) => setUniverse(e.target.value)}
            className="rounded-md border border-line bg-raised px-3 py-2 text-ink outline-none focus:border-gold">
            {UNIVERSES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
          <button onClick={() => refetch()} disabled={isFetching}
            className="rounded-md border border-gold/40 bg-gold/10 px-4 py-2 font-bold uppercase tracking-wider text-gold hover:bg-gold/20 disabled:opacity-50">
            {isFetching ? "⟳ screening" : "⚡ run"}
          </button>
        </div>
      </div>

      {data && <div className="font-mono text-[10px] text-muted">source: {data.price_source} · {data.candidates_count} setups / {data.total_screened} screened</div>}

      <div className="overflow-x-auto rounded-md border border-line">
        <table className="w-full text-left text-xs">
          <thead className="bg-raised/50 font-mono text-[10px] uppercase tracking-wider text-muted">
            <tr>{["Symbol", "LTP", "Score", "Contractions", "T1/T2/T3", "Pivot", "→Pivot", "RS", "Status", ""].map((h) => <th key={h} className="px-3 py-3">{h}</th>)}</tr>
          </thead>
          <tbody className="divide-y divide-line font-mono">
            {!data?.candidates.length && <tr><td colSpan={10} className="py-6 text-center text-muted">No setups.</td></tr>}
            {data?.candidates.map((c, i) => {
              const price = c.current_price || c.pivot_price;
              return (
                <motion.tr key={c.symbol} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.03 }}
                  className="transition-colors hover:bg-raised/40">
                  <td className="px-3 py-3 font-bold text-ink">{c.symbol}</td>
                  <td className="px-3 py-3 tnum text-ink">₹{price}</td>
                  <td className="px-3 py-3 tnum font-bold text-gold">{c.composite_score}</td>
                  <td className="px-3 py-3 text-muted">{c.contraction_count}×</td>
                  <td className="px-3 py-3 text-muted tnum">{c.t1_depth_pct}/{c.t2_depth_pct}/{c.t3_depth_pct}%</td>
                  <td className="px-3 py-3 tnum text-ink/80">₹{c.pivot_price}</td>
                  <td className="px-3 py-3 tnum text-signalgreen">+{c.distance_to_pivot_pct}%</td>
                  <td className="px-3 py-3"><span className="rounded bg-cyan/10 px-1.5 py-0.5 tnum text-cyan">{c.relative_strength_score}{c.rs_vs_index_6m_pct != null ? ` · ${c.rs_vs_index_6m_pct > 0 ? "+" : ""}${c.rs_vs_index_6m_pct}%` : ""}</span></td>
                  <td className="px-3 py-3"><span className="rounded px-1.5 py-0.5 text-[9px] font-bold uppercase" style={{ background: `color-mix(in srgb, ${statusColor(c.status)} 15%, transparent)`, color: statusColor(c.status) }}>{c.status.replace(/_/g, " ")}</span></td>
                  <td className="px-3 py-3">
                    <button onClick={() => buy.mutate(c)} disabled={buy.isPending}
                      className="rounded border border-gold/40 bg-gold/10 px-2.5 py-1 text-[10px] font-bold uppercase text-gold hover:bg-gold/20 disabled:opacity-50">⚡ Buy</button>
                  </td>
                </motion.tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
