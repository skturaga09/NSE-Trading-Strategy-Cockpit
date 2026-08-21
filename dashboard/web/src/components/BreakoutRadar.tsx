import { useEffect, useRef } from "react";
import { motion, AnimatePresence } from "motion/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { useMode } from "../App";
import { useToast } from "./Toast";
import type { Breakout } from "../types";

export function BreakoutRadar() {
  const { mode, afterHours } = useMode();
  const toast = useToast();
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["breakouts"],
    queryFn: api.getBreakouts,
    refetchInterval: 15_000,
  });
  const seen = useRef<Set<string>>(new Set());

  // Flash a toast the first time a symbol actually breaks out.
  useEffect(() => {
    for (const b of data?.breakouts ?? []) {
      const key = `${b.symbol}:${b.state}`;
      if (b.state === "BROKEN_OUT" && !seen.current.has(key)) {
        toast.push(`🚀 BREAKOUT · ${b.symbol} crossed ₹${b.pivot}\nEntry ₹${b.positional.entry} → T1 ₹${b.positional.target1} (R:R ${b.positional.gross_rr})`, "success");
      }
      seen.current.add(key);
    }
  }, [data, toast]);

  const place = useMutation({
    mutationFn: ({ b, intraday }: { b: Breakout; intraday: boolean }) => {
      const leg = intraday ? b.intraday : b.positional;
      return api.placeTrade({
        mode, symbol: b.symbol, quantity: b.qty, price: leg.entry,
        stop_loss_price: leg.stop, target_price: intraday ? b.intraday.target! : b.positional.target1!,
        is_option: false, product: intraday ? "MIS" : "CNC", order_type: "LIMIT",
        transaction_type: "BUY", strategy_origin: intraday ? "Breakout Radar (Intraday)" : "Breakout Radar (Positional)",
        available_margin: 1e7, allow_after_hours: afterHours,
      });
    },
    onSuccess: (r, v) => {
      if (r.success) { toast.push(`▲ ${v.intraday ? "INTRADAY" : "POSITIONAL"} · BUY ${v.b.qty} ${v.b.symbol} @ ₹${v.intraday ? v.b.intraday.entry : v.b.positional.entry}`, "success"); qc.invalidateQueries({ queryKey: ["positions"] }); }
      else toast.push(`✕ ${r.message ?? "rejected"}`, "error");
    },
  });

  const list = data?.breakouts ?? [];
  if (list.length === 0) return null;

  return (
    <div className="panel rounded-lg p-4">
      <div className="mb-3 flex items-center gap-2">
        <span className="pip h-2 w-2 rounded-full bg-signalgreen" style={{ color: "var(--green)" }} />
        <h3 className="font-mono text-xs font-bold uppercase tracking-widest text-signalgreen">Breakout Radar</h3>
        <span className="font-mono text-[10px] text-muted">{list.length} live · {data?.source}</span>
      </div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        <AnimatePresence>
          {list.map((b) => <BreakoutCard key={b.symbol} b={b} onTrade={(intraday) => place.mutate({ b, intraday })} pending={place.isPending} />)}
        </AnimatePresence>
      </div>
    </div>
  );
}

function BreakoutCard({ b, onTrade, pending }: { b: Breakout; onTrade: (intraday: boolean) => void; pending: boolean }) {
  const broke = b.state === "BROKEN_OUT";
  const accent = broke ? "var(--green)" : "var(--gold)";
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0 }}
      className="relative overflow-hidden rounded-md border bg-raised/40 p-3"
      style={{ borderColor: `color-mix(in srgb, ${accent} 40%, transparent)` }}
    >
      {broke && (
        <motion.div className="pointer-events-none absolute inset-0"
          animate={{ opacity: [0.15, 0, 0.15] }} transition={{ duration: 1.6, repeat: Infinity }}
          style={{ background: `radial-gradient(80% 100% at 50% 0%, ${accent}, transparent 70%)` }} />
      )}
      <div className="relative flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="font-display text-sm font-bold text-ink">{b.symbol}</span>
          <span className="rounded px-1.5 py-0.5 font-mono text-[9px] font-bold uppercase" style={{ background: `color-mix(in srgb, ${accent} 15%, transparent)`, color: accent }}>
            {broke ? "● broke out" : "◇ imminent"}
          </span>
        </div>
        <span className="font-mono text-[10px] text-muted">score {b.composite_score}</span>
      </div>
      <div className="relative mt-1 font-mono text-[11px] text-muted">
        LTP <span className="tnum text-ink">₹{b.ltp}</span> · pivot <span className="tnum">₹{b.pivot}</span>
        <span className="tnum" style={{ color: accent }}> ({b.above_pivot_pct >= 0 ? "+" : ""}{b.above_pivot_pct}%)</span>
      </div>

      <div className="relative mt-2 grid grid-cols-2 gap-2">
        <Leg title="POSITIONAL" entry={b.positional.entry} stop={b.positional.stop} target={b.positional.target1!}
          rr={b.positional.gross_rr} net={b.positional.net_profit_pct} onTrade={() => onTrade(false)} pending={pending} />
        <Leg title="INTRADAY" entry={b.intraday.entry} stop={b.intraday.stop} target={b.intraday.target!}
          rr={b.intraday.gross_rr} net={b.intraday.net_profit_pct} onTrade={() => onTrade(true)} pending={pending} />
      </div>
    </motion.div>
  );
}

function Leg({ title, entry, stop, target, rr, net, onTrade, pending }: {
  title: string; entry: number; stop: number; target: number; rr: number | null; net: number; onTrade: () => void; pending: boolean;
}) {
  return (
    <div className="rounded border border-line bg-panel/60 p-2">
      <div className="flex items-center justify-between">
        <span className="font-mono text-[9px] uppercase tracking-widest text-muted">{title}</span>
        <span className="font-mono text-[10px]"><span className="text-muted">R:R</span> <span className="tnum text-cyan">{rr ?? "—"}</span></span>
      </div>
      <div className="mt-1 font-mono text-[10px] leading-relaxed text-muted">
        E <span className="tnum text-ink">{entry}</span> · SL <span className="tnum text-signalred">{stop}</span> · T <span className="tnum text-signalgreen">{target}</span>
      </div>
      <div className="font-mono text-[10px] text-muted">net <span className="tnum" style={{ color: net >= 0 ? "var(--green)" : "var(--red)" }}>{net >= 0 ? "+" : ""}{net}%</span></div>
      <button onClick={onTrade} disabled={pending}
        className="mt-1.5 w-full rounded border border-gold/40 bg-gold/10 py-1 font-mono text-[10px] font-bold uppercase text-gold hover:bg-gold/20 disabled:opacity-50">
        ⚡ trade {title.toLowerCase()}
      </button>
    </div>
  );
}
