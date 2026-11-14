// D — Option chain (Phase 11): CE / PE OI distribution, OI change, premium change, IV (Black-76, from a fresh book's mid),
// concentration, liquidity, per-strike positioning HYPOTHESES and the selected-contract comparison. Every number is a
// backend field (engine/api.py /chain); UNAVAILABLE values show "—" with their reason. Nothing here is mocked.
import { useEffect, useState } from "react";
import { useEnv, type Maybe, type View } from "../api";
import { Chip, Panel, Tip, V, inr, isU, num, pct } from "../core";

type Greeks = { delta: number; gamma: number; theta: number; vega: number };
interface Row { token: number; kind: "CE" | "PE"; strike: number; oi: Maybe<number>; oi_change: Maybe<number>; oi_change_pct: Maybe<number>;
  volume_day: Maybe<number>; premium: Maybe<number>; premium_change_pct: Maybe<number>; spread_pct: Maybe<number>;
  depth_bid_qty: Maybe<number>; depth_ask_qty: Maybe<number>; iv: Maybe<number>; iv_change_pts: Maybe<number>;
  greeks: Maybe<Greeks>; hypothesis: string; evidence: string[] }
interface Snap { expiry: string; atm_strike: Maybe<number>; underlying_price: Maybe<number>; underlying_change_pct: Maybe<number>;
  rows: Row[]; pcr_oi: Maybe<number>; pcr_volume: Maybe<number>; concentration: Record<"CE" | "PE", Maybe<[number, number]>>;
  concentration_change: Record<"CE" | "PE", Maybe<number>>; iv_coverage: [number, number] }
interface Cmp { role: string; selected: boolean; strike: number; kind: string; premium: Maybe<number>; spread_pct: Maybe<number>;
  iv: Maybe<number>; greeks: Maybe<Greeks>; oi: Maybe<number>; oi_change: Maybe<number>; volume_day: Maybe<number>;
  depth_bid_qty: Maybe<number>; depth_ask_qty: Maybe<number>; hypothesis: string }
interface Data { underlying: string; underlyings: string[]; snapshot_ns: number; options_config_version: string; expiries: Snap[];
  selected: Record<string, unknown> | null; comparison: Maybe<Cmp[]>; labels: string[] }

const ivp = (v: number) => `${(v * 100).toFixed(1)}%`;
const TONE: Record<string, "ok" | "warning" | "unavailable" | "accent"> = { UNCERTAIN: "unavailable", SPREAD_OR_HEDGE_SUSPECTED: "warning" };

export function OptionChain({ view }: { view: View }) {
  const [und, setUnd] = useState<string | null>(null);
  const [exp, setExp] = useState(0);
  useEffect(() => setExp(0), [und, view.date]);
  const q = useEnv<Data>("chain", view, { underlying: und }, 30_000);
  const d = q.data?.data;
  const s = d?.expiries[exp];
  const strikes = s ? [...new Set(s.rows.map((r) => r.strike))].sort((a, b) => a - b) : [];
  const at = (k: number, kind: "CE" | "PE") => s?.rows.find((r) => r.strike === k && r.kind === kind);

  return (
    <Panel title="Option chain" env={q.data} error={q.error} right={d && (
      <div className="fo-flex fo-gap-3 fo-text-xs">
        <select aria-label="underlying" value={d.underlying} onChange={(e) => setUnd(e.target.value)}
          className="fo-h-control fo-rounded-md fo-border fo-border-line fo-bg-raised fo-px-3">
          {d.underlyings.map((u) => <option key={u}>{u}</option>)}
        </select>
        <select aria-label="expiry" value={exp} onChange={(e) => setExp(Number(e.target.value))}
          className="fo-h-control fo-rounded-md fo-border fo-border-line fo-bg-raised fo-px-3">
          {d.expiries.map((x, i) => <option key={x.expiry} value={i}>{x.expiry}</option>)}
        </select>
      </div>)}>
      {d && s && (
        <div className="fo-grid fo-gap-5">
          <div className="fo-flex fo-flex-wrap fo-gap-5 fo-text-xs">
            <span>ATM <V v={s.atm_strike} f={num(2)} /></span>
            <span>underlying (near-month future mid) <V v={s.underlying_price} f={inr} /> <V v={s.underlying_change_pct} f={pct} /></span>
            <span>PCR (OI, ATM ± range) <V v={s.pcr_oi} f={num(2)} /></span>
            <span>PCR (volume) <V v={s.pcr_volume} f={num(2)} /></span>
            {(["CE", "PE"] as const).map((k) => (
              <span key={k}>{k} OI concentration <V v={s.concentration[k]} f={(c) => `${c[0]} (${(c[1] * 100).toFixed(1)}% of range)`} />
                {" "}change <V v={s.concentration_change[k]} f={(x) => `${x > 0 ? "+" : ""}${x.toFixed(1)} pts`} /></span>))}
            <span>IV coverage <span className="fo-num">{s.iv_coverage[0]}/{s.iv_coverage[1]}</span></span>
          </div>
          <div className="fo-overflow-x-auto">
            <table className="fo-w-full fo-text-xs fo-num">
              <thead className="fo-text-muted">
                <tr>{["OI", "ΔOI", "vol", "prem", "Δprem", "IV", "spread", "hypothesis"].map((h) => <th key={"c" + h}>CE {h}</th>)}
                  <th>strike</th>
                  {["hypothesis", "spread", "IV", "Δprem", "prem", "vol", "ΔOI", "OI"].map((h) => <th key={"p" + h}>PE {h}</th>)}</tr>
              </thead>
              <tbody>
                {strikes.map((k) => {
                  const c = at(k, "CE"), p = at(k, "PE");
                  return (
                    <tr key={k} className={!isU(s.atm_strike) && k === s.atm_strike ? "fo-bg-raised" : ""}>
                      {cells(c)}
                      <td className="fo-font-semibold fo-text-center">{k}</td>
                      {cells(p, true)}
                    </tr>);
                })}
              </tbody>
            </table>
          </div>
          <div>
            <h4 className="fo-m-0 fo-mb-3 fo-text-xs fo-uppercase fo-tracking-wider fo-text-muted">Selected contract comparison</h4>
            {isU(d.comparison) ? <p className="fo-m-0 fo-text-xs fo-text-muted">— {d.comparison.UNAVAILABLE}</p> : (
              <table className="fo-w-full fo-text-xs fo-num">
                <thead className="fo-text-muted"><tr>{["role", "strike", "prem", "IV", "delta", "theta/day", "spread", "OI", "vol",
                  "depth bid / ask (pending)", "hypothesis"].map((h) => <th key={h}>{h}</th>)}</tr></thead>
                <tbody>{d.comparison.map((r) => (
                  <tr key={r.strike} className={r.selected ? "fo-bg-raised fo-font-semibold" : ""}>
                    <td>{r.role}{r.selected ? " · selected" : ""}</td><td>{r.kind} {r.strike}</td>
                    <td><V v={r.premium} f={inr} /></td><td><V v={r.iv} f={ivp} /></td>
                    <td><V v={r.greeks} f={(g) => g.delta.toFixed(3)} /></td><td><V v={r.greeks} f={(g) => `₹${g.theta.toFixed(2)}`} /></td>
                    <td><V v={r.spread_pct} f={(x) => `${x.toFixed(2)}%`} /></td><td><V v={r.oi} f={num(0)} /></td>
                    <td><V v={r.volume_day} f={num(0)} /></td>
                    <td><V v={r.depth_bid_qty} f={num(0)} /> / <V v={r.depth_ask_qty} f={num(0)} /></td>
                    <td><Chip tone={TONE[r.hypothesis] ?? "accent"}>{r.hypothesis}</Chip></td>
                  </tr>))}</tbody>
              </table>)}
          </div>
          {d.labels.map((l) => <p key={l} className="fo-m-0 fo-text-2xs fo-text-muted">{l}</p>)}
        </div>)}
    </Panel>
  );
}

function cells(r: Row | undefined, mirror = false) {
  if (!r) return Array.from({ length: 8 }, (_, i) => <td key={i} className="fo-text-muted">·</td>);
  const tds = [
    <td key="oi"><V v={r.oi} f={num(0)} /></td>,
    <td key="doi"><V v={r.oi_change_pct} f={pct} /></td>,
    <td key="vol"><V v={r.volume_day} f={num(0)} /></td>,
    <td key="prem"><V v={r.premium} f={inr} /></td>,
    <td key="dprem"><V v={r.premium_change_pct} f={pct} /></td>,
    <td key="iv"><V v={r.iv} f={ivp} /></td>,
    <td key="spr"><V v={r.spread_pct} f={(x) => `${x.toFixed(1)}%`} /></td>,
    <td key="hyp"><Tip text={r.evidence.join(" · ")}><Chip tone={TONE[r.hypothesis] ?? "accent"}>{r.hypothesis}</Chip></Tip></td>,
  ];
  return mirror ? tds.reverse() : tds;
}
