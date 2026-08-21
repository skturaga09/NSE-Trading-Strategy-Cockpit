import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "../api";
import type { BacktestForm } from "../types";

const DEFAULT: BacktestForm = {
  total_trades: 150, win_rate: 52, avg_win_pct: 2.4, avg_loss_pct: 1.3,
  max_drawdown_pct: 14, years_tested: 5, num_parameters: 4, avg_trade_value: 50000,
  trade_type: "delivery", brokerage_per_trade: 20, slippage_tested: true, include_india_costs: true,
};

function verdictColor(pct: number): string {
  if (pct >= 80) return "var(--green)";
  if (pct >= 60) return "var(--gold)";
  if (pct >= 40) return "#f59e42";
  return "var(--red)";
}
function barColor(ratio: number): string {
  if (ratio >= 0.85) return "var(--green)";
  if (ratio >= 0.65) return "var(--cyan)";
  if (ratio >= 0.45) return "var(--gold)";
  return "var(--red)";
}
const sevColor: Record<string, string> = { critical: "var(--red)", warning: "var(--gold)", info: "var(--cyan)" };

export function Backtest() {
  const [form, setForm] = useState<BacktestForm>(DEFAULT);
  const set = <K extends keyof BacktestForm>(k: K, v: BacktestForm[K]) => setForm((f) => ({ ...f, [k]: v }));
  const evalM = useMutation({ mutationFn: () => api.backtestEvaluate(form) });
  const d = evalM.data;
  const pct = d?.percentage ?? 0;

  return (
    <div className="panel space-y-5 rounded-lg p-6">
      <div className="flex items-center justify-between border-b border-line pb-4">
        <h2 className="font-display text-lg font-bold text-ink">Strategy Backtest · Cost Friction</h2>
        <div className="flex gap-2 font-mono text-xs">
          <button onClick={() => setForm(DEFAULT)} className="rounded-md border border-line bg-raised px-3 py-2 text-muted hover:text-ink">Reset</button>
          <button onClick={() => evalM.mutate()} disabled={evalM.isPending}
            className="rounded-md border border-gold/40 bg-gold/10 px-4 py-2 font-bold uppercase tracking-wider text-gold hover:bg-gold/20 disabled:opacity-50">
            {evalM.isPending ? "⟳" : "⚡ evaluate"}
          </button>
        </div>
      </div>

      {/* Inputs */}
      <div className="grid grid-cols-2 gap-3 font-mono text-xs md:grid-cols-4">
        <N label="Total trades" v={form.total_trades} on={(x) => set("total_trades", x)} />
        <N label="Win rate %" v={form.win_rate} on={(x) => set("win_rate", x)} step={0.5} />
        <N label="Avg win %" v={form.avg_win_pct} on={(x) => set("avg_win_pct", x)} step={0.1} />
        <N label="Avg loss %" v={form.avg_loss_pct} on={(x) => set("avg_loss_pct", x)} step={0.1} />
        <N label="Max DD %" v={form.max_drawdown_pct} on={(x) => set("max_drawdown_pct", x)} step={0.5} />
        <N label="Years" v={form.years_tested} on={(x) => set("years_tested", x)} step={0.5} />
        <N label="# params" v={form.num_parameters} on={(x) => set("num_parameters", x)} />
        <N label="Trade value ₹" v={form.avg_trade_value} on={(x) => set("avg_trade_value", x)} step={1000} />
        <div>
          <label className="uppercase tracking-wider text-muted">Trade type</label>
          <select value={form.trade_type} onChange={(e) => set("trade_type", e.target.value)}
            className="mt-1 w-full rounded-md border border-line bg-raised px-2 py-2 text-ink outline-none focus:border-gold">
            {["delivery", "intraday", "fno_options", "fno_futures"].map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        <N label="Brokerage ₹" v={form.brokerage_per_trade} on={(x) => set("brokerage_per_trade", x)} />
        <Chk label="Slippage modeled" v={form.slippage_tested} on={(x) => set("slippage_tested", x)} />
        <Chk label="India costs" v={form.include_india_costs} on={(x) => set("include_india_costs", x)} />
      </div>

      {d && d.total_score != null && (
        <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
          <div className="rounded-lg border border-line bg-raised/40 p-5 text-center">
            <div className="font-mono text-[10px] uppercase tracking-widest text-muted">robustness</div>
            <div className="font-mono text-4xl font-bold tnum" style={{ color: verdictColor(pct) }}>{d.total_score}<span className="text-lg text-muted">/{d.max_possible}</span></div>
            <span className="mt-1 inline-block rounded px-2 py-0.5 font-mono text-[11px] font-bold uppercase" style={{ background: `color-mix(in srgb, ${verdictColor(pct)} 15%, transparent)`, color: verdictColor(pct) }}>{d.verdict}</span>
            <p className="mt-2 text-[11px] leading-relaxed text-muted">{d.verdict_detail}</p>
            <p className="mt-1 font-mono text-[11px] text-muted">adj. E {d.adjusted_expectancy_pct >= 0 ? "+" : ""}{d.adjusted_expectancy_pct}% / trade</p>
          </div>

          <div className="space-y-2 md:col-span-2">
            <h3 className="font-mono text-xs font-bold uppercase tracking-wider text-ink/80">5-dimension breakdown</h3>
            {d.dimensions.map((dim) => {
              const ratio = dim.max_score ? dim.score / dim.max_score : 0;
              return (
                <div key={dim.name}>
                  <div className="flex justify-between font-mono text-[11px]"><span className="text-ink/80">{dim.name}</span><span className="tnum text-muted">{dim.score}/{dim.max_score}</span></div>
                  <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-raised">
                    <div className="h-full rounded-full transition-all" style={{ width: `${ratio * 100}%`, background: barColor(ratio) }} />
                  </div>
                  <div className="mt-0.5 font-mono text-[9px] text-muted">{dim.details}</div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {d && d.red_flags?.length > 0 && (
        <div className="space-y-2 rounded-lg border border-line bg-raised/40 p-4">
          <h3 className="font-mono text-xs font-bold uppercase tracking-wider text-gold">⚠ Red flags</h3>
          {d.red_flags.map((f, i) => (
            <div key={i} className="border-l-2 pl-3" style={{ borderColor: sevColor[f.severity] }}>
              <div className="flex items-center gap-2">
                <span className="rounded px-1.5 py-0.5 text-[9px] font-bold uppercase" style={{ background: `color-mix(in srgb, ${sevColor[f.severity]} 15%, transparent)`, color: sevColor[f.severity] }}>{f.severity}</span>
                <span className="text-[11px] text-ink/80">{f.message}</span>
              </div>
              <div className="mt-0.5 font-mono text-[10px] text-muted">→ {f.recommendation}</div>
            </div>
          ))}
        </div>
      )}

      {!d && <p className="font-mono text-[11px] text-muted">Enter your strategy stats and hit Evaluate.</p>}
    </div>
  );
}

function N({ label, v, on, step }: { label: string; v: number; on: (n: number) => void; step?: number }) {
  return (
    <div>
      <label className="uppercase tracking-wider text-muted">{label}</label>
      <input type="number" step={step} value={v} onChange={(e) => on(parseFloat(e.target.value) || 0)}
        className="mt-1 w-full rounded-md border border-line bg-raised px-2 py-2 text-ink outline-none focus:border-gold" />
    </div>
  );
}
function Chk({ label, v, on }: { label: string; v: boolean; on: (b: boolean) => void }) {
  return (
    <label className="flex cursor-pointer items-center gap-2 pt-5 text-muted">
      <input type="checkbox" checked={v} onChange={(e) => on(e.target.checked)} className="h-4 w-4 accent-[color:var(--gold)]" />
      {label}
    </label>
  );
}
