// A — Market overview: index trend/structure, breadth, index-future OI, VWAP relation, India VIX, positioning summary.
import { useEnv, type Maybe, type View } from "../api";
import { Dir, Panel, Tip, V, inr, ist, isU, num } from "../core";

interface Data {
  index: string;
  market_context: Maybe<{ nifty_trend: Maybe<number>; breadth: Maybe<number>; breadth_n: number; index_positioning: Maybe<string>; as_of: number }>;
  close: Maybe<number>; vwap: Maybe<number>; vwap_relation: Maybe<string>;
  index_futures_oi: Maybe<{ end_ns: number; oi: Maybe<number>; oi_age_s: number | null }[]>;
  india_vix: Maybe<number>;
  positioning_summary: { view: string; mark_ns: number | null; counts: Record<string, number>; label: string };
}

export function Kv({ k, children, hint }: { k: string; children: React.ReactNode; hint?: string }) {
  return (
    <div className="fo-flex fo-flex-col fo-gap-1 fo-rounded-md fo-border fo-border-line fo-bg-raised fo-px-5 fo-py-4">
      <span className="fo-text-2xs fo-uppercase fo-tracking-wider fo-text-muted">{hint ? <Tip text={hint}><span>{k} ⓘ</span></Tip> : k}</span>
      <span className="fo-text-lg">{children}</span>
    </div>
  );
}

export function Overview({ view }: { view: View }) {
  const q = useEnv<Data>("overview", view);
  const d = q.data?.data;
  const mc = d && !isU(d.market_context) ? d.market_context : null;
  const trend: Maybe<number> | undefined = mc ? mc.nifty_trend : d && isU(d.market_context) ? d.market_context : undefined;
  const oi = d && !isU(d.index_futures_oi) ? d.index_futures_oi : [];
  return (
    <Panel title="Market overview" env={q.data} error={q.error}>
      {d && (
        <div className="fo-grid fo-gap-5">
          <div className="fo-grid fo-grid-cols-2 fo-gap-4 lg:fo-grid-cols-4">
            <Kv k={`${d.index} trend (15m structure)`} hint="latest Phase 5 BOS / CHOCH of the index near-month future">
              {trend !== undefined && !isU(trend) ? <Dir d={trend > 0 ? "PRICE_UP" : "PRICE_DOWN"} /> : <V v={trend} />}
            </Kv>
            <Kv k="Breadth (share above VWAP)" hint="share of universe near-month futures whose last usable 1m close is above session VWAP">
              {mc ? <><V v={mc.breadth} f={(x) => `${(x * 100).toFixed(0)}%`} /> <span className="fo-text-xs fo-text-muted">of {mc.breadth_n}</span></> : <V v={isU(d.market_context) ? d.market_context : null} />}
            </Kv>
            <Kv k={`${d.index} future vs VWAP`}>
              <V v={d.vwap_relation} /> <span className="fo-text-xs fo-text-muted"><V v={d.close} f={inr} /> / <V v={d.vwap} f={inr} /></span>
            </Kv>
            <Kv k="India VIX"><V v={d.india_vix} f={num(2)} /></Kv>
          </div>
          <div className="fo-grid fo-gap-5 lg:fo-grid-cols-2">
            <div>
              <h4 className="fo-m-0 fo-mb-3 fo-text-xs fo-uppercase fo-tracking-wider fo-text-muted">
                {d.index} index-future positioning hypothesis: {mc ? <V v={mc.index_positioning} /> : "—"}
              </h4>
              <h4 className="fo-m-0 fo-mb-3 fo-text-xs fo-uppercase fo-tracking-wider fo-text-muted">
                Universe positioning summary ({d.positioning_summary.view}{d.positioning_summary.mark_ns ? `, ${ist(d.positioning_summary.mark_ns)}` : ""})
              </h4>
              <table className="fo-text-sm"><tbody>
                {Object.entries(d.positioning_summary.counts).map(([k, n]) => (
                  <tr key={k} className="fo-border-b fo-border-line">
                    <td className="fo-py-2">{k === "UNAVAILABLE" ? <span className="fo-text-unavailable">not evaluated (UNAVAILABLE)</span> : k}</td>
                    <td className="fo-num fo-py-2 fo-text-right">{n}</td>
                  </tr>))}
                {Object.keys(d.positioning_summary.counts).length === 0 && <tr><td className="fo-text-muted">—</td></tr>}
              </tbody></table>
              <p className="fo-m-0 fo-mt-3 fo-text-2xs fo-text-muted">{d.positioning_summary.label}</p>
            </div>
            <div>
              <h4 className="fo-m-0 fo-mb-3 fo-text-xs fo-uppercase fo-tracking-wider fo-text-muted">{d.index} near-month future OI (candle close, with OI age)</h4>
              <div className="fo-max-h-scroll fo-overflow-y-auto">
                <table className="fo-text-xs"><thead><tr className="fo-text-muted"><th className="fo-text-left">time</th><th className="fo-text-right">OI</th><th className="fo-text-right">OI age</th></tr></thead>
                  <tbody>{oi.slice(-24).reverse().map((r) => (
                    <tr key={r.end_ns} className="fo-border-b fo-border-line">
                      <td className="fo-num fo-py-1">{ist(r.end_ns)}</td>
                      <td className="fo-py-1 fo-text-right"><V v={r.oi} f={num(0)} /></td>
                      <td className="fo-num fo-py-1 fo-text-right">{r.oi_age_s == null ? "—" : `${r.oi_age_s.toFixed(0)} s`}</td>
                    </tr>))}</tbody></table>
              </div>
              {isU(d.index_futures_oi) && <V v={d.index_futures_oi} />}
            </div>
          </div>
        </div>)}
    </Panel>
  );
}
