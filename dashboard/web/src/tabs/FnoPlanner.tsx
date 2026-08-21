import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useQuery } from "@tanstack/react-query";
import { motion } from "motion/react";
import { api } from "../api";
import { useMode } from "../App";
import { useToast } from "../components/Toast";

export function FnoPlanner() {
  const { data, refetch, isFetching } = useQuery({ queryKey: ["fno"], queryFn: api.getFnoPlan });
  const { mode, afterHours } = useMode();
  const toast = useToast();
  const qc = useQueryClient();

  const place = useMutation({
    mutationFn: () => {
      const tc = data!.trade_card;
      return api.placeTrade({
        mode, symbol: "NIFTY24000CE", quantity: 75 * tc.recommended_lots, price: 285,
        stop_loss_price: tc.stop_loss_price, target_price: tc.target_1, is_option: true,
        product: "NRML", order_type: "LIMIT", transaction_type: "BUY",
        strategy_origin: "Weekly F&O Plan", available_margin: 1e7, allow_after_hours: afterHours,
      });
    },
    onSuccess: (r) => {
      if (r.success) { toast.push(`▲ ${mode.toUpperCase()} · Weekly F&O plan placed\n${r.order_id ?? ""}`, "success"); qc.invalidateQueries({ queryKey: ["positions"] }); }
      else toast.push(`✕ ${r.message ?? "rejected"}`, "error");
    },
  });

  if (!data) return <div className="panel rounded-lg p-8 text-center font-mono text-sm text-muted">Loading plan…</div>;
  const tc = data.trade_card;
  const dir = tc.direction === "BULLISH" ? "var(--green)" : tc.direction === "BEARISH" ? "var(--red)" : "var(--gold)";

  return (
    <div className="space-y-5">
      <div className="panel flex flex-wrap items-center justify-between gap-3 rounded-lg p-6">
        <div>
          <h2 className="font-display text-lg font-bold text-ink">Weekly F&amp;O Trade Plan</h2>
          <p className="font-mono text-[11px] text-muted">{data.dominant_theme}</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="text-right">
            <div className="font-mono text-[9px] uppercase tracking-widest text-muted">macro conviction</div>
            <div className="font-mono text-2xl font-bold text-gold tnum">{data.macro_conviction_score}<span className="text-sm text-muted">/5</span></div>
          </div>
          <button onClick={() => refetch()} disabled={isFetching} className="rounded-md border border-line px-3 py-2 font-mono text-xs text-muted hover:text-gold">↻</button>
        </div>
      </div>

      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
        className="panel overflow-hidden rounded-lg" style={{ borderLeft: `2px solid ${dir}` }}>
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line p-6">
          <div>
            <div className="font-display text-2xl font-bold text-ink">{tc.instrument}</div>
            <div className="mt-1 flex items-center gap-2 font-mono text-xs">
              <span className="rounded px-2 py-0.5 font-bold uppercase" style={{ background: `color-mix(in srgb, ${dir} 15%, transparent)`, color: dir }}>{tc.direction}</span>
              <span className="text-muted">spot <span className="tnum text-ink">₹{tc.underlying_spot}</span></span>
              <span className="text-muted">R:R <span className="text-cyan">{tc.risk_reward_ratio}</span></span>
            </div>
          </div>
          <button onClick={() => place.mutate()} disabled={place.isPending}
            className="rounded-md border border-gold/40 bg-gold/10 px-5 py-2.5 font-mono text-xs font-bold uppercase tracking-wider text-gold hover:bg-gold/20 disabled:opacity-50">
            ⚡ Trade this plan · {tc.recommended_lots} lot
          </button>
        </div>

        <div className="grid grid-cols-2 gap-px bg-line md:grid-cols-4">
          <Stat label="ENTRY ZONE" value={tc.entry_zone} />
          <Stat label="STOP LOSS" value={`₹${tc.stop_loss_price}`} tone="red" />
          <Stat label="TARGET 1" value={`₹${tc.target_1}`} tone="green" />
          <Stat label="TARGET 2" value={`₹${tc.target_2}`} tone="green" />
          <Stat label="LOTS" value={String(tc.recommended_lots)} />
          <Stat label="CAPITAL" value={tc.total_capital_required} tone="gold" />
          <Stat label="GTT · SL/T1/T2" value={`${tc.gtt_levels.sl_trigger} / ${tc.gtt_levels.t1_trigger} / ${tc.gtt_levels.t2_trigger}`} />
          <Stat label="R:R" value={tc.risk_reward_ratio} tone="cyan" />
        </div>

        <div className="p-6">
          <h3 className="font-mono text-xs font-bold uppercase tracking-wider text-ink/80">Execution rules</h3>
          <ul className="mt-2 space-y-1.5">
            {tc.rules.map((r, i) => (
              <li key={i} className="flex gap-2 text-[12px] text-muted"><span className="text-gold-dim">{String(i + 1).padStart(2, "0")}</span>{r}</li>
            ))}
          </ul>
        </div>
      </motion.div>
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: "red" | "green" | "gold" | "cyan" }) {
  const color = tone === "red" ? "var(--red)" : tone === "green" ? "var(--green)" : tone === "gold" ? "var(--gold)" : tone === "cyan" ? "var(--cyan)" : "var(--ink)";
  return (
    <div className="bg-panel p-4">
      <div className="font-mono text-[9px] uppercase tracking-widest text-muted">{label}</div>
      <div className="mt-1 font-mono text-sm font-bold tnum" style={{ color }}>{value}</div>
    </div>
  );
}
