import { useEffect, useState } from "react";
import { api } from "../api";
import type { McxWatchlist, McxWatchRow, McxPositions, McxExpiryRisk, McxContext, McxAttribution } from "../types";

/* =============================================================================
   MCX COMMODITIES — isolated from the equity boards. Options on MCX futures.
   Observations / conditions / constraints / review states — never blind buy/sell.
   Every time-sensitive value carries a data-quality/freshness read.
============================================================================= */

const STATE_COLOR: Record<string, string> = {
  ELIGIBLE_FOR_REVIEW: "var(--green)", WATCH: "var(--gold)", ROLL_GUARD: "var(--gold)",
  EVENT_GUARD: "var(--gold)", ILLIQUID: "var(--red)", STALE_DATA: "var(--red)",
  NO_DATA: "var(--muted)", MARKET_CLOSED: "var(--muted)", MAPPING_ERROR: "var(--red)",
  POSITION_RISK_ALERT: "var(--red)", EXIT_REVIEW: "var(--red)",
};
const RISK_COLOR: Record<string, string> = {
  NONE: "var(--muted)", WATCH: "var(--gold)", HIGH: "var(--red)", CRITICAL: "var(--red)", UNKNOWN: "var(--gold)",
};
const GRADE_COLOR: Record<string, string> = {
  A: "var(--green)", B: "var(--green)", C: "var(--gold)", D: "var(--red)", UNKNOWN: "var(--muted)",
};

function Badge({ text, color }: { text: string; color: string }) {
  return (
    <span className="rounded px-1.5 py-0.5 font-mono text-[9px] font-bold uppercase tracking-wider"
      style={{ background: `color-mix(in srgb, ${color} 15%, transparent)`, color }}>{text}</span>
  );
}

const ALIGN_COLOR: Record<string, string> = {
  high: "var(--green)", mixed: "var(--gold)", low: "var(--red)", unavailable: "var(--muted)",
};
const pctStr = (v: number | null | undefined) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${v}%`);

export function Commodities() {
  const [wl, setWl] = useState<McxWatchlist | null>(null);
  const [pos, setPos] = useState<McxPositions | null>(null);
  const [ctx, setCtx] = useState<McxContext | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = () => {
    api.getMcxWatchlist().then((d) => { setWl(d); setErr(null); }).catch(() => setErr("watchlist unavailable"));
    api.getMcxPositions().then(setPos).catch(() => {});
  };
  useEffect(() => {
    load();
    api.getMcxContext().then(setCtx).catch(() => {});
    const id = setInterval(load, 20000);
    const idc = setInterval(() => api.getMcxContext().then(setCtx).catch(() => {}), 60000);
    return () => { clearInterval(id); clearInterval(idc); };
    /* eslint-disable-next-line */
  }, []);

  const dq = wl?.data_quality;
  return (
    <div className="space-y-4">
      <div className="rounded-md border border-gold/25 bg-gold/[0.05] px-4 py-2.5 font-mono text-[10px] leading-relaxed text-muted">
        🛢️ MCX COMMODITIES — options on commodity <span className="text-ink/80">futures</span>, isolated from the stock boards. These are
        <span className="text-gold"> observations, conditions and review states</span>, not buy/sell calls. Expiry can create a futures position
        (devolvement) — settlement/broker rules are <span className="text-signalred">unverified until you confirm them</span>, so expiry-sensitive
        states default to manual review. Nothing here auto-exits, rolls, or sends instructions.
      </div>

      {ctx && (
        <div className="flex flex-wrap items-center gap-2 rounded-md border border-line bg-raised/30 px-3 py-2 font-mono text-[10px]">
          <span className="text-muted">🌐 Global context</span>
          {Object.entries(ctx.macro).map(([k, m]) => (
            <span key={k} className="rounded border border-line px-2 py-0.5">
              {k} <span className="tnum" style={{ color: (m.change_pct ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>{pctStr(m.change_pct)}</span>
              <span className="ml-1 text-[8px] text-muted">{m.status}</span>
            </span>
          ))}
          <span className="text-[9px] text-muted">context-only · delayed · not execution-grade</span>
        </div>
      )}

      <div className="panel space-y-3 rounded-lg p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="flex items-center gap-2 font-display text-base font-bold text-ink">
            🛢️ Commodity watchlist
            <span className="font-mono text-[11px] font-normal text-muted">— MCX {wl?.market_state ?? "…"} · auto-refresh 20s</span>
          </h2>
          {dq && <Badge text={`data ${dq.overall_confidence}`} color={dq.overall_confidence === "high" ? "var(--green)" : dq.overall_confidence === "medium" ? "var(--gold)" : "var(--red)"} />}
        </div>
        {err && <p className="font-mono text-[11px] text-signalred">⚠ {err}</p>}
        {!wl ? (
          <p className="font-mono text-[11px] text-muted">Loading MCX master + quotes…</p>
        ) : (
          <div className="overflow-x-auto rounded-md border border-line">
            <table className="w-full text-left text-[11px]">
              <thead className="bg-raised/50 font-mono text-[9px] uppercase tracking-wider text-muted">
                <tr>
                  {["Commodity", "Active future", "Price", "Chg%", "ATR (pts / %)", "Global + FX", "Roll", "ATM opt", "Liq", "State"].map((h) =>
                    <th key={h} className="px-2 py-1.5">{h}</th>)}
                </tr>
              </thead>
              <tbody className="divide-y divide-line font-mono">
                {wl.rows.map((r) => <Row key={r.root} r={r} attr={ctx?.roots?.[r.root]} />)}
              </tbody>
            </table>
          </div>
        )}
        <p className="font-mono text-[9px] leading-relaxed text-muted">
          <b className="text-ink/80">State</b> is operational, not directional: ELIGIBLE_FOR_REVIEW = fresh + tradable liquidity (review it yourself);
          WATCH = wide spread, insight only; ROLL_GUARD/STALE_DATA/ILLIQUID = not entry-eligible. Options analytics (Black-76 IV, expected move,
          probability) and inter-market context are staged next.
        </p>
      </div>

      <ExpiryRiskPanel pos={pos} />
    </div>
  );
}

function Row({ r, attr }: { r: McxWatchRow; attr?: McxAttribution }) {
  const ts = r.trade_state;
  const g = r.options?.liquidity?.grade ?? "—";
  return (
    <tr className="hover:bg-raised/30">
      <td className="px-2 py-1.5">
        <div className="font-bold text-ink">{r.root}</div>
        {r.economic_root !== r.root && <div className="text-[9px] text-muted">({r.economic_root})</div>}
      </td>
      <td className="px-2 py-1.5 text-muted">{r.active_future ?? "—"}<div className="text-[9px]">exp {r.future_expiry ?? "—"}</div></td>
      <td className="px-2 py-1.5 tnum text-ink">{r.price ?? "—"}</td>
      <td className="px-2 py-1.5 tnum" style={{ color: (r.change_pct ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>
        {r.change_pct == null ? "—" : `${r.change_pct >= 0 ? "+" : ""}${r.change_pct}%`}
      </td>
      <td className="px-2 py-1.5 tnum text-muted">{r.atr ?? "—"}{r.atr_pct != null ? ` / ${r.atr_pct}%` : ""}</td>
      <td className="px-2 py-1.5">
        {attr && attr.alignment !== "unavailable" ? (
          <>
            <div className="text-[9px] text-muted">{attr.benchmark ?? "—"} {pctStr(attr.global_return_pct)} · INR {pctStr(attr.usdinr_return_pct)}</div>
            <Badge text={`align ${attr.alignment}`} color={ALIGN_COLOR[attr.alignment]} />
          </>
        ) : <span className="text-[9px] text-muted">no benchmark</span>}
      </td>
      <td className="px-2 py-1.5">
        {r.roll ? <Badge text={r.roll.state} color={r.roll.state === "front_liquid" ? "var(--green)" : r.roll.state.includes("risk") || r.roll.state === "contract_dislocated" ? "var(--red)" : "var(--gold)"} /> : "—"}
        {r.roll?.front_expiry_days != null && <div className="mt-0.5 text-[9px] text-muted">exp {r.roll.front_expiry_days}d</div>}
      </td>
      <td className="px-2 py-1.5 tnum text-muted">{r.options ? `${r.options.atm_strike}` : "—"}</td>
      <td className="px-2 py-1.5">{r.options ? <Badge text={g} color={GRADE_COLOR[g] ?? "var(--muted)"} /> : "—"}</td>
      <td className="px-2 py-1.5"><Badge text={ts.state} color={STATE_COLOR[ts.state] ?? "var(--muted)"} /><div className="mt-0.5 text-[9px] text-muted">{ts.why}</div></td>
    </tr>
  );
}

function ExpiryRiskPanel({ pos }: { pos: McxPositions | null }) {
  const items = pos?.positions ?? [];
  return (
    <div className="panel space-y-3 rounded-lg p-5">
      <h2 className="flex items-center gap-2 font-display text-base font-bold text-ink">
        ⏳ MCX option positions — expiry / devolvement risk
        <span className="font-mono text-[11px] font-normal text-muted">— options on futures can devolve into a futures position</span>
      </h2>
      {items.length === 0 ? (
        <p className="font-mono text-[11px] text-muted">No open MCX option positions (or Kite not connected).</p>
      ) : (
        <div className="space-y-2">
          {items.map((it, i) => {
            const r = it.expiry_risk as McxExpiryRisk;
            if (!r) return <div key={i} className="font-mono text-[10px] text-muted">{JSON.stringify(it)}</div>;
            return (
              <div key={i} className="rounded-md border border-line bg-raised/30 p-3 font-mono text-[10px]">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-bold text-ink">{r.option_symbol} · {r.side} {r.option_type} · {r.quantity_lots} lot</span>
                  <span className="flex items-center gap-2">
                    <Badge text={`ITM ${r.itm_state}`} color={r.itm_state === "ITM" ? "var(--gold)" : "var(--muted)"} />
                    <Badge text={`risk ${r.expiry_risk_state}`} color={RISK_COLOR[r.expiry_risk_state] ?? "var(--muted)"} />
                  </span>
                </div>
                <div className="mt-1 text-muted">
                  settlement <span className="text-ink/80">{r.settlement_mode}</span> · linked future {r.linked_future_symbol ?? "—"} (exp {r.linked_future_expiry ?? "—"})
                  {r.estimated_devolved_future_side !== "NONE" && r.estimated_devolved_future_side !== "UNKNOWN" &&
                    <> · devolves <span className="text-signalred">{r.estimated_devolved_future_side}</span> future{r.estimated_devolved_future_notional ? ` ≈ ₹${Math.round(r.estimated_devolved_future_notional).toLocaleString("en-IN")}` : ""}</>}
                </div>
                {r.warnings?.length > 0 && (
                  <ul className="mt-1 list-disc pl-4 text-gold">{r.warnings.map((w, j) => <li key={j}>{w}</li>)}</ul>
                )}
              </div>
            );
          })}
        </div>
      )}
      <p className="font-mono text-[9px] leading-relaxed text-muted">
        Alerts and review states only — the system never auto-squares-off, sends contrary instructions, rolls, or hedges. Settlement/tender/broker-cutoff
        semantics are unverified until you fill the contract-profile registry, so positions stay in manual review.
      </p>
    </div>
  );
}
