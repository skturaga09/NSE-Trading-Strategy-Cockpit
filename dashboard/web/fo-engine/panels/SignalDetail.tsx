// E — Signal detail. Chart data are the Phase 3 1m candles of the price token as stored; an UNAVAILABLE bar is left as a
// gap (whitespace), never drawn from neighbours. Levels / zones / sweeps / structure come from Phase 5 detections.
import { useEffect, useRef } from "react";
import { ColorType, LineStyle, createChart, type IChartApi, type SeriesMarker, type Time, type UTCTimestamp } from "lightweight-charts";
import { useEnv, useSignal, type Maybe, type View } from "../api";
import type { RadarRow } from "./Radar";
import { Chip, Dir, Panel, V, inr, ist, isU, num } from "../core";
import { Kv } from "./Overview";

interface Bar { start_ns: number; end_ns: number; open: Maybe<number>; high: Maybe<number>; low: Maybe<number>; close: Maybe<number>;
  volume: Maybe<number>; vwap: Maybe<number>; completeness: string; status: string | null; oi: Maybe<number>; oi_age_s: number | null;
  oi_last_change_ns: number | null }
interface Det { id: string; type: string; timeframe: string; level: number | null; confirmed_ts: number; attrs: Record<string, number | string>; label: string }
interface Part { name: string; points: Maybe<number>; max_points: number; detail: string }
interface Factor { name: string; points: number; available_max: number; weight: number; missing: string[]; parts: Part[] }
interface Rec {
  recommendation_id: string; underlying: string; contract: Maybe<string>; direction: string; classification: string; status: string;
  setup_family: string; setup_kind: string; entry_trigger: Maybe<number>; entry_trigger_rule: string; entry_range: Maybe<number[]>;
  underlying_invalidation: Maybe<number>; t1: Maybe<number>; t2: Maybe<number>; expected_net_rr: Maybe<number | null>;
  score: { headline: { points: number; available_max: number; band: string; factors: Factor[]; missing: string[] } };
  opportunity_age: Record<string, Maybe<number> | string | string[] | null>;
  why_selected: string[]; contradicting_evidence: string[]; warnings: string[]; reasons_to_cancel: string[];
  gates: { name: string; passed: boolean; detail: string }[]; disclaimer: string;
}
interface Eval { as_of: number; classification: string | null; retest_plan: null | { zone_low: number | null; zone_high: number | null; level_type: string | null; expires_ts: number } }
interface Data { recommendation: Rec; bars: Bar[]; detections: Det[]; lifecycle: { ts: number; from_state: string | null; to_state: string; cause: string }[];
  timeline: { detected_ns: number; confirmed_ns: number; eligible_ns: Maybe<number>; first_timely_ns: Maybe<number> }; evaluations: Eval[] }

const KEY_LEVELS = ["PDH", "PDL", "PDC", "PWH", "PWL", "ORH", "ORL"];
const MARKS: Record<string, [SeriesMarker<Time>["position"], SeriesMarker<Time>["shape"], "bullish" | "bearish" | "accent"]> = {
  SWEEP_LOW: ["belowBar", "arrowUp", "bullish"], SWEEP_HIGH: ["aboveBar", "arrowDown", "bearish"],
  BOS_UP: ["belowBar", "circle", "bullish"], BOS_DOWN: ["aboveBar", "circle", "bearish"],
  CHOCH_UP: ["belowBar", "square", "accent"], CHOCH_DOWN: ["aboveBar", "square", "accent"],
  BREAKOUT_ACCEPTED: ["belowBar", "arrowUp", "accent"], BREAKDOWN_ACCEPTED: ["aboveBar", "arrowDown", "accent"],
};
const sec = (ns: number) => Math.floor(ns / 1e9) as UTCTimestamp;
const hm = (t: Time) => new Date((t as number) * 1000).toLocaleTimeString("en-GB", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false });

function token(el: HTMLElement, name: string) {
  const root = el.closest("[data-fo-engine]") as HTMLElement | null;
  return root ? getComputedStyle(root).getPropertyValue(`--fo-${name}`).trim() : "";
}

function baseChart(el: HTMLElement, height: number): IChartApi {
  return createChart(el, {
    height, autoSize: true,
    layout: { background: { type: ColorType.Solid, color: token(el, "surface") }, textColor: token(el, "muted"),
      fontFamily: token(el, "font-mono"), fontSize: 11 },
    grid: { vertLines: { color: token(el, "line") }, horzLines: { color: token(el, "line") } },
    rightPriceScale: { borderColor: token(el, "line") },
    timeScale: { borderColor: token(el, "line"), timeVisible: true, secondsVisible: false, tickMarkFormatter: hm },
    localization: { timeFormatter: (t: Time) => `${hm(t)} IST`, priceFormatter: (p: number) => (p / 100).toFixed(2) },
  });
}

function PriceChart({ d, theme }: { d: Data; theme: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const chart = baseChart(el, el.clientHeight);
    const c = (n: string) => token(el, n);
    const candles = chart.addCandlestickSeries({ upColor: c("bullish"), downColor: c("bearish"), wickUpColor: c("bullish"),
      wickDownColor: c("bearish"), borderVisible: false });
    const ok = (b: Bar) => !isU(b.open) && !isU(b.high) && !isU(b.low) && !isU(b.close);
    candles.setData(d.bars.map((b) => ok(b)
      ? { time: sec(b.start_ns), open: b.open as number, high: b.high as number, low: b.low as number, close: b.close as number }
      : { time: sec(b.start_ns) }));
    const vwap = chart.addLineSeries({ color: c("accent"), lineWidth: 1, priceLineVisible: false, lastValueVisible: false, title: "VWAP" });
    vwap.setData(d.bars.map((b) => (isU(b.vwap) ? { time: sec(b.start_ns) } : { time: sec(b.start_ns), value: b.vwap })));
    const vol = chart.addHistogramSeries({ priceScaleId: "vol", priceFormat: { type: "volume" }, color: c("unavailable"), lastValueVisible: false, priceLineVisible: false });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    vol.setData(d.bars.map((b) => (isU(b.volume) ? { time: sec(b.start_ns) } : { time: sec(b.start_ns), value: b.volume })));
    const line = (price: Maybe<number> | null, title: string, color: string, style = LineStyle.Dashed) =>
      price != null && !isU(price) && candles.createPriceLine({ price, color, lineWidth: 1, lineStyle: style, axisLabelVisible: true, title });
    const r = d.recommendation;
    line(r.entry_trigger, "entry", c("accent"), LineStyle.Solid);
    line(r.underlying_invalidation, "SL", c("bearish"), LineStyle.Solid);
    line(r.t1, "T1", c("bullish"), LineStyle.Solid);
    line(r.t2, "T2", c("bullish"));
    const latest = new Map<string, Det>();
    for (const x of d.detections) if (KEY_LEVELS.includes(x.type)) latest.set(x.type, x);
    latest.forEach((x) => line(x.level, x.type, c("muted"), LineStyle.Dotted));
    for (const z of d.detections.filter((x) => x.type === "DEMAND_ZONE" || x.type === "SUPPLY_ZONE").slice(-2)) {
      const col = c(z.type === "DEMAND_ZONE" ? "bullish" : "bearish");
      line(Number(z.attrs.low), `${z.type === "DEMAND_ZONE" ? "demand" : "supply"} ${z.timeframe} lo`, col, LineStyle.SparseDotted);
      line(Number(z.attrs.high), `hi`, col, LineStyle.SparseDotted);
    }
    const times = new Set(d.bars.map((b) => sec(b.start_ns)));
    const marks = d.detections.filter((x) => MARKS[x.type] && times.has(sec(x.confirmed_ts - 60e9)))
      .map((x) => { const [position, shape, tone] = MARKS[x.type];
        return { time: sec(x.confirmed_ts - 60e9), position, shape, color: c(tone), text: `${x.type.replace("_", " ")} ${x.timeframe}${x.label ? "*" : ""}` }; })
      .sort((a, b) => (a.time as number) - (b.time as number));
    candles.setMarkers(marks);
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [d, theme]);
  return <div ref={ref} className="fo-h-chart fo-w-full" aria-label="price, volume and VWAP chart" role="img" />;
}

function OiChart({ bars, theme }: { bars: Bar[]; theme: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const chart = baseChart(el, el.clientHeight);
    chart.applyOptions({ localization: { timeFormatter: (t: Time) => `${hm(t)} IST`, priceFormatter: (p: number) => p.toLocaleString("en-IN") } });
    const s = chart.addLineSeries({ color: token(el, "neutral"), lineWidth: 1, lineType: 1 });
    s.setData(bars.map((b) => (isU(b.oi) ? { time: sec(b.start_ns) } : { time: sec(b.start_ns), value: b.oi })));
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [bars, theme]);
  return <div ref={ref} className="fo-h-chart-sm fo-w-full" role="img" aria-label="open interest at candle close" />;
}

export function SignalDetail({ view, id, onPick }: { view: View; id: string | null; onPick?: (id: string | null) => void }) {
  const q = useSignal<Data>(id, view);
  const radar = useEnv<{ rows: RadarRow[] }>("radar", view);
  const theme = typeof document === "undefined" ? "" : document.documentElement.getAttribute("data-theme") ?? "dark";
  if (!id) return <PickList rows={radar.data?.data?.rows} onPick={onPick} />;
  const d = q.data?.data;
  const r = d?.recommendation;
  const last = d?.evaluations[d.evaluations.length - 1];
  const oa = r?.opportunity_age ?? {};
  return (
    <>
    {onPick && <button onClick={() => onPick(null)}
      className="fo-mb-4 fo-h-control fo-cursor-pointer fo-rounded-md fo-border fo-border-accent fo-bg-raised fo-px-5 fo-text-sm fo-font-semibold fo-text-accent">
      ← Back to all signals</button>}
    <Panel title={r ? `Signal · ${r.underlying}` : "Signal detail"} env={q.data} error={q.error}
      right={r && <span className="fo-flex fo-items-center fo-gap-3 fo-text-xs"><Dir d={r.direction} /><Chip tone={r.status === "ENTRY_ELIGIBLE" ? "ok" : "unavailable"}>{r.status}</Chip></span>}>
      {d && r && (
        <div className="fo-grid fo-gap-6">
          <p className="fo-m-0 fo-text-xs fo-text-muted">{r.classification} · family {r.setup_family} ({r.setup_kind}) · contract <V v={r.contract} /> · {r.disclaimer}</p>
          <PriceChart d={d} theme={theme} />
          <p className="fo-m-0 fo-text-2xs fo-text-muted">1m candles of the near-month future (Phase 3; gaps = UNAVAILABLE bars). Dotted: PDH/PDL/PDC/PWH/PWL/ORH/ORL; sparse: last demand/supply zones; markers: sweeps, BOS, CHOCH (* = HEURISTIC), accepted breakouts.</p>
          <div className="fo-grid fo-gap-5 lg:fo-grid-cols-2">
            <div>
              <h4 className="fo-m-0 fo-mb-3 fo-text-xs fo-uppercase fo-tracking-wider fo-text-muted">Open interest (candle close) and OI age</h4>
              <OiChart bars={d.bars} theme={theme} />
              <table className="fo-mt-3 fo-text-xs"><tbody>{d.bars.slice(-6).reverse().map((b) => (
                <tr key={b.end_ns} className="fo-border-b fo-border-line"><td className="fo-num fo-py-1">{ist(b.end_ns)}</td>
                  <td className="fo-py-1 fo-text-right"><V v={b.oi} f={num(0)} /></td>
                  <td className="fo-num fo-py-1 fo-text-right">{b.oi_age_s == null ? "—" : `age ${b.oi_age_s.toFixed(0)} s`}</td></tr>))}</tbody></table>
            </div>
            <div>
              <h4 className="fo-m-0 fo-mb-3 fo-text-xs fo-uppercase fo-tracking-wider fo-text-muted">Confirmation timeline</h4>
              <ol className="fo-m-0 fo-grid fo-gap-2 fo-pl-6 fo-text-sm">
                <li>detected <span className="fo-num">{ist(d.timeline.detected_ns)}</span></li>
                <li>confirmed <span className="fo-num">{ist(d.timeline.confirmed_ns)}</span></li>
                <li>first TIMELY <V v={d.timeline.first_timely_ns} f={ist} /></li>
                <li>entry-eligible <V v={d.timeline.eligible_ns} f={ist} /></li>
              </ol>
              <table className="fo-mt-3 fo-text-xs"><tbody>{d.lifecycle.map((x, i) => (
                <tr key={i} className="fo-border-b fo-border-line"><td className="fo-num fo-py-1">{ist(x.ts)}</td>
                  <td className="fo-py-1">{x.from_state ?? "—"} → <b>{x.to_state}</b></td><td className="fo-py-1 fo-text-muted">{x.cause}</td></tr>))}</tbody></table>
            </div>
          </div>
          <div>
            <h4 className="fo-m-0 fo-mb-3 fo-text-xs fo-uppercase fo-tracking-wider fo-text-muted">
              Score breakdown · <span className="fo-num">{r.score.headline.points.toFixed(1)} / {r.score.headline.available_max.toFixed(1)}</span> available ({r.score.headline.band}; research priority, not a probability)
            </h4>
            <table className="fo-text-xs"><thead><tr className="fo-text-muted"><th className="fo-text-left">factor</th><th className="fo-text-right">points</th><th className="fo-text-right">available / weight</th><th className="fo-text-left fo-pl-5">parts</th></tr></thead>
              <tbody>{r.score.headline.factors.map((f) => (
                <tr key={f.name} className="fo-border-b fo-border-line fo-align-top">
                  <td className="fo-py-2">{f.name}</td><td className="fo-num fo-py-2 fo-text-right">{num(2)(f.points)}</td>
                  <td className="fo-num fo-py-2 fo-text-right">{num(2)(f.available_max)} / {f.weight}</td>
                  <td className="fo-py-2 fo-pl-5">{f.parts.map((p) => <div key={p.name}><V v={p.points} f={num(2)} /> / <span className="fo-num">{num(2)(p.max_points)}</span> — <span className="fo-text-muted">{p.detail}</span></div>)}</td>
                </tr>))}</tbody></table>
          </div>
          <div className="fo-grid fo-grid-cols-2 fo-gap-4 lg:fo-grid-cols-4">
            <Kv k="Extension (ATR)"><V v={oa.extension_atr as Maybe<number>} f={num(2)} /></Kv>
            <Kv k="Obstacle distance (ATR)"><V v={oa.obstacle_distance_atr as Maybe<number>} f={num(2)} /></Kv>
            <Kv k="Current R:R (gross)"><V v={oa.current_rr as Maybe<number>} f={num(2)} /></Kv>
            <Kv k="Retest zone">{last?.retest_plan && last.retest_plan.zone_low != null
              ? <span className="fo-num">{inr(last.retest_plan.zone_low)}–{inr(last.retest_plan.zone_high ?? 0)}</span>
              : <V v={{ UNAVAILABLE: last?.retest_plan ? `no valid retest level (${last.retest_plan.level_type ?? "NO_VALID_LEVEL"})` : "no retest plan at the latest evaluation" }} />}</Kv>
          </div>
          <div className="fo-grid fo-gap-5 lg:fo-grid-cols-2">
            <List title="Evidence" items={r.why_selected} />
            <List title="Contradictions and warnings" items={[...r.contradicting_evidence, ...r.warnings]} empty="none recorded" />
            <div>
              <h4 className="fo-m-0 fo-mb-3 fo-text-xs fo-uppercase fo-tracking-wider fo-text-muted">Entry criteria</h4>
              <p className="fo-m-0 fo-text-sm">trigger <V v={r.entry_trigger} f={inr} /> — {r.entry_trigger_rule}</p>
              <p className="fo-m-0 fo-text-sm">executable range {isU(r.entry_range) ? <V v={r.entry_range} /> : <span className="fo-num">{r.entry_range.map(inr).join(" – ")}</span>}</p>
              <p className="fo-m-0 fo-text-sm">expected net R:R <V v={r.expected_net_rr ?? { UNAVAILABLE: "not computed" }} f={num(2)} /></p>
              <ul className="fo-m-0 fo-mt-3 fo-pl-6 fo-text-xs">{r.gates.map((g) => (
                <li key={g.name} className={g.passed ? "fo-text-muted" : "fo-text-bearish"}>{g.passed ? "✓" : "✗"} {g.name}: {g.detail}</li>))}</ul>
            </div>
            <div>
              <h4 className="fo-m-0 fo-mb-3 fo-text-xs fo-uppercase fo-tracking-wider fo-text-muted">Exit criteria</h4>
              <p className="fo-m-0 fo-text-sm">stop <V v={r.underlying_invalidation} f={inr} /> · T1 <V v={r.t1} f={inr} /> · T2 <V v={r.t2} f={inr} /></p>
              <List title="" items={r.reasons_to_cancel} />
            </div>
          </div>
        </div>)}
    </Panel>
    </>
  );
}

function List({ title, items, empty = "—" }: { title: string; items: string[]; empty?: string }) {
  return (
    <div>
      {title && <h4 className="fo-m-0 fo-mb-3 fo-text-xs fo-uppercase fo-tracking-wider fo-text-muted">{title}</h4>}
      {items.length === 0 ? <p className="fo-m-0 fo-text-xs fo-text-muted">{empty}</p> :
        <ul className="fo-m-0 fo-pl-6 fo-text-sm">{items.map((x, i) => <li key={i}>{x}</li>)}</ul>}
    </div>
  );
}


// No row picked yet: list the session's recommendations (rejected included, best score first) to open one here.
function PickList({ rows, onPick }: { rows?: RadarRow[]; onPick?: (id: string) => void }) {
  const sorted = [...(rows ?? [])].sort((a, b) => b.score - a.score);
  return (
    <Panel title="Signal detail" env={null}>
      <p className="fo-m-0 fo-mb-4 fo-text-muted">
        {rows === undefined ? "Loading the session's signals…" : rows.length === 0 ? "No signal recorded for this session yet." :
          `No signal picked. ${rows.length} signal${rows.length === 1 ? "" : "s"} this session — click one to open it (best score first; REJECTED ones are not tradable).`}
      </p>
      {sorted.length > 0 && (
        <div className="fo-overflow-x-auto"><table className="fo-text-sm">
          <thead><tr className="fo-bg-raised fo-text-2xs fo-uppercase fo-tracking-wider fo-text-muted">
            {["Time", "Symbol", "Direction", "Signal", "Score", "Status"].map((h) => <th key={h} className="fo-px-4 fo-py-3 fo-text-left">{h}</th>)}</tr></thead>
          <tbody>{sorted.map((r) => (
            <tr key={r.recommendation_id} className="fo-cursor-pointer fo-border-b fo-border-line hover:fo-bg-raised"
              onClick={() => onPick?.(r.recommendation_id)}>
              <td className="fo-num fo-px-4 fo-py-2">{ist(r.as_of)}</td>
              <td className="fo-px-4 fo-py-2 fo-font-semibold">
                <button className="fo-cursor-pointer fo-border-0 fo-bg-transparent fo-p-0 fo-font-semibold fo-text-ink"
                  onClick={(e) => { e.stopPropagation(); onPick?.(r.recommendation_id); }}>{r.symbol}</button></td>
              <td className="fo-px-4 fo-py-2"><Dir d={r.direction} /></td>
              <td className="fo-px-4 fo-py-2 fo-text-xs">{r.signal}</td>
              <td className="fo-num fo-px-4 fo-py-2">{num()(r.score)} / {num()(r.score_available_max)}</td>
              <td className="fo-px-4 fo-py-2"><Chip tone={r.status === "REJECTED" ? "unavailable" : "ok"}>{r.status}</Chip></td>
            </tr>))}</tbody></table></div>)}
    </Panel>
  );
}
