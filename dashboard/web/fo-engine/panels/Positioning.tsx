// C — Positioning map: the four price × OI quadrants across the universe at a scrubbed time, residual or raw view.
// Labels are positioning hypotheses from price and OI changes, not who traded.
import { useEffect, useState } from "react";
import { useEnv, type Maybe, type View } from "../api";
import { Chip, Panel, Tip, ist, isU, pct } from "../core";

interface Cell { underlying: string; hypothesis: Maybe<string>; price_axis: Maybe<string>; oi_axis: Maybe<string>;
  suppressed: string | null; price_chg_pct: Maybe<number>; oi_chg_pct: Maybe<number>; rvol: Maybe<number> }
interface Data { view: "primary" | "raw"; marks: number[]; mark_ns: number | null; cells: Cell[];
  suspected: { underlying: string; label: string; ts: number; detail?: string }[]; disclaimer: string }

const QUADS: [string, string, string, string][] = [   // hypothesis, title, price, oi
  ["LONG_BUILDUP", "Long buildup", "▲ price", "▲ OI"], ["SHORT_COVERING", "Short covering", "▲ price", "▼ OI"],
  ["SHORT_BUILDUP", "Short buildup", "▼ price", "▲ OI"], ["LONG_UNWINDING", "Long unwinding", "▼ price", "▼ OI"]];
const TONE: Record<string, string> = { LONG_BUILDUP: "fo-border-bullish", SHORT_COVERING: "fo-border-bullish",
  SHORT_BUILDUP: "fo-border-bearish", LONG_UNWINDING: "fo-border-bearish" };

export function Positioning({ view }: { view: View }) {
  const [mode, setMode] = useState<"primary" | "raw">("primary");
  const [mark, setMark] = useState<number | null>(null);
  useEffect(() => setMark(null), [view.date, view.asOf]);
  const q = useEnv<Data>("positioning", view, { view: mode, mark });
  const d = q.data?.data;
  const cells = d?.cells ?? [];
  const by = (h: string) => cells.filter((c) => c.hypothesis === h);
  const other = cells.filter((c) => isU(c.hypothesis) || !QUADS.some(([h]) => h === c.hypothesis));
  const unavail = other.filter((c) => isU(c.hypothesis));
  const reasons = Object.entries(unavail.reduce<Record<string, number>>((a, c) => {
    const r = isU(c.hypothesis) ? c.hypothesis.UNAVAILABLE : ""; a[r] = (a[r] ?? 0) + 1; return a; }, {}));
  const idx = d && d.mark_ns != null ? d.marks.indexOf(d.mark_ns) : -1;

  return (
    <Panel title="Positioning map" env={q.data} error={q.error} right={
      <div role="group" aria-label="view" className="fo-flex fo-gap-1 fo-text-xs">
        {(["primary", "raw"] as const).map((m) => (
          <button key={m} onClick={() => setMode(m)} aria-pressed={mode === m}
            className={`fo-h-control fo-cursor-pointer fo-rounded-md fo-border fo-px-4 ${mode === m ? "fo-border-accent fo-text-accent fo-bg-raised" : "fo-border-line fo-bg-transparent fo-text-muted"}`}>
            {m === "primary" ? "residual" : "raw"}
          </button>))}
      </div>}>
      {d && (
        <div className="fo-grid fo-gap-5">
          <label className="fo-flex fo-items-center fo-gap-4 fo-text-xs">
            <span className="fo-text-muted">history</span>
            <input aria-label="history scrubber" type="range" min={0} max={Math.max(0, d.marks.length - 1)} step={1}
              value={Math.max(0, idx)} onChange={(e) => setMark(d.marks[Number(e.target.value)])} className="fo-flex-1" disabled={!d.marks.length} />
            <span className="fo-num">{d.mark_ns ? `${ist(d.mark_ns)} IST` : "—"}</span>
            <span className="fo-text-muted">{d.marks.length} marks · {mode === "primary" ? "residual (index-beta adjusted)" : "raw"} view</span>
          </label>
          <div className="fo-grid fo-grid-cols-2 fo-gap-4">
            {QUADS.map(([h, title, p, o]) => (
              <div key={h} className={`fo-rounded-md fo-border fo-bg-raised fo-p-5 ${TONE[h]}`}>
                <div className="fo-mb-3 fo-flex fo-items-baseline fo-gap-4">
                  <span className="fo-font-semibold">{title}</span>
                  <span className="fo-text-xs fo-text-muted">{p} · {o}</span>
                  <span className="fo-num fo-ml-auto fo-text-xs">{by(h).length}</span>
                </div>
                <div className="fo-flex fo-flex-wrap fo-gap-2">
                  {by(h).map((c) => (
                    <Tip key={c.underlying} text={`price ${fmt(c.price_chg_pct)} · OI ${fmt(c.oi_chg_pct)} · RVOL ${fmt(c.rvol, false)}${c.suppressed ? ` · suppressed: ${c.suppressed}` : ""}`}>
                      <span className="fo-rounded-sm fo-border fo-border-line fo-bg-surface fo-px-3 fo-text-xs">{c.underlying}</span>
                    </Tip>))}
                  {by(h).length === 0 && <span className="fo-text-xs fo-text-muted">none</span>}
                </div>
              </div>))}
          </div>
          <div className="fo-rounded-md fo-border fo-border-dashed fo-border-unavailable fo-p-5">
            <div className="fo-mb-3 fo-flex fo-gap-4"><span className="fo-font-semibold fo-text-unavailable">Not evaluated / neutral</span>
              <span className="fo-num fo-ml-auto fo-text-xs">{other.length}</span></div>
            {reasons.map(([r, n]) => <p key={r} className="fo-m-0 fo-text-xs"><span className="fo-num">{n}</span> × <span className="fo-text-muted">{r}</span></p>)}
            {other.filter((c) => !isU(c.hypothesis)).length > 0 &&
              <p className="fo-m-0 fo-text-xs">{other.filter((c) => !isU(c.hypothesis)).length} evaluated with no single quadrant (NEUTRAL_OR_MIXED)</p>}
          </div>
          <div>
            <h4 className="fo-m-0 fo-mb-3 fo-text-xs fo-uppercase fo-tracking-wider fo-text-muted">Suspected accumulation / distribution (to this mark)</h4>
            {d.suspected.length === 0 ? <p className="fo-m-0 fo-text-xs fo-text-muted">none observed</p> :
              d.suspected.map((s, i) => <p key={i} className="fo-m-0 fo-text-xs"><Chip tone="warning">{s.label}</Chip> {s.underlying} <span className="fo-num">{ist(s.ts)}</span></p>)}
          </div>
          <p className="fo-m-0 fo-text-2xs fo-text-muted">{d.disclaimer}</p>
        </div>)}
    </Panel>
  );
}

function fmt(v: Maybe<number>, asPct = true) {
  return isU(v) ? `— (${v.UNAVAILABLE})` : asPct ? pct(v) : v.toFixed(2);
}
