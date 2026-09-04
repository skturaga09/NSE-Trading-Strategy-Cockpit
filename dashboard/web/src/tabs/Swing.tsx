import { useEffect, useState } from "react";
import { api } from "../api";
import type { SwingScan, SwingCandidate, OptionChain, OvernightBrief } from "../types";

// Black-Scholes (fair-value the option at the swing target)
function erf(x: number): number {
  const t = 1 / (1 + 0.3275911 * Math.abs(x));
  const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x);
  return x >= 0 ? y : -y;
}
const _N = (x: number) => 0.5 * (1 + erf(x / Math.SQRT2));
function bsPrice(S: number, K: number, T: number, sigma: number, isCall: boolean, r = 0.065): number {
  if (T <= 0 || sigma <= 0) return Math.max(0, isCall ? S - K : K - S);
  const d1 = (Math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * Math.sqrt(T));
  const d2 = d1 - sigma * Math.sqrt(T);
  return isCall ? S * _N(d1) - K * Math.exp(-r * T) * _N(d2) : K * Math.exp(-r * T) * _N(-d2) - S * _N(-d1);
}
type OptState = "loading" | OptionChain | null;

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

  const [opts, setOpts] = useState<Record<string, OptState>>({});
  const loadOption = async (symbol: string) => {
    if (opts[symbol] && opts[symbol] !== null) { // toggle off if already open
      if (opts[symbol] !== "loading") { setOpts((s) => ({ ...s, [symbol]: null })); return; }
    }
    setOpts((s) => ({ ...s, [symbol]: "loading" }));
    try {
      const chain = await api.getOptionChain(symbol);
      setOpts((s) => ({ ...s, [symbol]: chain }));
    } catch {
      setOpts((s) => ({ ...s, [symbol]: null }));
    }
  };

  // Rescan button forces a fresh OI snapshot (force=true); the silent auto-poll does not.
  const run = async (force = false) => {
    setLoading(true);
    try {
      setScan(await api.getSwingScan(force));
    } catch {
      setScan(null);
    } finally {
      setLoading(false);
    }
  };
  // Auto-run on open, then a silent 30s refresh — the swing scan fires ~16 futures
  // OI-history calls per run, so 3s would hit Kite's rate limits; 30s is safe and
  // EOD-positioning data changes slowly anyway.
  useEffect(() => {
    void run();
    const id = setInterval(() => { api.getSwingScan().then(setScan).catch(() => {}); }, 30000);
    return () => clearInterval(id);
    /* eslint-disable-next-line */
  }, []);

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
            <button onClick={() => run(true)} disabled={loading}
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

            <IgnitionBoard scan={scan} riskBudget={riskBudget} opts={opts} onOption={loadOption} />

            <OvernightBoard scan={scan} riskBudget={riskBudget} opts={opts} onOption={loadOption} />

            <FitBanner scan={scan} riskBudget={riskBudget} />
            <details className="group">
              <summary className="cursor-pointer font-mono text-[10px] font-bold uppercase tracking-wider text-muted hover:text-ink">
                ▸ Close-strength boards (price only, top {scan.constructive.length}/{scan.weak.length}) — secondary
              </summary>
              <div className="mt-3 grid grid-cols-1 gap-4 lg:grid-cols-2">
                <Column title="▲ Constructive (bullish close + OI)" color="var(--green)" rows={scan.constructive} riskBudget={riskBudget} opts={opts} onOption={loadOption} />
                <Column title="▼ Weak (bearish close + OI)" color="var(--red)" rows={scan.weak} riskBudget={riskBudget} opts={opts} onOption={loadOption} />
              </div>
            </details>
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

const TIER_STYLE: Record<string, { bg: string; fg: string; label: string }> = {
  strong: { bg: "rgba(88,214,141,0.18)", fg: "var(--green)", label: "STRONG" },
  notable: { bg: "rgba(244,185,66,0.16)", fg: "var(--gold)", label: "NOTABLE" },
};

function IgnitionBoard({ scan, riskBudget, opts, onOption }: {
  scan: SwingScan; riskBudget: number; opts: Record<string, OptState>; onOption: (s: string) => void;
}) {
  if (!scan.oi_ready) return null;   // shares the OI warm; OvernightBoard shows the warming state
  const ign = scan.ignition ?? [];
  return (
    <div className="space-y-3 rounded-lg p-4" style={{ border: "1px solid rgba(255,138,42,0.42)", background: "rgba(255,138,42,0.06)" }}>
      <h3 className="flex flex-wrap items-center gap-2 font-display text-sm font-bold text-ink">
        🔥 Ignition — early accumulation
        <span className="font-mono text-[10px] font-normal text-muted">— volume surge + fresh OI + breakout (the SOLARINDS footprint)</span>
      </h3>
      {ign.length === 0 ? (
        <div className="font-mono text-[10px] text-muted">— none firing today (needs ≥1.5× its own average volume + a fresh OI buildup).</div>
      ) : (
        <div className="grid grid-cols-1 gap-2 lg:grid-cols-2">
          {ign.map((c) => <SwingRow key={c.symbol} c={c} riskBudget={riskBudget} opt={opts[c.symbol]} onOption={() => onOption(c.symbol)} />)}
        </div>
      )}
      <p className="font-mono text-[9px] leading-relaxed text-muted">
        Ranks the whole F&amp;O universe 0–100 by fusing <span className="text-ink/80">relative volume</span> (today vs its ~20-day average),
        <span className="text-ink/80"> multi-day OI build</span>, a direction-agreeing <span className="text-ink/80">strong close</span>, and
        <span className="text-ink/80"> breakout proximity</span> — the footprint of a name being accumulated before it's obvious. All public data; the edge is
        <span className="text-ink/80"> complete, consistent coverage</span> of 200+ names, not secret info. Every pick is logged to the learning layer below to test whether it
        actually runs — so this stays a <span className="text-gold">measured screen, not a promise</span>. Overnight gap risk applies; you size and decide.
      </p>
    </div>
  );
}

function OvernightBoard({ scan, riskBudget, opts, onOption }: {
  scan: SwingScan; riskBudget: number; opts: Record<string, OptState>; onOption: (s: string) => void;
}) {
  const longs = scan.overnight_longs ?? [];
  const shorts = scan.overnight_shorts ?? [];
  const th = scan.oi_thresholds;
  const below = scan.oi_below_threshold;
  return (
    <div className="space-y-3 rounded-lg border border-gold/30 bg-gold/[0.05] p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="flex items-center gap-2 font-display text-sm font-bold text-ink">
          🌙 Overnight hold candidates
          <span className="font-mono text-[10px] font-normal text-muted">
            — fresh OI buildup ≥{th?.notable ?? 10}% + price agrees (the "carry overnight" signal)
          </span>
        </h3>
        <span className="font-mono text-[9px] text-muted">
          {scan.oi_refreshing ? "↻ OI refreshing (~1 min)…" : scan.oi_ready ? `OI as of ${scan.oi_ts ?? "—"}` : "OI warming…"}
        </span>
      </div>

      {!scan.oi_ready ? (
        <div className="rounded-md border border-cyan/25 bg-cyan/[0.06] px-3 py-2 font-mono text-[10px] text-cyan">
          ⏳ Scanning open interest across all {scan.universe} F&amp;O names (~1 min, runs in the background). The board fills in on the next
          auto-refresh — nothing is dropped; every name is checked.
        </div>
      ) : (
        <>
          {scan.oi_forming && (
            <div className="rounded-md border border-gold/30 bg-gold/10 px-3 py-1.5 font-mono text-[9px] leading-relaxed text-gold">
              ⚠ Today's OI is still <span className="font-bold">forming</span> (before 2 pm) — day-over-day OI change is incomplete until late session. Read these near/after close.
            </div>
          )}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <div className="space-y-2">
              <div className="font-mono text-[10px] font-bold uppercase tracking-wider" style={{ color: "var(--green)" }}>
                ▲ Long buildup ({longs.length}) — price up + OI up
              </div>
              {longs.length === 0
                ? <div className="font-mono text-[10px] text-muted">— none ≥{th?.notable ?? 10}% today</div>
                : longs.map((c) => <SwingRow key={c.symbol} c={c} riskBudget={riskBudget} opt={opts[c.symbol]} onOption={() => onOption(c.symbol)} />)}
              <OverflowChips more={scan.overnight_longs_more} color="var(--green)" />
            </div>
            <div className="space-y-2">
              <div className="font-mono text-[10px] font-bold uppercase tracking-wider" style={{ color: "var(--red)" }}>
                ▼ Short buildup ({shorts.length}) — price down + OI up
              </div>
              {shorts.length === 0
                ? <div className="font-mono text-[10px] text-muted">— none ≥{th?.notable ?? 10}% today</div>
                : shorts.map((c) => <SwingRow key={c.symbol} c={c} riskBudget={riskBudget} opt={opts[c.symbol]} onOption={() => onOption(c.symbol)} />)}
              <OverflowChips more={scan.overnight_shorts_more} color="var(--red)" />
            </div>
          </div>
          <BuildingBoard scan={scan} riskBudget={riskBudget} opts={opts} onOption={onOption} />

          <p className="font-mono text-[9px] leading-relaxed text-muted">
            Fresh <span className="text-ink/80">buildup = open interest rising with price</span> (new positions committed), the day-1 signal you hold overnight to
            catch tomorrow's continuation. <span className="text-gold">Short covering / long unwinding</span> (OI falling) are excluded — they're positions closing, not
            fresh conviction. A buildup does <span className="text-gold">not</span> guarantee a gap up; overnight news can still gap it against you. Tiers: ≥{th?.notable ?? 10}% notable, ≥{th?.strong ?? 20}% strong.
            {below && (below.long + below.short > 0) ? <> Below the bar today: {below.long} long / {below.short} short mild buildups (5–{th?.notable ?? 10}%, not shown).</> : null}
            {scan.oi_unavailable_count ? <> · {scan.oi_unavailable_count} name(s) OI-unavailable (check manually — not dropped).</> : null}
          </p>
        </>
      )}
    </div>
  );
}

function BuildingBoard({ scan, riskBudget, opts, onOption }: {
  scan: SwingScan; riskBudget: number; opts: Record<string, OptState>; onOption: (s: string) => void;
}) {
  const longs = scan.building_longs ?? [];
  const shorts = scan.building_shorts ?? [];
  if (longs.length === 0 && shorts.length === 0) return null;
  return (
    <div className="space-y-2 rounded-md border border-cyan/25 bg-cyan/[0.04] p-3">
      <div className="font-mono text-[10px] font-bold uppercase tracking-wider text-cyan">
        ⚡ Building — strong close, lighter OI (&lt;10%)
        <span className="ml-1 font-normal normal-case text-muted">— fresh buildup + a big close (e.g. SOLARINDS type); conviction from price, OI confirming</span>
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="space-y-2">
          <div className="font-mono text-[9px] font-bold uppercase tracking-wider" style={{ color: "var(--green)" }}>▲ Long ({longs.length})</div>
          {longs.length === 0
            ? <div className="font-mono text-[10px] text-muted">—</div>
            : longs.map((c) => <SwingRow key={c.symbol} c={c} riskBudget={riskBudget} opt={opts[c.symbol]} onOption={() => onOption(c.symbol)} />)}
        </div>
        <div className="space-y-2">
          <div className="font-mono text-[9px] font-bold uppercase tracking-wider" style={{ color: "var(--red)" }}>▼ Short ({shorts.length})</div>
          {shorts.length === 0
            ? <div className="font-mono text-[10px] text-muted">—</div>
            : shorts.map((c) => <SwingRow key={c.symbol} c={c} riskBudget={riskBudget} opt={opts[c.symbol]} onOption={() => onOption(c.symbol)} />)}
        </div>
      </div>
      <p className="font-mono text-[9px] leading-relaxed text-muted">
        These clear a smaller OI bar (≥1%, under the 10% "notable" line) but closed <span className="text-ink/80">strong</span> (≥2.5% move, near the day's extreme,
        the right side of VWAP) — the strong close is the conviction, OI just confirms fresh positioning. Lower OI conviction than the board above; the learning
        layer tracks this group separately so you'll see whether it actually pays.
      </p>
    </div>
  );
}

function OverflowChips({ more, color }: { more?: OvernightBrief[]; color: string }) {
  if (!more || more.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1.5 pt-1">
      <span className="font-mono text-[9px] text-muted">also ≥bar:</span>
      {more.map((m) => (
        <span key={m.symbol} className="rounded px-1.5 py-0.5 font-mono text-[9px]"
          style={{ background: `color-mix(in srgb, ${color} 12%, transparent)`, color }}>
          {m.symbol} {m.oi_chg_pct !== null ? `${m.oi_chg_pct >= 0 ? "+" : ""}${m.oi_chg_pct}%` : ""}
        </span>
      ))}
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

function Column({ title, color, rows, riskBudget, opts, onOption }: {
  title: string; color: string; rows: SwingCandidate[]; riskBudget: number;
  opts: Record<string, OptState>; onOption: (s: string) => void;
}) {
  return (
    <div className="space-y-2">
      <div className="font-mono text-[10px] font-bold uppercase tracking-wider" style={{ color }}>{title}</div>
      {rows.length === 0 ? <div className="font-mono text-[10px] text-muted">—</div> : rows.map((c) => (
        <SwingRow key={c.symbol} c={c} riskBudget={riskBudget} opt={opts[c.symbol]} onOption={() => onOption(c.symbol)} />
      ))}
    </div>
  );
}

function SwingRow({ c, riskBudget, opt, onOption }: { c: SwingCandidate; riskBudget: number; opt: OptState; onOption: () => void }) {
  const lots = Math.floor(riskBudget / c.plan.per_lot_risk);
  const fits = lots >= 1;
  const buildupColor = c.buildup ? (c.buildup.lean === "bullish" ? "var(--green)" : "var(--red)") : "var(--muted)";
  const open = opt != null;
  // Long buildup (bullish) → buy a CALL; short buildup (bearish) → buy a PUT.
  const isCall = c.bias === "LONG";
  const optType = isCall ? "CALL (CE)" : "PUT (PE)";
  const optColor = isCall ? "var(--green)" : "var(--red)";
  return (
    <div className="rounded-md border border-line bg-raised/30 p-2.5">
      <div className="flex items-center justify-between">
        <span className="flex flex-wrap items-baseline gap-2">
          <span className="font-mono text-[12px] font-bold text-ink">{c.symbol}</span>
          <span className="tnum font-mono text-[10px]" style={{ color: c.pct_change >= 0 ? "var(--green)" : "var(--red)" }}>{c.pct_change >= 0 ? "+" : ""}{c.pct_change}%</span>
          <span className="font-mono text-[9px] text-muted">rng {c.range_pos}</span>
          {c.ignition && (
            <span className="rounded px-1.5 py-0.5 font-mono text-[9px] font-bold" style={{ background: "rgba(255,138,42,0.18)", color: "#ff8a2a" }}>
              🔥 {c.ignition.score} · {c.ignition.rel_volume}×vol{c.ignition.oi_up_days ? ` · OI↑${c.ignition.oi_up_days}d` : ""}
            </span>
          )}
        </span>
        {c.buildup && (
          <span className="flex items-center gap-1">
            {c.buildup.tier && TIER_STYLE[c.buildup.tier] && (
              <span className="rounded px-1 py-0.5 font-mono text-[8px] font-bold uppercase tracking-wider"
                style={{ background: TIER_STYLE[c.buildup.tier].bg, color: TIER_STYLE[c.buildup.tier].fg }}>
                {TIER_STYLE[c.buildup.tier].label}
              </span>
            )}
            <span className="rounded px-1.5 py-0.5 font-mono text-[9px] font-bold uppercase" style={{ background: `color-mix(in srgb, ${buildupColor} 15%, transparent)`, color: buildupColor }}>
              {c.buildup.label}{c.buildup.oi_chg_pct !== null ? ` ${c.buildup.oi_chg_pct >= 0 ? "+" : ""}${c.buildup.oi_chg_pct}% OI` : ""}
            </span>
            <span className="rounded px-1.5 py-0.5 font-mono text-[9px] font-bold uppercase"
              title={isCall ? "Long buildup = bullish lean → a CALL (CE) profits if it rises" : "Short buildup = bearish lean → a PUT (PE) profits if it falls"}
              style={{ background: `color-mix(in srgb, ${optColor} 24%, transparent)`, color: optColor }}>
              → buy {optType}
            </span>
          </span>
        )}
      </div>
      <div className="mt-1.5 grid grid-cols-2 gap-2 font-mono text-[10px] sm:grid-cols-4">
        <div><span className="text-muted">Entry</span> <span className="tnum text-ink">{c.plan.entry}</span></div>
        <div><span className="text-muted">Stop</span> <span className="tnum text-signalred">{c.plan.stop}</span> <span className="text-muted">({c.plan.stop_pct}%)</span></div>
        <div><span className="text-muted">Target</span> <span className="tnum text-signalgreen">{c.plan.target}</span></div>
        <div><span className="text-muted">R:R</span> <span className="tnum font-bold" style={{ color: (c.plan.rr ?? 0) >= 2 ? "var(--green)" : "var(--gold)" }}>{c.plan.rr ?? "—"}</span></div>
      </div>
      <div className="mt-0.5 font-mono text-[9px] text-muted">
        stop: {c.plan.stop_basis} · target: {c.plan.target_basis}
      </div>
      <div className="mt-1 flex flex-wrap items-center justify-between gap-2 font-mono text-[10px]">
        <span className="text-muted">Future: 1 lot (×{c.lot_size}) risks <span className="tnum text-ink">{inr(c.plan.per_lot_risk)}</span>
          <span className="tnum font-bold" style={{ color: fits ? "var(--green)" : "var(--red)" }}> · {fits ? `${lots} lot${lots > 1 ? "s" : ""} fit` : "0 fit"}</span>
        </span>
        <button onClick={onOption}
          className="rounded border px-2 py-0.5 font-mono text-[9px] font-bold uppercase hover:opacity-80"
          style={{ borderColor: `color-mix(in srgb, ${optColor} 45%, transparent)`, background: `color-mix(in srgb, ${optColor} 12%, transparent)`, color: optColor }}>
          {open ? "▾ hide plan" : `▸ ${isCall ? "CALL" : "PUT"}-buy plan`}
        </button>
      </div>
      {opt === "loading" && <div className="mt-2 font-mono text-[10px] text-muted">Loading {c.symbol} option chain…</div>}
      {opt && opt !== "loading" && <OptionBuyPlan chain={opt} c={c} riskBudget={riskBudget} />}
    </div>
  );
}

function OptionBuyPlan({ chain, c, riskBudget }: { chain: OptionChain; c: SwingCandidate; riskBudget: number }) {
  if (!chain.is_live) {
    return <div className="mt-2 rounded border border-gold/30 bg-gold/10 px-2 py-1.5 font-mono text-[10px] text-gold">Option chain unavailable — {chain.source}</div>;
  }
  const atm = chain.rows.find((r) => r.atm);
  const isCall = c.bias === "LONG";
  const leg = isCall ? atm?.call : atm?.put;
  const lot = chain.lot_size;
  const spot = chain.spot;
  if (!atm || !leg || leg.ltp == null || !lot || !spot) {
    return <div className="mt-2 font-mono text-[10px] text-muted">No ATM {isCall ? "CALL" : "PUT"} data.</div>;
  }
  const premium = leg.ltp, strike = atm.strike;
  const costPerLot = Math.round(premium * lot);        // debit paid
  const maxLots = Math.floor(riskBudget / costPerLot); // defined risk = premium; fits budget
  const totalCost = maxLots * costPerLot;
  const breakeven = isCall ? strike + premium : strike - premium;
  // Fair value at the swing target (same IV, one day less to expiry) → P&L per lot.
  const iv = leg.iv ?? 20;
  const days = chain.expiry ? Math.max(1, Math.ceil((new Date(chain.expiry + "T15:30:00+05:30").getTime() - Date.now()) / 86_400_000)) : 5;
  const projPrem = bsPrice(c.plan.target, strike, Math.max(days - 1, 0) / 365, iv / 100, isCall);
  const pnlAtTargetPerLot = Math.round((projPrem - premium) * lot);
  const fits = maxLots >= 1;

  return (
    <div className="mt-2 space-y-1.5 rounded-md border border-cyan/25 bg-cyan/[0.05] p-2.5 font-mono text-[10px]">
      <div className="font-bold text-cyan">Buy ATM {strike} {isCall ? "CALL" : "PUT"} @ ₹{premium} <span className="font-normal text-muted">(defined risk — can't lose more than the premium)</span></div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3">
        <div><span className="text-muted">Cost / lot</span> <span className="tnum text-ink">{inr(costPerLot)}</span> <span className="text-muted">(×{lot})</span></div>
        <div><span className="text-muted">Lots in {inr(riskBudget)}</span> <span className="tnum font-bold" style={{ color: fits ? "var(--green)" : "var(--red)" }}>{fits ? `${maxLots}` : "0 — 1 lot too dear"}</span></div>
        <div><span className="text-muted">Total outlay</span> <span className="tnum text-ink">{fits ? inr(totalCost) : "—"}</span></div>
        <div><span className="text-muted">Max loss</span> <span className="tnum text-signalred">{fits ? inr(totalCost) : inr(costPerLot)}</span> <span className="text-muted">(= premium)</span></div>
        <div><span className="text-muted">Breakeven (underlying)</span> <span className="tnum">₹{breakeven.toFixed(1)}</span></div>
        <div><span className="text-muted">Spread</span> <span className="tnum" style={{ color: leg.spread != null && premium && leg.spread / premium <= 0.03 ? "var(--green)" : "var(--gold)" }}>{leg.spread ?? "—"}</span></div>
      </div>
      <div className="border-t border-line pt-1">
        <span className="text-muted">If underlying reaches swing target ₹{c.plan.target}:</span> option ≈ <span className="tnum">₹{Math.max(0, projPrem).toFixed(1)}</span> →
        <span className="tnum font-bold" style={{ color: pnlAtTargetPerLot >= 0 ? "var(--green)" : "var(--red)" }}> {pnlAtTargetPerLot >= 0 ? "+" : "−"}{inr(Math.abs(pnlAtTargetPerLot))}/lot</span>
      </div>
      <p className="text-[9px] leading-relaxed text-muted">
        Defined risk (worst case = premium), which is why an option fits a ₹2L account where a future doesn't. But overnight <span className="text-gold">theta + IV
        crush</span> erode the premium even if the stock is flat, and the underlying must clear breakeven to profit. Target P&L is a Black-Scholes estimate (same IV,
        one day out), not a fill. Verify spread/liquidity before acting.
      </p>
    </div>
  );
}
