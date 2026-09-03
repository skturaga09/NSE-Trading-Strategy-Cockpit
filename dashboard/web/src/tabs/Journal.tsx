import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import type { AttributionResponse, ExpectancyStat, JournalTrade, DecisionsResponse, CostsSummary,
  SwingSignalsResponse, SwingSigAgg, SwingSignalRow } from "../types";

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
    refetchInterval: 3000,
  });
  const recent = useQuery({
    queryKey: ["journal-recent"],
    queryFn: api.getJournalRecent,
    refetchInterval: 3000,
  });
  const decisions = useQuery({
    queryKey: ["journal-decisions"],
    queryFn: api.getDecisions,
    refetchInterval: 3000,
  });
  const costs = useQuery({
    queryKey: ["journal-costs"],
    queryFn: api.getCosts,
    refetchInterval: 3000,
  });
  const swingSig = useQuery({
    queryKey: ["journal-swing-signals"],
    queryFn: api.getSwingSignals,
    refetchInterval: 30000,   // resolves prior-day signals; not real-time critical
  });
  const dailyPnl = useQuery({
    queryKey: ["journal-daily-pnl"],
    queryFn: api.getDailyPnl,
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
      <PnlHeatmap days={dailyPnl.data?.days ?? {}} />
      <SampleGate a={a} />
      <SwingSignalLearning data={swingSig.data} />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <AttributionTable title="By signal source" rows={a.by_source} min={a.min_sample} />
        <AttributionTable title="By conviction" rows={a.by_conviction} min={a.min_sample} />
        <AttributionTable title="By regime" rows={a.by_regime} min={a.min_sample} />
      </div>
      <EquityCurve trades={trades} />
      <CostsCard data={costs.data} />
      <RecentTrades trades={trades} />
      <DecisionLog data={decisions.data} />
    </div>
  );
}

/* ---------------- Intraday decision log (process quality) ---------------- */

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const CELL = 13; // px per day cell
const GAP = 3;   // px gap

type HoverCell = { x: number; y: number; date: string; v: number | undefined };

function PnlHeatmap({ days }: { days: Record<string, number> }) {
  const nowYear = new Date().getFullYear();
  const [year, setYear] = useState(nowYear);
  const [hover, setHover] = useState<HoverCell | null>(null);

  // Colour: green scale for a profit day, red for a loss, grey when no trade closed.
  const cellColor = (v: number | undefined): string => {
    if (v === undefined || v === 0) return "var(--bg-3, rgba(255,255,255,0.05))";
    const a = Math.abs(v);
    const t = a < 2500 ? 0.3 : a < 7500 ? 0.55 : a < 15000 ? 0.78 : 1;
    return v >= 0 ? `rgba(88,214,141,${t})` : `rgba(255,93,93,${t})`;
  };

  const key2 = (m: number, day: number) => `${year}-${String(m + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
  const niceDate = (k: string) => {
    const [y, m, d] = k.split("-").map(Number);
    return `${d} ${MONTHS[m - 1]} ${y}`;
  };

  // Year summary.
  let total = 0, greens = 0, reds = 0, tradeDays = 0;
  for (const [k, v] of Object.entries(days)) {
    if (k.startsWith(`${year}-`)) { total += v; tradeDays++; if (v > 0) greens++; else if (v < 0) reds++; }
  }

  // One mini-grid per month → natural gaps between months.
  const months = MONTHS.map((label, m) => {
    const offset = new Date(year, m, 1).getDay();          // weekday of the 1st
    const dim = new Date(year, m + 1, 0).getDate();         // days in month
    return { label, m, offset, dim, cols: Math.ceil((offset + dim) / 7) };
  });
  const rows = [0, 1, 2, 3, 4, 5, 6];

  return (
    <div className="panel space-y-3 rounded-lg p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 font-display text-base font-bold text-ink">
          🎯 P&amp;L Calendar
          <span className="font-mono text-[11px] font-normal text-muted">— each day shaded by net realised P&amp;L</span>
        </h2>
        <div className="flex items-center gap-3">
          <button onClick={() => setYear((y) => y - 1)}
            className="rounded border border-line px-2 py-0.5 font-mono text-sm text-muted hover:bg-raised hover:text-ink">◀</button>
          <span className="tnum font-display text-lg font-bold text-ink">{year}</span>
          <button onClick={() => setYear((y) => Math.min(nowYear, y + 1))} disabled={year >= nowYear}
            className="rounded border border-line px-2 py-0.5 font-mono text-sm text-muted hover:bg-raised hover:text-ink disabled:opacity-30">▶</button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-4 font-mono text-[10px] text-muted">
        <span>Year net <span className="tnum font-bold" style={{ color: total > 0 ? "var(--green)" : total < 0 ? "var(--red)" : "var(--ink)" }}>{signed(total)}</span></span>
        <span>🟢 {greens} up</span>
        <span>🔴 {reds} down</span>
        <span>{tradeDays} trading day{tradeDays === 1 ? "" : "s"}</span>
      </div>

      <div className="overflow-x-auto pb-1">
        {/* month blocks with a gap between each */}
        <div className="flex" style={{ gap: 14 }}>
          {months.map((mo) => (
            <div key={mo.m} className="flex flex-col" style={{ gap: 4 }}>
              <span className="font-mono text-[9px] uppercase tracking-wider text-muted">{mo.label}</span>
              <div className="flex" style={{ gap: GAP }}>
                {Array.from({ length: mo.cols }, (_, col) => (
                  <div key={col} className="flex flex-col" style={{ gap: GAP }}>
                    {rows.map((row) => {
                      const dayNum = col * 7 + row - mo.offset + 1; // 1-based day of month
                      if (dayNum < 1 || dayNum > mo.dim) {
                        return <div key={row} style={{ width: CELL, height: CELL }} />;
                      }
                      const k = key2(mo.m, dayNum);
                      const v = days[k];
                      return (
                        <div key={row}
                          onMouseEnter={(e) => setHover({ x: e.clientX, y: e.clientY, date: k, v })}
                          onMouseMove={(e) => setHover({ x: e.clientX, y: e.clientY, date: k, v })}
                          onMouseLeave={() => setHover(null)}
                          style={{ width: CELL, height: CELL, borderRadius: 3, background: cellColor(v), cursor: "pointer" }} />
                      );
                    })}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="flex items-center gap-1.5 font-mono text-[9px] text-muted">
        <span>Loss</span>
        {[-16000, -8000, -3000].map((v) => <span key={v} style={{ width: CELL, height: CELL, borderRadius: 3, background: cellColor(v) }} />)}
        <span style={{ width: CELL, height: CELL, borderRadius: 3, background: cellColor(undefined) }} />
        {[3000, 8000, 16000].map((v) => <span key={v} style={{ width: CELL, height: CELL, borderRadius: 3, background: cellColor(v) }} />)}
        <span>Profit</span>
      </div>

      {hover && (
        <div className="pointer-events-none fixed z-50 rounded-md border border-line px-2.5 py-1.5 font-mono text-[11px] shadow-lg"
          style={{ left: hover.x + 14, top: hover.y + 14, background: "var(--bg-2, #14140f)" }}>
          <div className="text-muted">{niceDate(hover.date)}</div>
          {hover.v === undefined ? (
            <div className="text-muted">No trades</div>
          ) : (
            <div className="tnum font-bold" style={{ color: hover.v > 0 ? "var(--green)" : hover.v < 0 ? "var(--red)" : "var(--ink)" }}>
              {signed(hover.v)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function SwingSignalLearning({ data }: { data: SwingSignalsResponse | undefined }) {
  if (!data) return null;
  const s = data.stats;
  const o = s.overall;
  const pct = (v: number | null) => (v === null ? "—" : `${v}%`);
  const rr = (v: number | null) => (v === null ? "—" : `${v >= 0 ? "+" : ""}${v}%`);

  const AggCard = ({ label, agg }: { label: string; agg: SwingSigAgg }) => {
    const edge = agg.hit_rate !== null ? agg.hit_rate - s.coinflip : 0;
    const color = !agg.sufficient ? "var(--muted)" : edge > 5 ? "var(--green)" : edge < -5 ? "var(--red)" : "var(--gold)";
    return (
      <div className="rounded-md border border-line bg-raised/40 p-3">
        <div className="font-mono text-[9px] uppercase tracking-wider text-muted">{label}</div>
        <div className="tnum text-lg font-bold" style={{ color }}>{agg.n > 0 ? pct(agg.hit_rate) : "—"}</div>
        <div className="font-mono text-[9px] text-muted">
          n={agg.n}{agg.n > 0 ? ` · gap ${rr(agg.avg_gap)} · run ${rr(agg.avg_mfe)}` : ""}{agg.n > 0 && !agg.sufficient ? " · thin" : ""}
        </div>
      </div>
    );
  };

  return (
    <div className="panel space-y-3 rounded-lg p-5">
      <h2 className="flex items-center gap-2 font-display text-base font-bold text-ink">
        🌙 Overnight OI signal — learning
        <span className="font-mono text-[11px] font-normal text-muted">— does the buildup actually gap your way next day?</span>
      </h2>

      {!o.sufficient ? (
        <div className="rounded-md border border-cyan/25 bg-cyan/[0.06] px-3 py-2 font-mono text-[10px] leading-relaxed text-cyan">
          📊 Accumulating evidence — <span className="font-bold">{o.n}/{s.min_sample}</span> resolved signals. No verdict until ≥{s.min_sample},
          so a few lucky or unlucky days can't fake an edge.{s.open_pending > 0 ? ` ${s.open_pending} signal(s) awaiting next-day resolution.` : ""}
        </div>
      ) : (
        <div className="font-mono text-[10px] text-muted">
          {o.n} resolved · overall <span className="font-bold text-ink">{pct(o.hit_rate)}</span> gapped in your favour vs {s.coinflip}% coin-flip · {s.open_pending} pending
        </div>
      )}

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        <AggCard label="Overall hit-rate" agg={o} />
        {s.ignition && <AggCard label="🔥 Ignition" agg={s.ignition} />}
        <AggCard label="Strong (≥20%)" agg={s.by_tier.strong} />
        <AggCard label="Notable (10–20%)" agg={s.by_tier.notable} />
        <AggCard label="Building (<10%)" agg={s.by_tier.building} />
        <AggCard label="Long buildup" agg={s.by_bias.LONG} />
        <AggCard label="Short buildup" agg={s.by_bias.SHORT} />
      </div>

      {data.recent.length > 0 && (
        <div className="overflow-x-auto rounded-md border border-line">
          <table className="w-full text-left text-[11px]">
            <thead className="bg-raised/50 font-mono text-[9px] uppercase tracking-wider text-muted">
              <tr>
                <th className="px-2 py-1.5">Date</th><th className="px-2 py-1.5">Symbol</th><th className="px-2 py-1.5">Side</th>
                <th className="px-2 py-1.5 text-right">OI Δ</th><th className="px-2 py-1.5">Tier</th>
                <th className="px-2 py-1.5 text-right">Gap</th><th className="px-2 py-1.5 text-right">Next-day run</th>
                <th className="px-2 py-1.5 text-center">Result</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line font-mono">
              {data.recent.map((r) => <SigRow key={`${r.signal_date}-${r.symbol}-${r.bias}`} r={r} />)}
            </tbody>
          </table>
        </div>
      )}

      <p className="font-mono text-[9px] leading-relaxed text-muted">
        Tracks <span className="text-ink/80">every</span> surfaced candidate (traded or not) and resolves it on the next settled session — so it measures the
        signal's edge, not just your fills. "Hit-rate" = % that <span className="text-ink/80">gapped in the signalled direction</span>; "run" = the best move it
        offered next day. Sample-size gated (≥{s.min_sample}), and it <span className="text-gold">measures only</span> — it will not auto-change the ≥10% threshold;
        tightening the bar stays your call once the data is clear.
      </p>
    </div>
  );
}

function SigRow({ r }: { r: SwingSignalRow }) {
  const rr = (v: number | null) => (v === null ? "—" : `${v >= 0 ? "+" : ""}${v}%`);
  const resolved = r.status === "RESOLVED";
  return (
    <tr>
      <td className="px-2 py-1.5 text-muted">{r.signal_date}</td>
      <td className="px-2 py-1.5 font-bold text-ink">{r.symbol}</td>
      <td className="px-2 py-1.5" style={{ color: r.bias === "LONG" ? "var(--green)" : "var(--red)" }}>{r.bias}</td>
      <td className="px-2 py-1.5 text-right tnum">{r.oi_chg_pct !== null ? `${r.oi_chg_pct >= 0 ? "+" : ""}${r.oi_chg_pct}%` : "—"}</td>
      <td className="px-2 py-1.5 text-[9px] uppercase text-muted">{r.tier ?? "—"}</td>
      <td className="px-2 py-1.5 text-right tnum" style={{ color: r.gap_pct === null ? "var(--muted)" : r.gap_pct >= 0 ? "var(--green)" : "var(--red)" }}>{resolved ? rr(r.gap_pct) : "—"}</td>
      <td className="px-2 py-1.5 text-right tnum" style={{ color: r.mfe_pct === null ? "var(--muted)" : "var(--green)" }}>{resolved ? rr(r.mfe_pct) : "—"}</td>
      <td className="px-2 py-1.5 text-center">
        {!resolved ? <span className="text-[9px] text-gold">pending</span>
          : r.worked ? <span className="font-bold text-signalgreen">✓</span> : <span className="font-bold text-signalred">✗</span>}
      </td>
    </tr>
  );
}

function DecisionLog({ data }: { data: DecisionsResponse | undefined }) {
  if (!data || data.summary.total === 0) {
    return (
      <div className="panel rounded-lg p-6">
        <h3 className="font-display text-sm font-bold text-ink">
          🛈 Intraday Decision Log <span className="font-mono text-[11px] font-normal text-muted">— from the Intraday tab</span>
        </h3>
        <p className="mt-2 font-mono text-[11px] text-muted">
          No decisions logged yet. Run an assessment on the Intraday tab and hit "Log decision to Journal" — every
          NO-TRADE and WAIT counts as process quality, not just executed trades.
        </p>
      </div>
    );
  }
  const s = data.summary;
  const V_COLOR: Record<string, string> = {
    CANDIDATE: "var(--green)", WAIT: "var(--gold)", NO_TRADE: "var(--red)",
    INSUFFICIENT_DATA: "var(--red)", STOP_DAY: "var(--red)",
  };
  return (
    <div className="panel space-y-3 rounded-lg p-6">
      <h3 className="font-display text-sm font-bold text-ink">
        🛈 Intraday Decision Log <span className="font-mono text-[11px] font-normal text-muted">— discipline scorecard</span>
      </h3>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <MiniStat k="Decisions logged" v={String(s.total)} />
        <MiniStat k="Trade candidates" v={String(s.candidates)} color="var(--green)" />
        <MiniStat k="Rejected (disciplined)" v={String(s.rejected)} color="var(--gold)" />
        <MiniStat k="Rejection rate" v={s.rejection_rate === null ? "—" : `${s.rejection_rate}%`} color="var(--cyan)" />
      </div>
      <div className="overflow-x-auto rounded-md border border-line">
        <table className="w-full text-left text-xs">
          <thead className="bg-raised/50 font-mono text-[10px] uppercase tracking-wider text-muted">
            <tr>{["Time", "Underlying", "Regime", "Setup", "Verdict", "Gates failed", "Risk ₹"].map((h) => <th key={h} className="px-3 py-2">{h}</th>)}</tr>
          </thead>
          <tbody className="divide-y divide-line font-mono">
            {data.decisions.map((d) => (
              <tr key={d.id} className="hover:bg-raised/40">
                <td className="px-3 py-2 text-[10px] text-muted">{d.ts}</td>
                <td className="px-3 py-2 text-ink/90">{d.underlying ?? "—"}</td>
                <td className="px-3 py-2 text-muted">{d.regime ?? "—"}</td>
                <td className="px-3 py-2 text-muted">{d.setup ?? "—"}{d.direction ? ` ${d.direction}` : ""}</td>
                <td className="px-3 py-2 font-bold" style={{ color: V_COLOR[d.verdict ?? ""] ?? "var(--muted)" }}>{d.decision ?? d.verdict}</td>
                <td className="px-3 py-2 text-[10px] text-muted">{d.gates_failed ?? "—"}</td>
                <td className="px-3 py-2 text-right tnum text-muted">{d.planned_risk ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CostsCard({ data }: { data: CostsSummary | undefined }) {
  if (!data || data.trades === 0) {
    return (
      <div className="panel rounded-lg p-6">
        <h3 className="font-display text-sm font-bold text-ink">
          🧾 Charges paid <span className="font-mono text-[11px] font-normal text-muted">— estimated, across closed trades</span>
        </h3>
        <p className="mt-2 font-mono text-[11px] text-muted">
          No closed journaled trades yet. Import your Kite trades (Journal → Import) or place through the dashboard, then this shows
          estimated Zerodha charges. Exact figures live in Kite Console → Reports → Charges.
        </p>
      </div>
    );
  }
  const b = data.breakdown;
  const cell = (k: string, v: number) => (
    <div className="rounded-md border border-line bg-raised/40 px-3 py-2">
      <div className="font-mono text-[9px] uppercase tracking-wider text-muted">{k}</div>
      <div className="tnum text-sm font-bold text-ink">{inr(v)}</div>
    </div>
  );
  return (
    <div className="panel space-y-3 rounded-lg p-6">
      <h3 className="font-display text-sm font-bold text-ink">
        🧾 Charges paid to Zerodha <span className="font-mono text-[11px] font-normal text-gold">— ESTIMATED (not from Kite API)</span>
      </h3>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-4">
        <div className="rounded-md border border-line bg-raised/40 px-3 py-2">
          <div className="font-mono text-[9px] uppercase tracking-wider text-muted">Total charges ({data.trades} trades)</div>
          <div className="tnum text-2xl font-bold text-red" style={{ color: "var(--red)" }}>{inr(data.total)}</div>
        </div>
        <div className="rounded-md border border-line bg-raised/40 px-3 py-2">
          <div className="font-mono text-[9px] uppercase tracking-wider text-muted">Gross P&L</div>
          <div className="tnum text-lg font-bold" style={{ color: posColor(data.gross_pnl) }}>{signed(data.gross_pnl)}</div>
        </div>
        <div className="rounded-md border border-line bg-raised/40 px-3 py-2">
          <div className="font-mono text-[9px] uppercase tracking-wider text-muted">Net after charges</div>
          <div className="tnum text-lg font-bold" style={{ color: posColor(data.net_after_costs) }}>{signed(data.net_after_costs)}</div>
        </div>
        <div className="rounded-md border border-line bg-raised/40 px-3 py-2">
          <div className="font-mono text-[9px] uppercase tracking-wider text-muted">Charges as % of gross</div>
          <div className="tnum text-lg font-bold text-gold">{data.gross_pnl ? ((data.total / Math.abs(data.gross_pnl)) * 100).toFixed(1) + "%" : "—"}</div>
        </div>
      </div>
      <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
        {cell("Brokerage", b.brokerage)}{cell("STT", b.stt)}{cell("Exchange", b.exchange)}
        {cell("GST", b.gst)}{cell("Stamp", b.stamp)}{cell("SEBI", b.sebi)}
      </div>
      <p className="font-mono text-[9px] leading-relaxed text-muted">
        ⚠ <span className="text-gold">Estimated</span> using India charge rates (STT, exchange txn, SEBI, stamp, 18% GST, ₹20 flat brokerage) on your
        entry/exit/qty — Kite's API does not expose charges. Your actual bill can differ (brokerage plan, DP charges, rounding). Exact figures:
        Kite Console → Reports → Charges / Tradewise P&L.
      </p>
    </div>
  );
}

function MiniStat({ k, v, color }: { k: string; v: string; color?: string }) {
  return (
    <div className="rounded-md border border-line bg-raised/40 px-3 py-2">
      <div className="font-mono text-[9px] uppercase tracking-wider text-muted">{k}</div>
      <div className="tnum text-base font-bold" style={{ color: color ?? "var(--ink)" }}>{v}</div>
    </div>
  );
}

/* ---------------- Hero: overall realized edge ---------------- */

function HeroExpectancy({ a }: { a: AttributionResponse }) {
  const o = a.overall;
  const n = o.trades ?? 0;
  const exp = o.expectancy_r ?? null;
  const qc = useQueryClient();
  const [importing, setImporting] = useState(false);
  const [importMsg, setImportMsg] = useState<string | null>(null);

  const importKite = async () => {
    setImporting(true);
    setImportMsg("Pulling live trades from Zerodha…");
    try {
      const r = await api.importKiteTrades();
      setImportMsg((r.success ? "✅ " : "⚠ ") + r.message);
      if (r.success) {
        qc.invalidateQueries({ queryKey: ["journal-attribution"] });
        qc.invalidateQueries({ queryKey: ["journal-recent"] });
      }
    } catch (e) {
      setImportMsg("⚠ " + (e instanceof Error ? e.message : "import failed"));
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="panel space-y-4 rounded-lg p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 font-display text-base font-bold text-ink">
          🧾 Trade Journal <span className="font-mono text-[11px] font-normal text-muted">— realized edge, in R</span>
        </h2>
        <div className="flex items-center gap-3">
          <span className="font-mono text-[10px] text-muted">
            {a.open_trades} open · {n} closed · updated {a.generated_at.split(" ")[1] ?? ""}
          </span>
          <button
            onClick={importKite}
            disabled={importing}
            title="Pull today's real F&O/intraday trades from your Zerodha account into the journal"
            className="rounded-md border border-cyan/40 bg-cyan/10 px-3 py-1.5 font-mono text-[11px] font-bold text-cyan hover:bg-cyan/20 disabled:opacity-50"
          >
            {importing ? "⏳ Importing…" : "⟳ Import Kite trades"}
          </button>
        </div>
      </div>
      {importMsg && (
        <div className="rounded-md border border-line bg-raised/40 px-3 py-2 font-mono text-[11px] text-muted">
          {importMsg}
          <span className="ml-2 text-[10px] text-muted/70">
            (Kite only keeps the current day's trades — import same-day, before the session rolls.)
          </span>
        </div>
      )}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
        <Stat label="Expectancy / trade" value={exp === null ? "—" : r2(exp)} color={posColor(exp)} big />
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
