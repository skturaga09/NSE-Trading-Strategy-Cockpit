import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import type { AttributionResponse, ExpectancyStat, JournalTrade } from "../types";

const inr = (n: number) => `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
const signed = (n: number) => `${n >= 0 ? "+" : ""}${inr(n)}`;
const r2 = (n: number | null | undefined) =>
  n === null || n === undefined ? "—" : `${n >= 0 ? "+" : ""}${n.toFixed(2)}R`;

const posColor = (n: number | null | undefined) =>
  n === null || n === undefined ? "var(--muted)" : n > 0 ? "var(--green)" : n < 0 ? "var(--red)" : "var(--gold)";

export function Journal() {
  const attr = useQuery({
    queryKey: ["journal-attribution"],
    queryFn: api.getAttribution,
    refetchInterval: 5000,
  });
  const recent = useQuery({
    queryKey: ["journal-recent"],
    queryFn: api.getJournalRecent,
    refetchInterval: 5000,
  });

  const a = attr.data;
  const trades = recent.data?.trades ?? [];

  if (attr.isLoading) {
    return <p className="font-mono text-[11px] text-muted">Loading journal…</p>;
  }
  if (!a) {
    return <p className="font-mono text-[11px] text-red">Journal unavailable.</p>;
  }

  return (
    <div className="space-y-6">
      <HeroExpectancy a={a} />
      <SampleGate a={a} />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <AttributionTable title="By signal source" rows={a.by_source} min={a.min_sample} />
        <AttributionTable title="By conviction" rows={a.by_conviction} min={a.min_sample} />
        <AttributionTable title="By regime" rows={a.by_regime} min={a.min_sample} />
      </div>
      <EquityCurve trades={trades} />
      <RecentTrades trades={trades} />
    </div>
  );
}

/* ---------------- Hero: overall realized edge ---------------- */

function HeroExpectancy({ a }: { a: AttributionResponse }) {
  const o = a.overall;
  const n = o.trades ?? 0;
  const exp = o.expectancy_r ?? 0;
  return (
    <div className="panel space-y-4 rounded-lg p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 font-display text-base font-bold text-ink">
          🧾 Trade Journal <span className="font-mono text-[11px] font-normal text-muted">— realized edge, in R</span>
        </h2>
        <span className="font-mono text-[10px] text-muted">
          {a.open_trades} open · {n} closed · updated {a.generated_at.split(" ")[1] ?? ""}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
        <Stat label="Expectancy / trade" value={r2(exp)} color={posColor(exp)} big />
        <Stat label="Win rate" value={n ? `${o.win_rate}%` : "—"} color="var(--ink)" />
        <Stat label="Avg win" value={r2(o.avg_win_r)} color="var(--green)" />
        <Stat label="Avg loss" value={r2(o.avg_loss_r)} color="var(--red)" />
        <Stat label="Net P&L" value={n ? signed(o.net_pnl ?? 0) : "—"} color={posColor(o.net_pnl)} />
        <Stat label="Closed trades" value={String(n)} color="var(--ink)" />
      </div>
      <p className="font-mono text-[10px] leading-relaxed text-muted">
        Expectancy = avg R per trade after costs. Positive = the signal pays; win rate alone is not edge.
        MFE/MAE below track how far winners ran and losers dug — captured live per position.
      </p>
    </div>
  );
}

function Stat({ label, value, color, big }: { label: string; value: string; color: string; big?: boolean }) {
  return (
    <div className="rounded-md border border-line bg-raised/40 px-3 py-2.5">
      <div className="font-mono text-[9px] uppercase tracking-wider text-muted">{label}</div>
      <div className={`tnum font-bold ${big ? "text-xl" : "text-base"}`} style={{ color }}>{value}</div>
    </div>
  );
}

/* ---------------- Sample-size honesty gate ---------------- */

function SampleGate({ a }: { a: AttributionResponse }) {
  const n = a.overall.trades ?? 0;
  if (n >= a.min_sample) {
    return (
      <div className="rounded-md border border-signalgreen/30 bg-signalgreen/10 px-4 py-2.5 font-mono text-[11px] text-signalgreen">
        ✓ {n} closed trades — at or above the {a.min_sample}-trade floor. Attribution below is statistically usable
        (still watch each group's own sample).
      </div>
    );
  }
  const pct = Math.min(100, Math.round((n / a.min_sample) * 100));
  return (
    <div className="space-y-2 rounded-md border border-gold/30 bg-gold/10 px-4 py-3">
      <div className="flex items-center justify-between font-mono text-[11px] text-gold">
        <span>⚠ Insufficient sample — {n} / {a.min_sample} closed trades. Numbers shown, edge NOT yet claimable.</span>
        <span className="tnum">{pct}%</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-raised">
        <div className="h-full rounded-full bg-gold transition-all" style={{ width: `${pct}%` }} />
      </div>
      <p className="font-mono text-[10px] text-muted">
        Below {a.min_sample} closed trades, expectancy is dominated by noise. Keep paper-trading the signals; the
        harness withholds any "this signal has edge" verdict until the sample is real.
      </p>
    </div>
  );
}

/* ---------------- Attribution table (one grouping) ---------------- */

function AttributionTable({ title, rows, min }: { title: string; rows: ExpectancyStat[]; min: number }) {
  return (
    <div className="panel space-y-3 rounded-lg p-5">
      <h3 className="font-display text-sm font-bold text-ink">{title}</h3>
      {rows.length === 0 ? (
        <p className="font-mono text-[11px] text-muted">No closed trades yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="font-mono text-[9px] uppercase tracking-wider text-muted">
              <tr>
                <th className="py-1.5 pr-2">Group</th>
                <th className="py-1.5 px-2 text-right">n</th>
                <th className="py-1.5 px-2 text-right">Win%</th>
                <th className="py-1.5 pl-2 text-right">Exp R</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line font-mono">
              {rows.map((s) => {
                const weak = !s.sufficient;
                return (
                  <tr key={s.group} className="hover:bg-raised/40" style={{ opacity: weak ? 0.55 : 1 }}>
                    <td className="py-1.5 pr-2 text-ink/90">
                      {s.group}
                      {weak && (
                        <span className="ml-1 text-[9px] text-muted" title={`< ${min} trades — not statistically usable`}>
                          ⚠
                        </span>
                      )}
                    </td>
                    <td className="py-1.5 px-2 text-right tnum text-muted">{s.trades}</td>
                    <td className="py-1.5 px-2 text-right tnum text-muted">{s.win_rate}%</td>
                    <td className="py-1.5 pl-2 text-right tnum font-bold" style={{ color: posColor(s.expectancy_r) }}>
                      {r2(s.expectancy_r)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="font-mono text-[9px] text-muted">⚠ = below {min}-trade floor; greyed, treat as anecdote.</p>
    </div>
  );
}

/* ---------------- Equity curve (cumulative net P&L, closed trades) ---------------- */

function EquityCurve({ trades }: { trades: JournalTrade[] }) {
  const closed = useMemo(
    () =>
      trades
        .filter((t) => t.status === "CLOSED" && t.ts_exit)
        .sort((a, b) => (a.ts_exit! < b.ts_exit! ? -1 : 1)),
    [trades],
  );

  const pts = useMemo(() => {
    let cum = 0;
    return closed.map((t) => {
      cum += t.net_pnl ?? 0;
      return cum;
    });
  }, [closed]);

  return (
    <div className="panel space-y-3 rounded-lg p-6">
      <h3 className="font-display text-sm font-bold text-ink">
        📈 Equity curve <span className="font-mono text-[11px] font-normal text-muted">— cumulative net P&L, closed trades in order</span>
      </h3>
      {pts.length < 2 ? (
        <p className="font-mono text-[11px] text-muted">Need at least 2 closed trades to draw a curve ({pts.length} so far).</p>
      ) : (
        <Sparkline values={pts} />
      )}
    </div>
  );
}

function Sparkline({ values }: { values: number[] }) {
  const W = 900, H = 160, pad = 8;
  const min = Math.min(0, ...values);
  const max = Math.max(0, ...values);
  const span = max - min || 1;
  const x = (i: number) => pad + (i / (values.length - 1)) * (W - 2 * pad);
  const y = (v: number) => H - pad - ((v - min) / span) * (H - 2 * pad);
  const path = values.map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const zeroY = y(0);
  const last = values[values.length - 1];
  const up = last >= 0;
  const stroke = up ? "var(--green)" : "var(--red)";
  return (
    <div className="overflow-x-auto">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ minWidth: 320 }} preserveAspectRatio="none">
        <line x1={pad} y1={zeroY} x2={W - pad} y2={zeroY} stroke="var(--line)" strokeWidth="1" strokeDasharray="3 3" />
        <path d={`${path} L${x(values.length - 1)},${zeroY} L${x(0)},${zeroY} Z`} fill={stroke} opacity="0.08" />
        <path d={path} fill="none" stroke={stroke} strokeWidth="2" strokeLinejoin="round" />
        <circle cx={x(values.length - 1)} cy={y(last)} r="3.5" fill={stroke} />
      </svg>
      <div className="mt-1 flex justify-between font-mono text-[10px] text-muted">
        <span>{values.length} trades</span>
        <span style={{ color: posColor(last) }}>ending {signed(last)}</span>
      </div>
    </div>
  );
}

/* ---------------- Recent trades ledger ---------------- */

function RecentTrades({ trades }: { trades: JournalTrade[] }) {
  if (trades.length === 0) {
    return (
      <div className="panel rounded-lg p-6">
        <p className="font-mono text-[11px] text-muted">
          No journaled trades yet. Place from Ideas, the Breakout Radar, or the screener — each entry snapshots its
          signal features and resolves outcome over time.
        </p>
      </div>
    );
  }
  return (
    <div className="panel space-y-3 rounded-lg p-6">
      <h3 className="font-display text-sm font-bold text-ink">
        🧾 Recent trades <span className="font-mono text-[11px] font-normal text-muted">— newest first</span>
      </h3>
      <div className="overflow-x-auto rounded-md border border-line">
        <table className="w-full text-left text-xs">
          <thead className="bg-raised/50 font-mono text-[10px] uppercase tracking-wider text-muted">
            <tr>
              {["Symbol", "Source", "Conv", "Regime", "Status", "R", "MFE", "MAE", "Net P&L", "Exit"].map((h) => (
                <th key={h} className="px-3 py-2">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line font-mono">
            {trades.map((t) => {
              const open = t.status === "OPEN";
              return (
                <tr key={t.order_id} className="hover:bg-raised/40">
                  <td className="px-3 py-2 text-ink/90">{t.symbol}</td>
                  <td className="px-3 py-2 text-muted">{t.source ?? "Manual"}</td>
                  <td className="px-3 py-2 tnum text-muted">{t.conviction ?? "—"}</td>
                  <td className="px-3 py-2 text-muted">{t.regime ?? "—"}</td>
                  <td className="px-3 py-2">
                    <span className="tnum" style={{ color: open ? "var(--cyan)" : "var(--muted)" }}>
                      {open ? "OPEN" : t.outcome ?? "CLOSED"}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right tnum font-bold" style={{ color: posColor(t.r_multiple) }}>{r2(t.r_multiple)}</td>
                  <td className="px-3 py-2 text-right tnum" style={{ color: "var(--green)" }}>{r2(t.mfe_r)}</td>
                  <td className="px-3 py-2 text-right tnum" style={{ color: "var(--red)" }}>{r2(t.mae_r)}</td>
                  <td className="px-3 py-2 text-right tnum" style={{ color: posColor(t.net_pnl) }}>
                    {t.net_pnl === null || t.net_pnl === undefined ? "—" : signed(t.net_pnl)}
                  </td>
                  <td className="px-3 py-2 text-[10px] text-muted">{t.exit_reason ?? "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
