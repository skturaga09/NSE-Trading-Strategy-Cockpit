import { useEffect, useState } from "react";
import { api } from "../api";
import type { SwingScan, SwingCandidate } from "../types";

/* =============================================================================
   OVERNIGHT SWING lane — SEPARATE from the intraday discipline console.
   Uses today's close data (close strength + futures OI buildup = the buy/sell
   positioning signal) to surface constructive vs weak names into tomorrow.
   NOT a prediction: overnight gaps are driven by news/global cues that haven't
   happened yet. Carries GAP RISK — the stop can be jumped overnight, so the real
   loss can exceed the planned loss. Educational only, not SEBI-registered advice.
============================================================================= */

const CAPITAL = 200_000;
const inr = (n: number) => `₹${Math.round(n).toLocaleString("en-IN")}`;

export function Swing() {
  const [scan, setScan] = useState<SwingScan | null>(null);
  const [loading, setLoading] = useState(false);
  const [riskPct, setRiskPct] = useState(5); // % of capital per swing trade
  const riskBudget = Math.round((riskPct / 100) * CAPITAL);

  const run = async () => {
    setLoading(true);
    try {
      setScan(await api.getSwingScan());
    } catch {
      setScan(null);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { void run(); /* eslint-disable-next-line */ }, []);

  return (
    <div className="space-y-6">
      <div className="rounded-md border border-signalred/30 bg-signalred/[0.06] px-4 py-2.5 font-mono text-[10px] leading-relaxed text-muted">
        ⚠ OVERNIGHT SWING lane — <span className="text-signalred">separate from your intraday rules</span>. You'd enter today and
        carry the position overnight, so it has <span className="text-signalred">GAP RISK</span>: the price can open far past your stop
        before you can act, and the real loss can exceed the planned loss. This is a positioning screen (close strength + OI buildup),
        <span className="text-gold"> NOT a prediction</span> of tomorrow's direction. Educational only — not SEBI-registered advice.
      </div>

      <div className="panel space-y-3 rounded-lg p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="flex items-center gap-2 font-display text-base font-bold text-ink">
            🌙 EOD Positioning <span className="font-mono text-[11px] font-normal text-muted">— today's data → tomorrow's watchlist; buy/sell via futures OI buildup</span>
          </h2>
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 font-mono text-[10px] text-muted">
              risk/trade
              <input type="range" min={0.5} max={10} step={0.5} value={riskPct} onChange={(e) => setRiskPct(Number(e.target.value))} className="accent-cyan" />
              <span className="tnum font-bold text-cyan">{riskPct}% · {inr(riskBudget)}</span>
            </label>
            <button onClick={run} disabled={loading}
              className="rounded-md border border-cyan/50 bg-cyan/15 px-4 py-2 font-mono text-xs font-bold text-cyan hover:bg-cyan/25 disabled:opacity-50">
              {loading ? "⏳ Scanning…" : "⟳ Rescan EOD"}
            </button>
          </div>
        </div>

        {!scan ? (
          <p className="font-mono text-[11px] text-muted">Scanning the F&amp;O universe on today's close…</p>
        ) : !scan.is_live ? (
          <p className="font-mono text-[11px] text-gold">⚠ Unavailable — {scan.source}. Connect Kite (System Check), then retry. Best run near/after close.</p>
        ) : (
          <>
            <div className="font-mono text-[10px] text-muted">
              ● {scan.source} · {scan.scanned}/{scan.universe} scanned · {scan.timestamp} · sized to {inr(riskBudget)} ({riskPct}% of {inr(CAPITAL)})
            </div>
            <FitBanner scan={scan} riskBudget={riskBudget} />
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <Column title="▲ Constructive (bullish close + OI)" color="var(--green)" rows={scan.constructive} riskBudget={riskBudget} />
              <Column title="▼ Weak (bearish close + OI)" color="var(--red)" rows={scan.weak} riskBudget={riskBudget} />
            </div>
            <p className="font-mono text-[9px] leading-relaxed text-muted">
              Ranked by close strength; OI buildup (from futures, today vs yesterday) shows where positioning leans — treat as supporting evidence,
              never a standalone signal. Stops are wider than intraday (≥3% or 1.5× today's range) to survive a normal overnight move, but a gap can
              still jump them. “Lots at budget” = floor(risk budget ÷ per-lot risk); most stock futures won't fit a ₹2L account — see the note above.
            </p>
          </>
        )}
      </div>
    </div>
  );
}

function FitBanner({ scan, riskBudget }: { scan: SwingScan; riskBudget: number }) {
  const all = [...scan.constructive, ...scan.weak];
  const fit = all.filter((c) => Math.floor(riskBudget / c.plan.per_lot_risk) >= 1).length;
  if (fit > 0) return null;
  return (
    <div className="rounded-md border border-gold/30 bg-gold/10 px-3 py-2 font-mono text-[10px] leading-relaxed text-gold">
      None of these fit 1 futures lot within {inr(riskBudget)} — an F&amp;O lot's notional (~₹5–10L) is 2.5–5× a ₹2L account, so one lot risks
      ₹25k–45k on an overnight stop. For overnight swing on this account, the realistic defined-risk vehicle is <span className="text-ink/80">buying an
      option</span> (max loss = premium). Load the stock in the Intraday tab's chain view to see the option cost and tomorrow's landing scenarios.
    </div>
  );
}

function Column({ title, color, rows, riskBudget }: { title: string; color: string; rows: SwingCandidate[]; riskBudget: number }) {
  return (
    <div className="space-y-2">
      <div className="font-mono text-[10px] font-bold uppercase tracking-wider" style={{ color }}>{title}</div>
      {rows.length === 0 ? <div className="font-mono text-[10px] text-muted">—</div> : rows.map((c) => (
        <SwingRow key={c.symbol} c={c} riskBudget={riskBudget} />
      ))}
    </div>
  );
}

function SwingRow({ c, riskBudget }: { c: SwingCandidate; riskBudget: number }) {
  const lots = Math.floor(riskBudget / c.plan.per_lot_risk);
  const fits = lots >= 1;
  const buildupColor = c.buildup ? (c.buildup.lean === "bullish" ? "var(--green)" : "var(--red)") : "var(--muted)";
  return (
    <div className="rounded-md border border-line bg-raised/30 p-2.5">
      <div className="flex items-center justify-between">
        <span className="flex items-baseline gap-2">
          <span className="font-mono text-[12px] font-bold text-ink">{c.symbol}</span>
          <span className="tnum font-mono text-[10px]" style={{ color: c.pct_change >= 0 ? "var(--green)" : "var(--red)" }}>{c.pct_change >= 0 ? "+" : ""}{c.pct_change}%</span>
          <span className="font-mono text-[9px] text-muted">rng {c.range_pos}</span>
        </span>
        {c.buildup && (
          <span className="rounded px-1.5 py-0.5 font-mono text-[9px] font-bold uppercase" style={{ background: `color-mix(in srgb, ${buildupColor} 15%, transparent)`, color: buildupColor }}>
            {c.buildup.label}{c.buildup.oi_chg_pct !== null ? ` ${c.buildup.oi_chg_pct >= 0 ? "+" : ""}${c.buildup.oi_chg_pct}% OI` : ""}
          </span>
        )}
      </div>
      <div className="mt-1.5 grid grid-cols-3 gap-2 font-mono text-[10px]">
        <div><span className="text-muted">Entry</span> <span className="tnum text-ink">{c.plan.entry}</span></div>
        <div><span className="text-muted">Stop</span> <span className="tnum text-signalred">{c.plan.stop}</span> <span className="text-muted">({c.plan.stop_pct}%)</span></div>
        <div><span className="text-muted">Target</span> <span className="tnum text-signalgreen">{c.plan.target}</span></div>
      </div>
      <div className="mt-1 flex flex-wrap items-center justify-between gap-2 font-mono text-[10px]">
        <span className="text-muted">1 lot (×{c.lot_size}) risks <span className="tnum text-ink">{inr(c.plan.per_lot_risk)}</span> · notional <span className="tnum">{inr(c.plan.notional_1lot)}</span></span>
        <span className="tnum font-bold" style={{ color: fits ? "var(--green)" : "var(--red)" }}>
          {fits ? `${lots} lot${lots > 1 ? "s" : ""} fit` : "0 lots — exceeds budget"}
        </span>
      </div>
    </div>
  );
}
