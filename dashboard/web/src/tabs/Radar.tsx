import { useEffect, useState } from "react";
import { api } from "../api";
import type { IgniteScan, IgniteRow, IgniteCompare } from "../types";

/* =============================================================================
   INTRADAY IGNITION RADAR — early-entry lane (separate from the EOD swing board).
   Catches names STARTING to move on volume (leading footprint: volume pace + price
   breakout + VWAP side) so you enter near the start instead of chasing at EOD.
   Earlier = noisier; a heads-up screen, NOT advice. Logged for early-vs-EOD study.
============================================================================= */

export function Radar() {
  const [scan, setScan] = useState<IgniteScan | null>(null);
  const [cmp, setCmp] = useState<IgniteCompare | null>(null);
  const [loading, setLoading] = useState(false);

  const run = async () => {
    setLoading(true);
    try { setScan(await api.getIgnite()); } catch { setScan(null); } finally { setLoading(false); }
  };
  useEffect(() => {
    void run();
    const id = setInterval(() => { api.getIgnite().then(setScan).catch(() => {}); }, 15000);
    const idc = setInterval(() => { api.getIgniteCompare().then(setCmp).catch(() => {}); }, 30000);
    api.getIgniteCompare().then(setCmp).catch(() => {});
    return () => { clearInterval(id); clearInterval(idc); };
    /* eslint-disable-next-line */
  }, []);

  return (
    <div className="space-y-4">
      <div className="rounded-md border border-gold/25 bg-gold/[0.05] px-4 py-2.5 font-mono text-[10px] leading-relaxed text-muted">
        ⚡ INTRADAY IGNITION RADAR — surfaces names <span className="text-ink/80">starting to move on volume</span> during the session, so you can
        consider entering <span className="text-gold">early</span> instead of chasing at EOD. Trigger = volume pace + price move + VWAP side (intraday OI is
        provisional, so it's not used). <span className="text-signalred">Earlier = noisier</span> — more false starts; a heads-up screen, NOT advice. Every fire is
        logged to compare early-vs-EOD entries before you trust it.
      </div>

      <div className="panel space-y-3 rounded-lg p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="flex items-center gap-2 font-display text-base font-bold text-ink">
            ⚡ Igniting now <span className="font-mono text-[11px] font-normal text-muted">— live early movers (auto-refresh 15s)</span>
          </h2>
          <button onClick={run} disabled={loading}
            className="rounded-md border border-cyan/50 bg-cyan/15 px-4 py-2 font-mono text-xs font-bold text-cyan hover:bg-cyan/25 disabled:opacity-50">
            {loading ? "⏳ Scanning…" : "⟳ Rescan"}
          </button>
        </div>

        {!scan ? (
          <p className="font-mono text-[11px] text-muted">Scanning the F&amp;O universe…</p>
        ) : !scan.market_open ? (
          <p className="font-mono text-[11px] text-gold">
            ⚠ Market closed — the radar runs live during the session (09:15–15:30 IST). Idle until the next open ({scan.universe} F&amp;O names in scope).
          </p>
        ) : !scan.is_live ? (
          <p className="font-mono text-[11px] text-gold">⚠ Unavailable — {scan.source}. Connect Kite (System Check).</p>
        ) : (
          <>
            <div className="font-mono text-[10px] text-muted">● {scan.source} · {scan.scanned}/{scan.universe} scanned · {scan.timestamp}</div>
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <Col title="▲ Igniting UP (CALL / CE side)" color="var(--green)" rows={scan.longs} />
              <Col title="▼ Igniting DOWN (PUT / PE side)" color="var(--red)" rows={scan.shorts} />
            </div>
            <p className="font-mono text-[9px] leading-relaxed text-muted">
              Score 0–100 fuses <span className="text-ink/80">volume pace</span> (today's volume vs its time-of-day norm — the leading signal),
              % move, closing near the day's extreme, and VWAP side. A gap-open fires immediately (move already in — limited entry edge); the real value is a
              name that <span className="text-ink/80">develops</span> a move intraday. Confirm the level and your rules — earlier means more false starts.
            </p>
          </>
        )}
      </div>

      <EarlyVsEod cmp={cmp} />
    </div>
  );
}

function EarlyVsEod({ cmp }: { cmp: IgniteCompare | null }) {
  const s = cmp?.summary;
  const enough = !!s && s.resolved_count >= s.min_sample;
  const pct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}${v}%`);
  return (
    <div className="panel space-y-3 rounded-lg p-5">
      <h2 className="flex items-center gap-2 font-display text-base font-bold text-ink">
        📏 Early vs EOD <span className="font-mono text-[11px] font-normal text-muted">— did catching it on the radar beat waiting for the close?</span>
      </h2>
      {!s || s.overlap_count === 0 ? (
        <div className="rounded-md border border-cyan/25 bg-cyan/[0.06] px-3 py-2 font-mono text-[10px] leading-relaxed text-cyan">
          📊 Accumulating — {s?.total_fires_logged ?? 0} radar fires logged so far. This fills in once names caught intraday also appear on the EOD board
          (and resolves the day after). No verdict until ≥{s?.min_sample ?? 20} resolved pairs — so it can't lie from a lucky day.
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Stat k="Overlap names" v={String(s.overlap_count)} />
            <Stat k="Avg entry advantage" v={pct(s.avg_entry_advantage_pct)} color={(s.avg_entry_advantage_pct ?? 0) > 0 ? "var(--green)" : "var(--muted)"} />
            <Stat k="Resolved pairs" v={`${s.resolved_count}/${s.min_sample}`} />
            <Stat k="Early edge (next-day)" v={enough ? pct(s.avg_early_edge_pct) : "—"} color={!enough ? "var(--muted)" : (s.avg_early_edge_pct ?? 0) > 0 ? "var(--green)" : "var(--red)"} />
          </div>
          {!enough && (
            <div className="font-mono text-[9px] text-gold">Accumulating: {s.resolved_count}/{s.min_sample} resolved — entry-advantage shown, but no next-day-edge verdict yet.</div>
          )}
          {cmp!.pairs.length > 0 && (
            <div className="overflow-x-auto rounded-md border border-line">
              <table className="w-full text-left text-[11px]">
                <thead className="bg-raised/50 font-mono text-[9px] uppercase tracking-wider text-muted">
                  <tr>
                    <th className="px-2 py-1.5">Date</th><th className="px-2 py-1.5">Symbol</th><th className="px-2 py-1.5">Side</th>
                    <th className="px-2 py-1.5">Radar</th><th className="px-2 py-1.5 text-right">Early px</th><th className="px-2 py-1.5 text-right">EOD px</th>
                    <th className="px-2 py-1.5 text-right">Entry adv</th><th className="px-2 py-1.5 text-right">Early edge</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line font-mono">
                  {cmp!.pairs.slice(0, 20).map((p) => (
                    <tr key={`${p.date}-${p.symbol}`}>
                      <td className="px-2 py-1.5 text-muted">{p.date.slice(5)}</td>
                      <td className="px-2 py-1.5 font-bold text-ink">{p.symbol}</td>
                      <td className="px-2 py-1.5" style={{ color: p.bias === "LONG" ? "var(--green)" : "var(--red)" }}>{p.bias}</td>
                      <td className="px-2 py-1.5 text-muted">{p.radar_time}</td>
                      <td className="px-2 py-1.5 text-right tnum">{p.radar_price}</td>
                      <td className="px-2 py-1.5 text-right tnum">{p.eod_price}</td>
                      <td className="px-2 py-1.5 text-right tnum" style={{ color: p.entry_advantage_pct > 0 ? "var(--green)" : "var(--red)" }}>{pct(p.entry_advantage_pct)}</td>
                      <td className="px-2 py-1.5 text-right tnum" style={{ color: p.early_edge_pct === undefined ? "var(--muted)" : p.early_edge_pct > 0 ? "var(--green)" : "var(--red)" }}>{p.resolved ? pct(p.early_edge_pct) : "pending"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
      <p className="font-mono text-[9px] leading-relaxed text-muted">
        <span className="text-ink/80">Entry advantage</span> = how much better the radar's early price was than the EOD board price (direction-adjusted) — computable same day.
        <span className="text-ink/80"> Early edge</span> = next-day P&amp;L from the early entry minus from the EOD entry (positive = catching it early paid). Sample-gated;
        this is the honest test of whether the radar earns its place before you lean on it.
      </p>
    </div>
  );
}

function Stat({ k, v, color }: { k: string; v: string; color?: string }) {
  return (
    <div className="rounded-md border border-line bg-raised/40 p-3">
      <div className="font-mono text-[9px] uppercase tracking-wider text-muted">{k}</div>
      <div className="tnum text-lg font-bold" style={{ color: color ?? "var(--ink)" }}>{v}</div>
    </div>
  );
}

function Col({ title, color, rows }: { title: string; color: string; rows: IgniteRow[] }) {
  return (
    <div className="space-y-2">
      <div className="font-mono text-[10px] font-bold uppercase tracking-wider" style={{ color }}>{title} ({rows.length})</div>
      {rows.length === 0 ? <div className="font-mono text-[10px] text-muted">— none igniting</div> : rows.map((r) => (
        <div key={r.symbol} className="rounded-md border border-line bg-raised/30 p-2.5">
          <div className="flex items-center justify-between">
            <span className="flex items-baseline gap-2">
              <span className="font-mono text-[12px] font-bold text-ink">{r.symbol}</span>
              <span className="tnum font-mono text-[10px]" style={{ color: r.day_pct >= 0 ? "var(--green)" : "var(--red)" }}>{r.day_pct >= 0 ? "+" : ""}{r.day_pct}%</span>
              <span className="font-mono text-[9px] text-muted">₹{r.ltp}</span>
            </span>
            <span className="rounded px-1.5 py-0.5 font-mono text-[9px] font-bold" style={{ background: "rgba(255,138,42,0.18)", color: "#ff8a2a" }}>
              ⚡ {r.score} · {r.vol_pace}×vol
            </span>
          </div>
          <div className="mt-1 font-mono text-[9px] text-muted">
            vs VWAP {r.vs_vwap_pct >= 0 ? "+" : ""}{r.vs_vwap_pct}% · range {r.range_pos} · {r.bias === "LONG" ? "CALL/CE" : "PUT/PE"} side{r.lot_size ? ` · lot ×${r.lot_size}` : ""}
          </div>
        </div>
      ))}
    </div>
  );
}
