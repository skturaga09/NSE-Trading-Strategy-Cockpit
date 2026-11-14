// B — Opportunity Radar. Rows are Phase 8 recommendations exactly as stored; sorting / filtering is presentation only.
import { useMemo, useState } from "react";
import { useEnv, type Maybe, type View } from "../api";
import { Chip, Dir, Panel, Tip, V, inr, isU, num, pct } from "../core";

export interface RadarRow {
  recommendation_id: string; signal_id: string; as_of: number; symbol: string; contract: Maybe<string>; direction: string;
  signal: string; family: string; kind: string; oi_pct: Maybe<number>; price_pct: Maybe<number>; rvol: Maybe<number>;
  score: number; score_available_max: number; band: string; timeliness: Maybe<string>; entry: Maybe<number>;
  sl: Maybe<number>; target: Maybe<number>; status: string; lifecycle_state: Maybe<string>;
  rejected_reasons: string[]; risk_reasons: string[]; warnings: string[]; labels: string[];
  verdict: { action: Action; why: string[] };
}
type Action = "BUY" | "WAIT" | "CHECK" | "AVOID";
interface TrackDay { day: string; trades: number; wins: number; net_inr: number; calls_net_inr: number; puts_net_inr: number }
const RANK: Record<Action, number> = { BUY: 0, CHECK: 1, WAIT: 2, AVOID: 3 };
const TONE = { BUY: "ok", CHECK: "warning", WAIT: "accent", AVOID: "stale" } as const;
const rupees = (x: number) => `${x < 0 ? "−" : ""}₹${Math.abs(x).toLocaleString("en-IN")}`;

type Key = "call" | "symbol" | "contract" | "direction" | "signal" | "oi_pct" | "price_pct" | "rvol" | "score" | "timeliness" | "entry" | "sl" | "target" | "status";
const COLS: [Key, string][] = [["call", "Call"], ["symbol", "Symbol"], ["contract", "Option"], ["direction", "Direction"], ["signal", "Signal"], ["oi_pct", "OI %"],
  ["price_pct", "Price %"], ["rvol", "RVOL"], ["score", "Score"], ["timeliness", "Timeliness"], ["entry", "Entry"],
  ["sl", "SL"], ["target", "Target"], ["status", "Status"]];
const NUMERIC = new Set<Key>(["oi_pct", "price_pct", "rvol", "score", "entry", "sl", "target"]);

const sortVal = (r: RadarRow, k: Key) => {
  if (k === "call") return RANK[r.verdict.action];
  const v = r[k]; return isU(v) ? null : v;
};

export function Radar({ view, onOpen }: { view: View; onOpen: (id: string) => void }) {
  const q = useEnv<{ rows: RadarRow[]; feature_window_min: number; track_record?: TrackDay[] }>("radar", view);
  const [sort, setSort] = useState<{ k: Key; asc: boolean }>({ k: "call", asc: true });
  const [showRejected, setShowRejected] = useState(true);
  const [dir, setDir] = useState<"ALL" | "LONG" | "SHORT">("ALL");
  const [text, setText] = useState("");
  const rows = useMemo(() => {
    const all = q.data?.data?.rows ?? [];
    const f = all.filter((r) => (showRejected || r.verdict.action !== "AVOID") && (dir === "ALL" || r.direction === dir)
      && (!text || r.symbol.includes(text.toUpperCase())));
    return [...f].sort((a, b) => {
      const x = sortVal(a, sort.k), y = sortVal(b, sort.k);
      if (x === y) return 0;
      if (x === null) return 1;                       // UNAVAILABLE sorts last either way
      if (y === null) return -1;
      return (x < y ? -1 : 1) * (sort.asc ? 1 : -1);
    });
  }, [q.data, sort, showRejected, dir, text]);
  const total = q.data?.data?.rows.length ?? 0;
  const rejected = q.data?.data?.rows.filter((r) => r.verdict.action === "AVOID").length ?? 0;
  const calls = q.data?.data?.rows.filter((r) => r.verdict.action !== "AVOID").length ?? 0;
  const track = q.data?.data?.track_record ?? [];
  const fw = q.data?.data?.feature_window_min;

  return (
    <Panel title="Opportunity radar" env={q.data} error={q.error} right={
      <div className="fo-flex fo-items-center fo-gap-4 fo-text-xs">
        <input aria-label="filter symbol" placeholder="symbol" value={text} onChange={(e) => setText(e.target.value)}
          size={9} className="fo-h-control fo-rounded-md fo-border fo-border-line fo-bg-raised fo-px-4" />
        <select aria-label="direction" value={dir} onChange={(e) => setDir(e.target.value as typeof dir)}
          className="fo-h-control fo-rounded-md fo-border fo-border-line fo-bg-raised fo-px-3">
          <option>ALL</option><option>LONG</option><option>SHORT</option>
        </select>
        <label className="fo-flex fo-cursor-pointer fo-items-center fo-gap-2">
          <input type="checkbox" checked={showRejected} onChange={(e) => setShowRejected(e.target.checked)} />
          show AVOID ({rejected})
        </label>
      </div>}>
      <div role="note" className="fo-mb-4 fo-rounded-md fo-border fo-border-line fo-bg-raised fo-px-4 fo-py-3 fo-text-sm">
        <div className="fo-font-semibold">
          {calls === 0 ? "No option to buy right now." : `${calls} option idea${calls === 1 ? "" : "s"} to look at.`}{" "}
          <span className="fo-font-normal fo-text-muted">
            BUY = every check passed · CHECK = setup passed, look at the option's bid/ask yourself · WAIT = let price come back · AVOID = reason given.
          </span>
        </div>
        {track.length > 0 && (
          <div className="fo-mt-2 fo-text-xs">
            Engine's real-price record (every signal bought as one option lot, Kite prices, after charges):{" "}
            {track.map((t) => (
              <span key={t.day} className="fo-mr-4 fo-whitespace-nowrap">
                {t.day}: <b className={t.net_inr < 0 ? "fo-text-bearish" : "fo-text-bullish"}>{rupees(t.net_inr)}</b>{" "}
                ({t.wins}/{t.trades} won; calls {rupees(t.calls_net_inr)}, puts {rupees(t.puts_net_inr)})
              </span>))}
            {track.every((t) => t.net_inr < 0) && <span className="fo-text-bearish"> No proven edge yet: size small or paper-trade.</span>}
          </div>)}
      </div>
      <p className="fo-m-0 fo-mb-4 fo-text-xs fo-text-muted">
        {rows.length} shown of {total} · OI / Price / RVOL over {fw ?? "—"} min on the near-month future ·
        Score = research priority points with the maximum available from the inputs present, not a probability.
      </p>
      <div className="fo-overflow-x-auto">
        <table className="fo-text-sm">
          <thead>
            <tr className="fo-bg-raised fo-text-2xs fo-uppercase fo-tracking-wider fo-text-muted">
              {COLS.map(([k, label]) => (
                <th key={k} scope="col" aria-sort={sort.k === k ? (sort.asc ? "ascending" : "descending") : "none"}
                  className={`fo-whitespace-nowrap fo-px-4 fo-py-3 ${NUMERIC.has(k) ? "fo-text-right" : "fo-text-left"}`}>
                  <button onClick={() => setSort((s) => ({ k, asc: s.k === k ? !s.asc : false }))}
                    className="fo-cursor-pointer fo-border-0 fo-bg-transparent fo-p-0 fo-uppercase fo-tracking-wider">
                    {label}{sort.k === k ? (sort.asc ? " ↑" : " ↓") : ""}
                  </button>
                </th>))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr><td colSpan={COLS.length} className="fo-px-4 fo-py-6 fo-text-center fo-text-muted">
                {total === 0 ? "No recommendation at or before the view time."
                  : `No option to buy. ${rejected} marked AVOID — tick "show AVOID" to see each one and why.`}
              </td></tr>)}
            {rows.map((r) => (
              <tr key={r.recommendation_id} onClick={() => onOpen(r.recommendation_id)}
                className="fo-cursor-pointer fo-border-b fo-border-line hover:fo-bg-raised">
                <td className="fo-px-4 fo-py-3" style={{ minWidth: "16rem" }}>
                  <Chip tone={TONE[r.verdict.action]}>{r.verdict.action}</Chip>
                  <div className="fo-mt-1 fo-text-2xs fo-text-muted">{r.verdict.why[0]}</div>
                </td>
                <td className="fo-px-4 fo-py-3 fo-font-semibold">{r.symbol}</td>
                <td className="fo-px-4 fo-py-3 fo-whitespace-nowrap fo-text-xs"><V v={r.contract} /></td>
                <td className="fo-px-4 fo-py-3 fo-whitespace-nowrap"><Dir d={r.direction} /></td>
                <td className="fo-px-4 fo-py-3 fo-text-xs">{r.signal}</td>
                <td className="fo-px-4 fo-py-3 fo-text-right"><V v={r.oi_pct} f={pct} /></td>
                <td className="fo-px-4 fo-py-3 fo-text-right"><V v={r.price_pct} f={pct} /></td>
                <td className="fo-px-4 fo-py-3 fo-text-right"><V v={r.rvol} f={num(2)} /></td>
                <td className="fo-px-4 fo-py-3 fo-text-right fo-whitespace-nowrap">
                  <span className="fo-num">{r.score.toFixed(1)}</span><span className="fo-num fo-text-muted"> / {r.score_available_max.toFixed(1)}</span>
                </td>
                <td className="fo-px-4 fo-py-3"><Timeliness t={r.timeliness} /></td>
                <td className="fo-px-4 fo-py-3 fo-text-right"><V v={r.entry} f={inr} /></td>
                <td className="fo-px-4 fo-py-3 fo-text-right"><V v={r.sl} f={inr} /></td>
                <td className="fo-px-4 fo-py-3 fo-text-right"><V v={r.target} f={inr} /></td>
                <td className="fo-px-4 fo-py-3 fo-whitespace-nowrap">
                  {r.status === "REJECTED"
                    ? <Tip text={r.rejected_reasons.join("\n") || "rejected"}><span><Chip tone="unavailable">rejected</Chip> <span className="fo-text-2xs fo-text-muted">{r.rejected_reasons.length} gate{r.rejected_reasons.length === 1 ? "" : "s"}</span></span></Tip>
                    : <Chip tone={r.status === "ENTRY_ELIGIBLE" ? "ok" : "warning"}>{r.status.replace(/_/g, " ").toLowerCase()}</Chip>}
                </td>
              </tr>))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

function Timeliness({ t }: { t: Maybe<string> }) {
  if (isU(t)) return <V v={t} />;
  const tone = t === "TIMELY" ? "ok" : t === "RETEST" ? "accent" : t === "EXHAUSTED" ? "stale" : t === "LATE" ? "warning" : "unavailable";
  return <Chip tone={tone}>{t}</Chip>;
}
