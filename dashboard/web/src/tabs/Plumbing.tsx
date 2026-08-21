import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { useMode } from "../App";
import { useToast } from "../components/Toast";
import type {
  DiagStatus,
  OrderForm,
  Position,
  ValidateResponse,
} from "../types";

const inr = (n: number) => `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
const signed = (n: number) => `${n >= 0 ? "+" : ""}${inr(n)}`;

const DEFAULT_FORM: OrderForm = {
  symbol: "NIFTY",
  transaction_type: "BUY",
  product: "NRML",
  order_type: "LIMIT",
  is_option: true,
  quantity: 75,
  price: 140,
  stop_loss_price: 95,
  available_margin: 1_000_000,
};

export function Plumbing() {
  return (
    <div className="space-y-6">
      <PositionsMonitor />
      <SignalPerformance />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <OrderDesk />
      </div>
    </div>
  );
}

/* ---------------- Signal performance by source ---------------- */

interface SignalStat {
  source: string;
  trades: number;
  wins: number;
  winRate: number;
  netPnl: number;
  avgPnl: number;
}

function SignalPerformance() {
  const { data } = useQuery({ queryKey: ["positions"], queryFn: api.getPositions, refetchInterval: 2000 });
  const trades = data?.trades ?? [];

  const groups = new Map<string, Position[]>();
  for (const t of trades) {
    const key = t.strategy_origin || "Manual";
    (groups.get(key) ?? groups.set(key, []).get(key)!).push(t);
  }
  const stats: SignalStat[] = [...groups.entries()].map(([source, ts]) => {
    const wins = ts.filter((t) => t.pnl > 0).length;
    const netPnl = ts.reduce((s, t) => s + (t.pnl || 0), 0);
    return { source, trades: ts.length, wins, winRate: Math.round((wins / ts.length) * 100), netPnl, avgPnl: netPnl / ts.length };
  }).sort((a, b) => b.netPnl - a.netPnl);

  return (
    <div className="panel space-y-3 rounded-lg p-6">
      <h2 className="flex items-center gap-2 font-display text-base font-bold text-ink">
        📡 Signal Performance <span className="font-mono text-[11px] font-normal text-muted">— net P&amp;L by source</span>
      </h2>
      {stats.length === 0 ? (
        <p className="font-mono text-[11px] text-muted">No trades yet. Place from Trade Ideas, the Breakout Radar, or the screener to start tracking.</p>
      ) : (
        <div className="overflow-x-auto rounded-md border border-line">
          <table className="w-full text-left text-xs">
            <thead className="bg-raised/50 font-mono text-[10px] uppercase tracking-wider text-muted">
              <tr>{["Signal source", "Trades", "Win rate", "Net P&L", "Avg / trade"].map((h) => <th key={h} className="px-3 py-2.5">{h}</th>)}</tr>
            </thead>
            <tbody className="divide-y divide-line font-mono">
              {stats.map((s) => (
                <tr key={s.source} className="hover:bg-raised/40">
                  <td className="px-3 py-2.5 text-ink/90">{s.source}</td>
                  <td className="px-3 py-2.5 tnum text-muted">{s.wins}/{s.trades}</td>
                  <td className="px-3 py-2.5 tnum" style={{ color: s.winRate >= 50 ? "var(--green)" : "var(--gold)" }}>{s.winRate}%</td>
                  <td className="px-3 py-2.5 tnum font-bold" style={{ color: s.netPnl >= 0 ? "var(--green)" : "var(--red)" }}>{s.netPnl >= 0 ? "+" : ""}{inr(s.netPnl)}</td>
                  <td className="px-3 py-2.5 tnum" style={{ color: s.avgPnl >= 0 ? "var(--green)" : "var(--red)" }}>{s.avgPnl >= 0 ? "+" : ""}{inr(s.avgPnl)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ---------------- Positions monitor ---------------- */

function PositionsMonitor() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data } = useQuery({
    queryKey: ["positions"],
    queryFn: api.getPositions,
    refetchInterval: 2000,
  });

  const refresh = () => qc.invalidateQueries({ queryKey: ["positions"] });

  const squareOff = useMutation({
    mutationFn: api.squareOff,
    onSuccess: (r) => { toast.push(r.message ?? "Squared off", "info"); refresh(); },
  });
  const squareOffAll = useMutation({
    mutationFn: api.squareOffAll,
    onSuccess: (r) => { toast.push(r.message ?? "Squared off all", "info"); refresh(); },
  });
  const clearAll = useMutation({
    mutationFn: api.clearAll,
    onSuccess: (r) => { toast.push(r.message ?? "Cleared", "info"); refresh(); },
  });

  const s = data?.summary;
  return (
    <div className="panel space-y-5 rounded-lg p-6">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line pb-4">
        <div className="flex items-center gap-3">
          <h2 className="flex items-center gap-2 text-base font-bold text-ink">
            📈 Active Positions &amp; Portfolio
          </h2>
          <span className="inline-flex items-center gap-1.5 rounded-full border border-signalgreen/20 bg-signalgreen/10 px-2.5 py-0.5 text-[11px] font-semibold text-signalgreen">
            <span className="h-1.5 w-1.5 animate-ping rounded-full bg-signalgreen" />
            Live P&amp;L · <span className="font-mono">{s?.last_updated ?? "—"}</span>
          </span>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <button onClick={() => squareOffAll.mutate()} className="rounded-lg border border-signalred/40 bg-signalred/10 px-2.5 py-1 font-semibold text-signalred hover:bg-signalred/20">Square Off All</button>
          <button onClick={() => { if (confirm("Clear the entire trade book?")) clearAll.mutate(); }} className="rounded-lg border border-line bg-raised px-2.5 py-1 text-muted hover:bg-raised">Clear</button>
          <button onClick={refresh} className="rounded-lg border border-cyan/40 bg-cyan/10 px-3 py-1 font-semibold text-cyan hover:bg-cyan/20">↻ Refresh</button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 text-xs md:grid-cols-4">
        <SummaryCard label="Total P&L" icon="👛"
          value={<span className={s && s.total_pnl >= 0 ? "text-signalgreen" : "text-signalred"}>{s ? signed(s.total_pnl) : "—"}</span>}
          sub={s ? <>Floating <span className="text-ink/80">{signed(s.unrealized_pnl)}</span> · Locked <span className="text-ink/80">{signed(s.realized_pnl)}</span></> : ""} />
        <SummaryCard label="Active Positions" icon="🧱"
          value={<span className="text-ink">{s?.active_count ?? 0} <span className="text-xs font-normal text-muted">Open</span></span>}
          sub={s ? <>Closed: <span className="text-ink/80">{s.closed_count}</span></> : ""} />
        <SummaryCard label="Win Rate" icon="🏆"
          value={<span className="text-cyan">{s?.win_rate_pct ?? 0}%</span>}
          sub={s ? <>Total trades: <span className="text-ink/80">{s.total_trades}</span></> : ""} />
        <SummaryCard label="Capital Allocated" icon="🪙"
          value={<span className="text-gold">{s ? inr(s.total_capital_invested) : "—"}</span>}
          sub={s?.data_source ?? ""} />
      </div>

      <div className="overflow-x-auto rounded-xl border border-line">
        <table className="w-full text-left text-xs">
          <thead className="bg-raised/50 font-mono text-[11px] uppercase text-muted">
            <tr>
              {["Order", "Time", "Strategy", "Symbol", "Type", "Qty", "Entry", "LTP", "Live P&L", "SL / Target", "Status", ""].map((h) => (
                <th key={h} className="px-3 py-3">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line bg-panel/50 font-mono">
            {!data?.trades.length && (
              <tr><td colSpan={12} className="py-6 text-center text-muted">No positions yet. Place an order below or trade an idea.</td></tr>
            )}
            {data?.trades.map((t) => (
              <PositionRow key={t.order_id} t={t} onSquareOff={(id) => { if (confirm(`Square off ${id}?`)) squareOff.mutate(id); }} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SummaryCard({ label, icon, value, sub }: { label: string; icon: string; value: React.ReactNode; sub: React.ReactNode }) {
  return (
    <div className="space-y-1 rounded-xl border border-line bg-raised/50 p-4">
      <div className="flex items-center justify-between font-medium text-muted"><span>{label}</span><span>{icon}</span></div>
      <div className="font-mono text-xl font-extrabold">{value}</div>
      <div className="pt-0.5 text-[10px] text-muted">{sub}</div>
    </div>
  );
}

const STATUS_STYLE: Record<string, string> = {
  ACTIVE: "bg-signalgreen/15 text-signalgreen",
  CLOSED: "bg-gold/15 text-gold",
  STOP_LOSS_HIT: "bg-signalred/15 text-signalred",
  TARGET_HIT: "bg-signalgreen/15 text-signalgreen",
};

function PositionRow({ t, onSquareOff }: { t: Position; onSquareOff: (id: string) => void }) {
  const net = t.pnl ?? 0;
  const gross = t.gross_pnl ?? net;
  const friction = t.friction_costs ?? 0;
  return (
    <tr className="transition-colors hover:bg-raised/60">
      <td className="px-3 py-3 text-[11px] font-bold text-ink/80">{t.order_id}</td>
      <td className="px-3 py-3 text-[10px] text-muted">{t.timestamp}</td>
      <td className="px-3 py-3 text-[10px] font-bold text-cyan">⚡ {t.strategy_origin ?? "Manual"}</td>
      <td className="px-3 py-3 font-bold text-ink">{t.symbol}</td>
      <td className="px-3 py-3">{t.transaction_type} ({t.product})</td>
      <td className="px-3 py-3 font-bold">{t.quantity}</td>
      <td className="px-3 py-3">₹{t.entry_price.toFixed(2)}</td>
      <td className="px-3 py-3 font-bold text-ink">₹{t.current_price.toFixed(2)}</td>
      <td className={`px-3 py-3 ${net >= 0 ? "text-signalgreen" : "text-signalred"} font-bold`}>
        <div>{net >= 0 ? "+" : ""}₹{net.toFixed(2)} ({t.pnl_pct >= 0 ? "+" : ""}{t.pnl_pct.toFixed(2)}%)</div>
        <div className="text-[9px] font-normal text-muted">Gross {gross >= 0 ? "+" : ""}₹{gross.toFixed(2)} · Tax −₹{friction.toFixed(2)}</div>
      </td>
      <td className="px-3 py-3 text-[10px] text-muted">
        SL {t.stop_loss_price ? `₹${t.stop_loss_price}` : "—"}<br />Tgt {t.target_price ? `₹${t.target_price}` : "—"}
      </td>
      <td className="px-3 py-3"><span className={`rounded px-2 py-0.5 text-[10px] ${STATUS_STYLE[t.status] ?? "bg-raised text-muted"}`}>{t.status}</span></td>
      <td className="px-3 py-3">
        {t.status === "ACTIVE"
          ? <button onClick={() => onSquareOff(t.order_id)} className="rounded bg-rose-600/80 px-2.5 py-1 text-[10px] font-bold text-ink hover:bg-rose-600">Square Off</button>
          : <span className="text-[10px] text-muted">{t.status}</span>}
      </td>
    </tr>
  );
}

/* ---------------- Order desk ---------------- */

function OrderDesk() {
  const qc = useQueryClient();
  const { mode, afterHours } = useMode();
  const toast = useToast();
  const [form, setForm] = useState<OrderForm>(DEFAULT_FORM);
  const [result, setResult] = useState<ValidateResponse | null>(null);

  const set = <K extends keyof OrderForm>(k: K, v: OrderForm[K]) => setForm((f) => ({ ...f, [k]: v }));

  // Live validation, debounced on any form change.
  useEffect(() => {
    const id = setTimeout(() => {
      api.validateTrade(form).then(setResult).catch(() => {});
    }, 300);
    return () => clearTimeout(id);
  }, [form]);

  const place = useMutation({
    mutationFn: () => api.placeTrade({
      mode,
      symbol: form.symbol,
      quantity: form.quantity,
      price: form.price,
      stop_loss_price: form.stop_loss_price,
      is_option: form.is_option,
      product: form.product,
      order_type: form.order_type,
      transaction_type: form.transaction_type,
      strategy_origin: "Manual Order Desk",
      available_margin: form.available_margin, allow_after_hours: afterHours,
      // Discretionary order — no signal conviction to snapshot; only capture the
      // holding style so intraday vs positional attribution still works honestly.
      signal: { plan_type: form.product === "MIS" ? "intraday" : "positional" },
    }),
    onSuccess: (r) => {
      if (r.success) {
        toast.push(`✅ ${(r.mode ?? mode).toUpperCase()} order placed\n${form.transaction_type} ${form.quantity} ${form.symbol} @ ₹${form.price}\nOrder ${r.order_id ?? ""}`, "success");
        qc.invalidateQueries({ queryKey: ["positions"] });
      } else {
        toast.push(`❌ ${r.message ?? "Order rejected"}${r.errors?.length ? "\n• " + r.errors.join("\n• ") : ""}`, "error");
      }
    },
    onError: () => toast.push("❌ Network error placing order.", "error"),
  });

  return (
    <>
      {/* Form */}
      <div className="panel space-y-4 rounded-lg p-6">
        <div className="flex items-center justify-between border-b border-line pb-3">
          <h2 className="flex items-center gap-2 text-base font-bold text-ink">✈️ Order Plumbing &amp; Execution</h2>
          <span className="text-xs text-muted">Validated vs Zerodha rules</span>
        </div>

        <div className="grid grid-cols-2 gap-4 text-sm">
          <Field label="Symbol / Ticker">
            <input value={form.symbol} onChange={(e) => set("symbol", e.target.value.toUpperCase())} className={inputCls} />
          </Field>
          <Field label="Transaction">
            <Select value={form.transaction_type} onChange={(v) => set("transaction_type", v)} options={[["BUY", "BUY (Long)"], ["SELL", "SELL (Short)"]]} />
          </Field>
        </div>

        <div className="grid grid-cols-3 gap-4 text-sm">
          <Field label="Product">
            <Select value={form.product} onChange={(v) => set("product", v)} options={[["MIS", "MIS"], ["NRML", "NRML"], ["CNC", "CNC"]]} />
          </Field>
          <Field label="Order Type">
            <Select value={form.order_type} onChange={(v) => set("order_type", v)} options={[["LIMIT", "LIMIT"], ["MARKET", "MARKET"], ["SL", "SL"], ["SL-M", "SL-M"]]} />
          </Field>
          <Field label="F&O Option?">
            <Select value={form.is_option ? "true" : "false"} onChange={(v) => set("is_option", v === "true")} options={[["true", "YES"], ["false", "NO"]]} />
          </Field>
        </div>

        <div className="grid grid-cols-3 gap-4 text-sm">
          <Field label="Quantity"><NumInput value={form.quantity} onChange={(v) => set("quantity", v)} /></Field>
          <Field label="Price (₹)"><NumInput value={form.price} onChange={(v) => set("price", v)} step={0.05} /></Field>
          <Field label="Stop-Loss (₹)"><NumInput value={form.stop_loss_price} onChange={(v) => set("stop_loss_price", v)} step={0.05} /></Field>
        </div>

        <Field label="Available Margin (₹)"><NumInput value={form.available_margin} onChange={(v) => set("available_margin", v)} /></Field>

        <div className="flex items-center justify-between pt-1">
          <span className="text-[11px] text-muted">Live-validated as you type</span>
          <button
            onClick={() => {
              if (!result?.is_valid) { toast.push("❌ Order fails plumbing validation — fix the errors first.", "error"); return; }
              if (mode === "live" && !confirm(`LIVE ORDER\n${form.transaction_type} ${form.quantity} ${form.symbol} @ ₹${form.price}\n\nPlace now?`)) return;
              place.mutate();
            }}
            disabled={place.isPending || !result?.is_valid}
            className="rounded-xl bg-gradient-to-b from-gold to-gold-dim px-6 py-2.5 text-xs font-bold text-ink shadow-lg hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
          >
            ▶ Execute Order ({mode.toUpperCase()})
          </button>
        </div>
      </div>

      {/* Diagnostics + cost breakdown */}
      <div className="panel space-y-3 rounded-lg p-6">
        <div className="flex items-center justify-between border-b border-line pb-3">
          <h2 className="flex items-center gap-2 text-base font-bold text-ink">🩺 7-Point Plumbing Diagnostics</h2>
          {result && (
            <span className={`rounded px-2.5 py-0.5 text-xs font-bold ${result.is_valid ? "bg-signalgreen/15 text-signalgreen" : "bg-signalred/15 text-signalred"}`}>
              {result.is_valid ? "PASSED" : "FAILED"}
            </span>
          )}
        </div>

        <div className="space-y-2 text-xs">
          {result?.diagnostics.map((d, i) => <DiagRow key={i} name={d.check_name} status={d.status} message={d.message} />)}
        </div>

        {result?.cost_breakdown && (
          <div className="space-y-2 rounded-xl border border-line bg-raised/50 p-4 text-xs">
            <h3 className="flex items-center justify-between font-bold text-ink/80">
              <span>🧮 Indian Tax &amp; Friction Auditor</span>
              <span className="font-mono text-gold">{inr(result.cost_breakdown.total_friction)}</span>
            </h3>
            <div className="grid grid-cols-3 gap-2 pt-1 font-mono text-muted">
              <div>Brokerage: <span className="text-ink">₹{result.cost_breakdown.brokerage}</span></div>
              <div>STT: <span className="text-ink">₹{result.cost_breakdown.stt}</span></div>
              <div>Stamp: <span className="text-ink">₹{result.cost_breakdown.stamp_duty}</span></div>
              <div>Exchange: <span className="text-ink">₹{result.cost_breakdown.exchange_charges}</span></div>
              <div>GST: <span className="text-ink">₹{result.cost_breakdown.gst}</span></div>
              <div>Break-even: <span className="text-signalgreen">+{result.cost_breakdown.break_even_points} pts</span></div>
            </div>
          </div>
        )}
      </div>
    </>
  );
}

const DIAG_STYLE: Record<DiagStatus, { dot: string; badge: string; icon: string }> = {
  PASSED: { dot: "bg-signalgreen", badge: "bg-signalgreen/15 text-signalgreen", icon: "✓" },
  WARNING: { dot: "bg-gold", badge: "bg-gold/15 text-gold", icon: "!" },
  FAILED: { dot: "bg-signalred", badge: "bg-signalred/15 text-signalred", icon: "✕" },
};

function DiagRow({ name, status, message }: { name: string; status: DiagStatus; message: string }) {
  const st = DIAG_STYLE[status];
  return (
    <div className="flex items-start justify-between rounded-lg border border-line bg-raised/40 p-3">
      <div className="flex items-start gap-2">
        <span className={`mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded-full text-[9px] font-bold text-bg ${st.dot}`}>{st.icon}</span>
        <div>
          <div className="font-bold text-ink">{name}</div>
          <div className="text-[11px] text-muted">{message}</div>
        </div>
      </div>
      <span className={`rounded px-2 py-0.5 font-mono text-[10px] ${st.badge}`}>{status}</span>
    </div>
  );
}

/* ---------------- small form primitives ---------------- */

const inputCls = "mt-1 w-full rounded-lg border border-line bg-raised px-3 py-2 font-mono text-ink outline-none focus:border-gold";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <div><label className="text-xs text-muted">{label}</label>{children}</div>;
}

function NumInput({ value, onChange, step }: { value: number; onChange: (n: number) => void; step?: number }) {
  return <input type="number" step={step} value={value} onChange={(e) => onChange(parseFloat(e.target.value) || 0)} className={inputCls} />;
}

function Select({ value, onChange, options }: { value: string; onChange: (v: string) => void; options: [string, string][] }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} className={inputCls}>
      {options.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
    </select>
  );
}
