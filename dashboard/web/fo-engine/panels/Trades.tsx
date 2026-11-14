// F — Active trades, one table per ledger. SIMULATED and ACTUAL are never in one table and never summed.
import { useEnv, type Maybe, type View } from "../api";
import { Chip, LedgerBadge, Panel, Tip, V, inr, ist, isU, rupees } from "../core";

type Ledger = "SIMULATED" | "ACTUAL";
interface Alert { as_of: number; decision: string; rule_id: string; message: string }
interface Trade {
  id: string; underlying: string; kind: string; side: string; qty: number; lots: number; open_qty: number; entry_price: number;
  entry_ns: number; t1: number | null; underlying_stop: number; stop: number; decision: Maybe<string>; rule_id: string | null;
  pnl_gross_inr: Maybe<number>; pnl_net_inr: Maybe<number>; warnings: string[]; thesis: Maybe<string>; alerts: Alert[];
  mark: { bid: Maybe<number>; ask: Maybe<number>; observed_ns: number | null }; mark_label: string;
}

const DECISION_TONE: Record<string, "ok" | "warning" | "stale" | "unavailable" | "accent"> = {
  HOLD: "ok", TIGHTEN_STOP: "accent", PARTIAL_EXIT_CANDIDATE: "warning", EXIT_REQUIRED: "stale", DATA_UNAVAILABLE: "unavailable" };

export function Trades({ view }: { view: View }) {
  const q = useEnv<Record<Ledger, Trade[]>>("trades", view, {}, 5_000);
  return (
    <Panel title="Active trades" env={q.data} error={q.error}>
      {q.data?.data && (["SIMULATED", "ACTUAL"] as const).map((led) => <LedgerTable key={led} ledger={led} rows={q.data!.data![led]} />)}
    </Panel>
  );
}

function LedgerTable({ ledger, rows }: { ledger: Ledger; rows: Trade[] }) {
  return (
    <section data-ledger={ledger} className={`fo-mb-6 fo-rounded-md fo-p-5 ${ledger === "SIMULATED" ? "fo-sim-chip" : "fo-border fo-border-actual"}`}>
      <div className="fo-mb-4 fo-flex fo-items-center fo-gap-4"><LedgerBadge ledger={ledger} />
        <span className="fo-text-xs fo-text-muted">{rows.length} trade{rows.length === 1 ? "" : "s"} · totals are per ledger only</span></div>
      {rows.length === 0 ? <p className="fo-m-0 fo-text-sm fo-text-muted">No {ledger} trade for this session.</p> : (
        <div className="fo-overflow-x-auto"><table className="fo-text-sm">
          <thead><tr className="fo-bg-raised fo-text-2xs fo-uppercase fo-tracking-wider fo-text-muted">
            {["Symbol", "Contract", "Entry", "Qty / lots", "Current (bid / ask)", "P&L gross", "P&L net (est.)", "Stop", "Target", "Decision", "Thesis", "Alerts"]
              .map((h) => <th key={h} className="fo-whitespace-nowrap fo-px-4 fo-py-3 fo-text-left">{h}</th>)}</tr></thead>
          <tbody>{rows.map((t) => (
            <tr key={t.id} className="fo-border-b fo-border-line fo-align-top">
              <td className="fo-px-4 fo-py-3 fo-font-semibold">{t.underlying}</td>
              <td className="fo-px-4 fo-py-3 fo-text-xs">{t.kind} {t.side}</td>
              <td className="fo-px-4 fo-py-3"><span className="fo-num">{inr(t.entry_price)}</span><div className="fo-text-2xs fo-text-muted">{ist(t.entry_ns)}</div></td>
              <td className="fo-num fo-px-4 fo-py-3">{t.open_qty}/{t.qty} · {t.lots}</td>
              <td className="fo-px-4 fo-py-3"><Tip text={t.mark_label}><span><V v={t.mark.bid} f={inr} /> / <V v={t.mark.ask} f={inr} /></span></Tip></td>
              <td className="fo-px-4 fo-py-3"><Pnl v={t.pnl_gross_inr} /></td>
              <td className="fo-px-4 fo-py-3"><Pnl v={t.pnl_net_inr} /></td>
              <td className="fo-num fo-px-4 fo-py-3">{inr(t.stop)}{t.stop !== t.underlying_stop && <div className="fo-text-2xs fo-text-muted">from {inr(t.underlying_stop)}</div>}</td>
              <td className="fo-px-4 fo-py-3">{t.t1 == null ? <V v={{ UNAVAILABLE: "no T1" }} /> : <span className="fo-num">{inr(t.t1)}</span>}</td>
              <td className="fo-px-4 fo-py-3">{isU(t.decision) ? <V v={t.decision} /> :
                <Tip text={`${t.rule_id}\n${t.warnings.join("\n")}`}><span><Chip tone={DECISION_TONE[t.decision] ?? "accent"}>{t.decision}</Chip></span></Tip>}</td>
              <td className="fo-px-4 fo-py-3 fo-text-xs"><V v={t.thesis} /></td>
              <td className="fo-px-4 fo-py-3 fo-text-xs">
                <details><summary className="fo-cursor-pointer">{t.alerts.length}</summary>
                  <ul className="fo-m-0 fo-pl-5">{t.alerts.map((a, i) => <li key={i}><span className="fo-num">{ist(a.as_of)}</span> {a.message}</li>)}</ul></details>
              </td>
            </tr>))}</tbody></table></div>)}
    </section>
  );
}

function Pnl({ v }: { v: Maybe<number> }) {
  if (isU(v)) return <V v={v} />;
  return <span className={`fo-num ${v > 0 ? "fo-text-bullish" : v < 0 ? "fo-text-bearish" : ""}`}>{v > 0 ? "▲ " : v < 0 ? "▼ " : ""}{rupees(v)}</span>;
}
export { Pnl };
