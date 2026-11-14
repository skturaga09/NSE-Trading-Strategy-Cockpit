// G — Performance analytics. SIMULATED and ACTUAL are separate tabs, each fetched on its own (/performance?ledger=…);
// nothing in this module adds one ledger's numbers to the other's.
import { useState } from "react";
import { usePerformance, type Maybe } from "../api";
import { Chip, LedgerBadge, Panel, V, isU, num, rupees } from "../core";
import { Kv } from "./Overview";
import { Pnl } from "./Trades";

type Ledger = "SIMULATED" | "ACTUAL";
interface Group { trades: number; net_inr: number; win_rate: number; expectancy_inr: number }
export interface Perf {
  ledger: Ledger; label: Ledger; trades: number; win_rate: Maybe<number>; expectancy_inr: Maybe<number>; profit_factor: Maybe<number>;
  max_drawdown_inr: Maybe<number>; net_inr: Maybe<number>; gross_inr: Maybe<number>; charges_inr: Maybe<number>; slippage_inr: Maybe<number>;
  daily: { date: string; net_inr: number }[]; cumulative: { ts_ns: number; cumulative_net_inr: number }[];
  by: Record<string, Maybe<Record<string, Group>>>;
}

const BY = [["family", "Strategy (family)"], ["time_of_day", "Time of day (entry)"], ["underlying", "Instrument"],
  ["score_band", "Score band"], ["timeliness", "Timeliness class"], ["regime", "Regime"]] as const;

export function Performance() {
  const [tab, setTab] = useState<Ledger>("SIMULATED");
  return (
    <div className="fo-grid fo-gap-4">
      <div role="tablist" aria-label="ledger" className="fo-flex fo-gap-2">
        {(["SIMULATED", "ACTUAL"] as const).map((l) => (
          <button key={l} role="tab" aria-selected={tab === l} onClick={() => setTab(l)}
            className={`fo-h-control fo-cursor-pointer fo-rounded-md fo-border fo-px-5 fo-text-xs ${tab === l ? "fo-border-accent fo-bg-raised" : "fo-border-line fo-bg-transparent fo-text-muted"}`}>
            <LedgerBadge ledger={l} />
          </button>))}
      </div>
      <LedgerPerformance key={tab} ledger={tab} />
    </div>
  );
}

export function LedgerPerformance({ ledger }: { ledger: Ledger }) {
  const q = usePerformance<Perf>(ledger);
  const d = q.data?.data;
  return (
    <section role="tabpanel" data-ledger={ledger}>
      <Panel title={`Performance · ${ledger}`} error={q.error} right={<LedgerBadge ledger={ledger} />}
        env={q.data ? { panel: "performance", mode: "LIVE", now_ns: q.data.now_ns, status: q.data.status, reason: q.data.reason,
          provenance: { source: "ledger.sqlite (Phase 9)", observed_ns: null, received_ns: null, processed_ns: null, tz: "Asia/Kolkata" },
          age_s: null, stale_after_s: null, config_version: q.data.config_version, data: d ?? null } : null}>
        {d && (
          <div className="fo-grid fo-gap-5">
            {d.trades === 0 && <p className="fo-m-0 fo-text-sm fo-text-muted">— {q.data?.reason}. Metrics stay UNAVAILABLE until a trade closes; they are not shown as zero.</p>}
            <div className="fo-grid fo-grid-cols-2 fo-gap-4 lg:fo-grid-cols-4">
              <Kv k="Closed trades"><span className="fo-num">{d.trades}</span></Kv>
              <Kv k="Win rate"><V v={d.win_rate} f={(x) => `${(x * 100).toFixed(1)}%`} /></Kv>
              <Kv k="Expectancy / trade (net)"><V v={d.expectancy_inr} f={rupees} /></Kv>
              <Kv k="Profit factor"><V v={d.profit_factor} f={num(2)} /></Kv>
              <Kv k="Net P&L"><Pnl v={d.net_inr} /></Kv>
              <Kv k="Max drawdown"><V v={d.max_drawdown_inr} f={rupees} /></Kv>
              <Kv k="Charges (est.)"><V v={d.charges_inr} f={rupees} /></Kv>
              <Kv k="Slippage"><V v={d.slippage_inr} f={rupees} /></Kv>
            </div>
            {d.daily.length > 0 && (
              <table className="fo-text-xs"><thead><tr className="fo-text-muted"><th className="fo-text-left">date</th><th className="fo-text-right">net</th></tr></thead>
                <tbody>{d.daily.map((x) => <tr key={x.date} className="fo-border-b fo-border-line"><td className="fo-num">{x.date}</td><td className="fo-text-right"><Pnl v={x.net_inr} /></td></tr>)}</tbody></table>)}
            {d.cumulative.length > 0 && <p className="fo-m-0 fo-text-xs">cumulative net after the last close: <Pnl v={d.cumulative[d.cumulative.length - 1].cumulative_net_inr} /></p>}
            <div className="fo-grid fo-gap-4 lg:fo-grid-cols-3">
              {BY.map(([k, label]) => {
                const g = d.by[k];
                return (
                  <div key={k} className="fo-rounded-md fo-border fo-border-line fo-p-4">
                    <div className="fo-mb-2 fo-text-2xs fo-uppercase fo-tracking-wider fo-text-muted">{label}</div>
                    {g === undefined ? <V v={{ UNAVAILABLE: `no closed ${ledger} trades` }} /> : isU(g) ? <V v={g} /> : (
                      <table className="fo-text-xs"><tbody>{Object.entries(g).map(([name, x]) => (
                        <tr key={name}><td>{name}</td><td className="fo-num fo-text-right">{x.trades}</td><td className="fo-text-right"><Pnl v={x.net_inr} /></td></tr>))}</tbody></table>)}
                  </div>);
              })}
            </div>
            <div><Chip tone="accent">{ledger} only</Chip></div>
          </div>)}
      </Panel>
    </section>
  );
}
