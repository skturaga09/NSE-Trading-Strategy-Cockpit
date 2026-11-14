// System health: feed status, ticks/sec, stale instruments, gaps, allocator usage. Live view also listens to the SSE stream.
import { useEffect, useState } from "react";
import { useEnv, type Envelope, type Maybe, type View } from "../api";
import { Chip, Panel, V, ist, isU, num } from "../core";
import { Kv } from "./Overview";

interface Gap { kind: string; start_ns: number; end_ns: number; reason: string; count: number | null }
interface Data {
  connections: Record<string, string> | null; ticks_per_s: number | null; queue: { depth: number; max: number };
  dropped_total: number | null; gaps_today: number | null; degraded: Record<string, boolean> | null; instruments: number;
  stale_instruments: number; stale_sample: string[]; gaps: Maybe<Gap[]>;
  allocator: Maybe<{ plans: number; drops: number; last_usage: Record<string, number> }>;
  latency_s: Maybe<{ median: number; p90: number; p99: number; note: string }>;
  staleness: Maybe<{ incidents_recovered: number; still_stale_at_end: number; median_duration_s: number }>;
}

export function Health({ view }: { view: View }) {
  const q = useEnv<Data>("health", view, {}, 30_000);
  const [stream, setStream] = useState<Envelope<Data> | null>(null);
  useEffect(() => {
    setStream(null);
    if (view.asOf != null) return;                       // a replay is a fixed snapshot: no stream
    const es = new EventSource(`/api/engine/health/stream?date=${encodeURIComponent(view.date)}`);
    es.onmessage = (m) => setStream(JSON.parse(m.data));
    return () => es.close();
  }, [view.date, view.asOf]);
  const env = stream ?? q.data;
  const d = env?.data;
  return (
    <Panel title="System health" env={env} error={q.error} right={stream ? <Chip tone="ok">stream</Chip> : null}>
      {d && "instruments" in d && (
        <div className="fo-grid fo-gap-5">
          <div className="fo-grid fo-grid-cols-2 fo-gap-4 lg:fo-grid-cols-4">
            <Kv k="Feed connections">{d.connections ? Object.entries(d.connections).map(([c, s]) => `#${c} ${s}`).join(" · ") : "—"}</Kv>
            <Kv k="Ticks / sec"><V v={d.ticks_per_s} f={num(1)} /></Kv>
            <Kv k="Stale instruments" hint="no tick within quality.stale_price_s at the view time">
              <span className="fo-num">{d.stale_instruments}</span> <span className="fo-text-xs fo-text-muted">of {d.instruments}</span></Kv>
            <Kv k="Queue / dropped"><span className="fo-num">{d.queue.depth} / {d.queue.max} · {d.dropped_total ?? "—"}</span></Kv>
          </div>
          <div className="fo-grid fo-gap-5 lg:fo-grid-cols-2">
            <div>
              <h4 className="fo-m-0 fo-mb-3 fo-text-xs fo-uppercase fo-tracking-wider fo-text-muted">Gaps</h4>
              {isU(d.gaps) ? <V v={d.gaps} /> : (d.gaps.length === 0 ? <p className="fo-m-0 fo-text-xs fo-text-muted">none</p> :
                <table className="fo-text-xs"><tbody>{d.gaps.map((g, i) => (
                  <tr key={i} className="fo-border-b fo-border-line"><td className="fo-py-2"><Chip tone="warning">{g.kind}</Chip></td>
                    <td className="fo-num fo-py-2">{ist(g.start_ns)} → {ist(g.end_ns)}</td><td className="fo-py-2 fo-text-muted">{g.reason}</td></tr>))}
                </tbody></table>)}
            </div>
            <div>
              <h4 className="fo-m-0 fo-mb-3 fo-text-xs fo-uppercase fo-tracking-wider fo-text-muted">Subscription allocator</h4>
              {isU(d.allocator) ? <V v={d.allocator} /> : (
                <p className="fo-m-0 fo-text-sm fo-num">{Object.entries(d.allocator.last_usage).map(([k, x]) => `${k} ${x}`).join(" · ")}</p>)}
              <h4 className="fo-m-0 fo-mb-3 fo-mt-5 fo-text-xs fo-uppercase fo-tracking-wider fo-text-muted">Latency (exchange → receive)</h4>
              {isU(d.latency_s) ? <V v={d.latency_s} /> :
                <p className="fo-m-0 fo-text-sm fo-num">median {d.latency_s.median} s · p90 {d.latency_s.p90} s · p99 {d.latency_s.p99} s</p>}
              {d.stale_sample.length > 0 && <p className="fo-m-0 fo-mt-5 fo-text-2xs fo-text-muted">stale now (sample): {d.stale_sample.join(", ")}</p>}
            </div>
          </div>
        </div>)}
    </Panel>
  );
}
