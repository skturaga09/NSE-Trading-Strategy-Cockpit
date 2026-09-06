import { useEffect, useState } from "react";
import { api } from "../api";
import type { IgniteScan, IgniteRow } from "../types";

/* =============================================================================
   INTRADAY IGNITION RADAR — early-entry lane (separate from the EOD swing board).
   Catches names STARTING to move on volume (leading footprint: volume pace + price
   breakout + VWAP side) so you enter near the start instead of chasing at EOD.
   Earlier = noisier; a heads-up screen, NOT advice. Logged for early-vs-EOD study.
============================================================================= */

export function Radar() {
  const [scan, setScan] = useState<IgniteScan | null>(null);
  const [loading, setLoading] = useState(false);

  const run = async () => {
    setLoading(true);
    try { setScan(await api.getIgnite()); } catch { setScan(null); } finally { setLoading(false); }
  };
  useEffect(() => {
    void run();
    const id = setInterval(() => { api.getIgnite().then(setScan).catch(() => {}); }, 15000);
    return () => clearInterval(id);
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
            ⚠ Market closed — the radar runs live during the session (09:15–15:30 IST). {scan.scanned}/{scan.universe} names loaded from the last snapshot.
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
