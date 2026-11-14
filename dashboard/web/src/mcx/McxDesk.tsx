import { useCallback, useEffect, useState, type ReactNode } from "react";

/* MCX COMMODITY OPTIONS DESK — a separate workspace (dashboard/mcx_desk.py, /api/mcx-desk). Paper only: the page
   reads what the server's minute loop computed; nothing here sends an order. */

/* eslint-disable @typescript-eslint/no-explicit-any */
type Any = any;
type Tab = "desk" | "history" | "validation" | "settings";
const TABS: [Tab, string][] = [["desk", "Desk"], ["history", "History & P&L"], ["validation", "Validation"], ["settings", "Risk & settings"]];

const inr = (x: number | null | undefined) =>
  x == null ? "—" : `${x < 0 ? "−" : ""}₹${Math.abs(Math.round(x)).toLocaleString("en-IN")}`;
const px = (x: number | null | undefined) => (x == null ? "—" : x.toLocaleString("en-IN", { maximumFractionDigits: 2 }));
const tone = (x: number | null | undefined) => (x == null ? "text-muted" : x >= 0 ? "text-[var(--green)]" : "text-[var(--red)]");
const hm = (iso?: string | null) => (iso ? `${iso.slice(5, 10)} ${iso.slice(11, 16)}` : "—");
const ago = (iso?: string | null, now?: string) => {
  if (!iso || !now) return null;
  return Math.round((new Date(now).getTime() - new Date(iso).getTime()) / 1000);
};
const dir = (d?: number) => (d === 1 ? "UP" : d === -1 ? "DOWN" : "—");

function Badge({ v }: { v: string }) {
  const c: Record<string, string> = {
    UP: "bg-[var(--green)]/15 text-[var(--green)]", DOWN: "bg-[var(--red)]/15 text-[var(--red)]",
    WAIT: "bg-gold/15 text-gold", HOLD: "bg-cyan/15 text-cyan", TRAIL: "bg-gold/15 text-gold",
    EXIT: "bg-[var(--red)]/20 text-[var(--red)]", OPEN: "bg-[var(--green)]/15 text-[var(--green)]",
  };
  return <span className={`rounded px-1.5 py-0.5 font-mono text-[10px] font-bold ${c[v] ?? "bg-raised text-muted"}`}>{v}</span>;
}

function Panel({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return (
    <section className="panel space-y-3 rounded-lg p-4">
      <h2 className="font-display text-sm font-bold text-ink">
        {title} {note && <span className="font-mono text-[10px] font-normal text-muted">— {note}</span>}
      </h2>
      {children}
    </section>
  );
}

function Stat({ label, value, cls = "text-ink", sub }: { label: string; value: ReactNode; cls?: string; sub?: ReactNode }) {
  return (
    <div className="min-w-[8.5rem] rounded border border-line bg-raised/40 px-3 py-2">
      <div className="font-mono text-[9px] uppercase tracking-wider text-muted">{label}</div>
      <div className={`font-mono text-sm font-semibold ${cls}`}>{value}</div>
      {sub && <div className="font-mono text-[10px] text-muted">{sub}</div>}
    </div>
  );
}

const Th = ({ children, r }: { children?: ReactNode; r?: boolean }) => (
  <th className={`pb-1.5 pr-3 font-normal text-muted ${r ? "text-right" : "text-left"}`}>{children}</th>
);
const table = "w-full font-mono text-[11px]";
const tr = "border-t border-line/60 align-top";

// ---------------------------------------------------------------------------- Desk
function StatusStrip({ d }: { d: Any }) {
  const st = d.state ?? {};
  const s = d.settings;
  const tickAge = ago(st.last_tick, d.now);
  const kiteDown = (st.errors ?? []).includes("Kite not connected");
  const f = st.funds ?? {};
  const free = f.available == null ? null : f.available - (f.stock_paper_committed ?? 0) - (f.mcx_paper_committed ?? 0);
  const sess = d.session;
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        <Stat label="Kite" value={kiteDown ? "disconnected" : st.last_tick ? "connected" : "no tick yet"}
          cls={kiteDown ? "text-[var(--red)]" : "text-[var(--green)]"}
          sub={tickAge == null ? "loop not run" : `last check ${tickAge}s ago${tickAge > 150 ? " · STALE" : ""}`} />
        <Stat label="MCX session" value={`${sess.state}${sess.is_open ? ` · ${sess.half.toLowerCase()}` : ""}`}
          cls={sess.is_open ? "text-[var(--green)]" : "text-muted"}
          sub={`09:00–${sess.close}${sess.minutes_to_close != null ? ` · ${sess.minutes_to_close} min left` : ""}`} />
        <Stat label="Last 5-min candle" value={hm(st.bar)} sub={`Supertrend(${s.st_period}, ${s.st_mult})`} />
        <Stat label="Account free (shared)" value={inr(free)} cls={free != null && free > 0 ? "text-ink" : "text-[var(--red)]"}
          sub={f.available == null ? "Kite margins unreadable" : `Kite ${inr(f.available)} − stocks paper ${inr(f.stock_paper_committed)} − MCX paper ${inr(f.mcx_paper_committed)}`} />
        <Stat label="Day P&L / limit" value={<span className={tone(st.day_pnl)}>{inr(st.day_pnl)}</span>}
          sub={st.day_locked ? "LOCKED: no entries today" : `limit −${inr(s.daily_loss_limit)}`} />
      </div>
      <div className="space-y-1 font-mono text-[10px]">
        {f.commodity_enabled === false && (
          <p className="text-[var(--red)]">⚠ The commodity segment is NOT enabled on this Kite account: real MCX orders are impossible until you enable it (Kite → Profile → Segments). Paper trading still runs.</p>)}
        {!sess.holidays_verified && <p className="text-gold">⚠ MCX holiday list not verified (config/mcx_holidays.json): every weekday is treated as a trading day.</p>}
        {(st.errors ?? []).filter((e: string) => e !== "Kite not connected").map((e: string) => <p key={e} className="text-[var(--red)]">{e}</p>)}
      </div>
    </div>
  );
}

function SignalTable({ d }: { d: Any }) {
  const st = d.state ?? {};
  const roots: string[] = d.settings.roots;
  return (
    <Panel title="Watchlist & signals" note="direction = last completed 15-min candle, trigger = completed 5-min candle, both on the future under the option">
      <div className="overflow-x-auto">
        <table className={table}>
          <thead><tr><Th>Commodity</Th><Th>Analysis future</Th><Th r>Price</Th><Th>15m</Th><Th>5m</Th><Th>Signal</Th><Th>Option (1 ITM)</Th><Th r>Bid / ask</Th><Th r>1 lot</Th><Th>Entry check</Th></tr></thead>
          <tbody>
            {roots.map((r) => {
              const c = st.contracts?.[r] ?? {};
              const sg = c.future ? st.signals?.[c.future] : null;
              const fq = c.future ? st.quotes?.[c.future] : null;
              const opt = st.picks?.[r];
              const oq = opt ? st.quotes?.[opt] : null;
              const g = st.gates?.[r];
              return (
                <tr key={r} className={tr}>
                  <td className="py-2 pr-3 font-semibold text-ink">{r}<div className="text-[10px] font-normal text-muted">×{d.multipliers[r]} per lot</div></td>
                  <td className="pr-3 text-muted">{c.future ?? "—"}<div className="text-[10px]">opt exp {c.option_expiry ?? "—"} → fut {c.future_expiry ?? "—"} · map {c.mapping_confidence ?? "?"}</div></td>
                  <td className="pr-3 text-right text-ink">{px(fq?.ltp ?? sg?.close)}<div className="text-[10px] text-muted">{fq?.age_s != null ? `${Math.round(fq.age_s)}s old` : ""}</div></td>
                  <td className="pr-3"><Badge v={dir(sg?.dir15)} /><div className="text-[10px] text-muted">line {px(sg?.line15)}</div></td>
                  <td className="pr-3"><Badge v={dir(sg?.dir5)} /><div className="text-[10px] text-muted">line {px(sg?.line5)}</div></td>
                  <td className="pr-3"><Badge v={sg?.signal ?? "—"} /><div className="text-[10px] text-muted">{sg ? `was ${sg.prev_signal ?? "—"} · ${sg.regime.toLowerCase()}` : "no data"}</div></td>
                  <td className="pr-3 text-ink">{opt ?? <span className="text-muted">{sg?.signal === "WAIT" ? "none: WAIT" : "—"}</span>}</td>
                  <td className="pr-3 text-right text-muted">{oq ? `${px(oq.bid)} / ${px(oq.ask)}` : "—"}<div className="text-[10px]">{oq?.spread_pct != null ? `spread ${oq.spread_pct}%` : ""}</div></td>
                  <td className="pr-3 text-right text-ink">{g ? inr(g.cost) : "—"}</td>
                  <td className="max-w-[18rem] text-[10px]">
                    {!g ? <span className="text-muted">—</span> : g.blocks.length === 0
                      ? <span className="text-[var(--green)]">passes: buys at the next 5-min candle while both agree</span>
                      : g.blocks.map((b: string) => <div key={b} className="text-gold">✗ {b}</div>)}
                    {g?.real_funds && <div className="text-muted">ⓘ paper only — {g.real_funds}</div>}
                  </td>
                </tr>);
            })}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

function GuideCells({ g }: { g: Any }) {
  if (!g) return <td colSpan={5} className="text-muted">waiting for the next check</td>;
  return (
    <>
      <td className="pr-3"><Badge v={g.action} /><div className="max-w-[16rem] text-[10px] text-muted">{g.reason}</div></td>
      <td className="pr-3 text-right text-ink">{px(g.premium)}{g.no_bid && <div className="text-[10px] text-[var(--red)]">no bid</div>}</td>
      <td className={`pr-3 text-right ${tone(g.est_pnl)}`}>{inr(g.est_pnl)}<div className="text-[10px] text-muted">after charges</div></td>
      <td className="pr-3 text-right text-muted">prem {px(g.stop_premium)}<div className="text-[10px]">fut line {px(g.stop_future)}</div></td>
      <td className="text-muted">{hm(g.at)}</td>
    </>
  );
}

function Positions({ d }: { d: Any }) {
  const paper: Any[] = d.paper_open;
  const real: Any[] = d.state?.broker ?? [];
  const head = <tr><Th>Option</Th><Th>Size · policy</Th><Th r>Entry</Th><Th>Guidance</Th><Th r>Bid now</Th><Th r>Est. P&L</Th><Th r>Stop</Th><Th>At</Th></tr>;
  return (
    <div className="grid gap-4">
      <Panel title="📝 Paper positions" note="filled at the live ask, valued at the live bid; exits run automatically on paper">
        {paper.length === 0 ? <p className="font-mono text-[11px] text-muted">No open paper position.</p> : (
          <div className="overflow-x-auto"><table className={table}><thead>{head}</thead><tbody>
            {paper.map((p) => (
              <tr key={p.id} className={tr}>
                <td className="py-2 pr-3 font-semibold text-ink">{p.option}<div className="text-[10px] font-normal text-muted">on {p.future}</div></td>
                <td className="pr-3 text-muted">{p.lots} lot × {p.multiplier}<div className="text-[10px]">{p.policy} · out by {p.exit_by}</div>
                  {p.real_funds && p.real_funds !== "ok" && <div className="text-[10px] text-gold">real account couldn't pay</div>}</td>
                <td className="pr-3 text-right text-muted">{px(p.entry)}<div className="text-[10px]">{hm(p.entry_at)}</div></td>
                <GuideCells g={p.last} />
              </tr>))}
          </tbody></table></div>)}
      </Panel>
      <Panel title="🏦 Real Kite positions (MCX)" note="read from your broker account — guidance only, the desk never trades these">
        {real.length === 0 ? <p className="font-mono text-[11px] text-muted">No open MCX position in Kite.</p> : (
          <div className="overflow-x-auto"><table className={table}><thead>{head}</thead><tbody>
            {real.map((p) => (
              <tr key={p.option} className={`${tr} bg-cyan/5`}>
                <td className="py-2 pr-3 font-semibold text-ink"><span className="mr-1 rounded bg-cyan/20 px-1 text-[9px] text-cyan">REAL</span>{p.option}
                  {p.warnings?.map((w: string) => <div key={w} className="text-[10px] font-normal text-gold">{w}</div>)}</td>
                <td className="pr-3 text-muted">{p.lots} lot × {p.multiplier}<div className="text-[10px]">{p.product} · out by {p.exit_by ?? "—"}</div></td>
                <td className="pr-3 text-right text-muted">{px(p.avg)}<div className="text-[10px]">Kite P&L {inr(p.kite_pnl)}</div></td>
                <GuideCells g={p.guide} />
              </tr>))}
          </tbody></table></div>)}
      </Panel>
    </div>
  );
}

function Alerts({ d }: { d: Any }) {
  const a: Any[] = d.alerts ?? [];
  return (
    <Panel title="🔔 Alerts" note="MCX desk only; also pushed to your phone channel with an 'MCX ·' prefix">
      {a.length === 0 ? <p className="font-mono text-[11px] text-muted">No alert yet.</p> :
        <div className="space-y-1 font-mono text-[11px]">{a.slice(0, 15).map((x, i) => (
          <div key={i} className="flex gap-3"><span className="text-muted">{hm(x.at)}</span><Badge v={x.kind === "ALIGNED" ? "OPEN" : x.kind === "CONFLICT" ? "WAIT" : x.kind} />
            <span className="text-ink">{x.title}</span><span className="text-muted">{x.body}</span></div>))}</div>}
    </Panel>
  );
}

// ---------------------------------------------------------------------------- History / validation / settings
function History({ d }: { d: Any }) {
  const h: Any[] = d.history;
  return (
    <div className="grid gap-4">
      <Panel title="Daily P&L" note="paper, net of estimated charges">
        {d.daily.length === 0 ? <p className="font-mono text-[11px] text-muted">No closed paper trade yet.</p> :
          <table className={table}><thead><tr><Th>Day</Th><Th r>Trades</Th><Th r>Charges</Th><Th r>Net</Th></tr></thead><tbody>
            {d.daily.map((x: Any) => <tr key={x.day} className={tr}><td className="py-1.5 pr-3 text-ink">{x.day}</td><td className="pr-3 text-right text-muted">{x.trades}</td>
              <td className="pr-3 text-right text-muted">{inr(x.costs)}</td><td className={`pr-3 text-right ${tone(x.net)}`}>{inr(x.net)}</td></tr>)}
          </tbody></table>}
      </Panel>
      <Panel title="Trade journal" note="every paper trade with the prices it really got">
        {h.length === 0 ? <p className="font-mono text-[11px] text-muted">Empty.</p> : <div className="overflow-x-auto">
          <table className={table}><thead><tr><Th>In → out</Th><Th>Option</Th><Th>Context</Th><Th r>Ask in → bid out</Th><Th r>Charges</Th><Th r>Net</Th><Th>Exit reason</Th></tr></thead><tbody>
            {h.map((c) => <tr key={c.id} className={tr}>
              <td className="py-1.5 pr-3 text-muted">{hm(c.entry_at)} → {hm(c.exit_at)}<div className="text-[10px]">{c.hold_min} min</div></td>
              <td className="pr-3 text-ink">{c.option}<div className="text-[10px] text-muted">{c.lots}×{c.multiplier} · {c.policy}{c.real_funds && c.real_funds !== "ok" ? " · real account short" : ""}</div></td>
              <td className="pr-3 text-[10px] text-muted">{c.half.toLowerCase()} · {c.regime.toLowerCase()} · {c.dte}d to expiry</td>
              <td className="pr-3 text-right text-muted">{px(c.entry)} → {px(c.exit)}</td>
              <td className="pr-3 text-right text-muted">{inr(c.costs)}</td>
              <td className={`pr-3 text-right ${tone(c.net)}`}>{inr(c.net)}</td>
              <td className="text-[10px] text-muted">{c.exit_why}</td></tr>)}
          </tbody></table></div>}
      </Panel>
    </div>
  );
}

function StatsTable({ rows, label }: { rows: Any[]; label: string }) {
  if (!rows?.length) return <p className="font-mono text-[11px] text-muted">No closed trades yet.</p>;
  return (
    <table className={table}><thead><tr><Th>{label}</Th><Th r>Trades</Th><Th r>Won</Th><Th r>Net</Th><Th r>Avg</Th><Th r>Spread paid</Th><Th r>Avg hold</Th><Th r>Trend exits</Th></tr></thead><tbody>
      {rows.map((r) => <tr key={r.key} className={tr}><td className="py-1.5 pr-3 text-ink">{r.key}</td><td className="pr-3 text-right text-muted">{r.trades}</td>
        <td className="pr-3 text-right text-muted">{r.wins}</td><td className={`pr-3 text-right ${tone(r.net)}`}>{inr(r.net)}</td>
        <td className={`pr-3 text-right ${tone(r.avg)}`}>{inr(r.avg)}</td><td className="pr-3 text-right text-muted">{inr(r.spread_paid)}</td>
        <td className="pr-3 text-right text-muted">{r.avg_hold_min ?? "—"} min</td><td className="pr-3 text-right text-muted">{r.trend_exits}</td></tr>)}
    </tbody></table>
  );
}

function Validation() {
  const [v, setV] = useState<Any>(null);
  useEffect(() => { fetch("/api/mcx-desk/validation").then((r) => r.json()).then(setV).catch(() => {}); }, []);
  if (!v) return <p className="font-mono text-[11px] text-muted">Loading…</p>;
  const e = v.exit_rule;
  return (
    <div className="grid gap-4">
      <p className="font-mono text-[11px] text-gold">{v.note} A right futures direction can still lose on the option: premium also moves with volatility and time decay, which is why only real bid/ask fills count here.</p>
      <Panel title="Does the 5-minute exit close trades too often?" note="same entries; one book exits on the 5-min Supertrend, the other only on the 15-min">
        <table className={table}><thead><tr><Th>Exit rule</Th><Th r>Trades</Th><Th r>Net</Th><Th r>Avg</Th><Th r>Avg hold</Th><Th r>Trend exits</Th></tr></thead><tbody>
          {(["5m", "15m"] as const).map((k) => <tr key={k} className={tr}><td className="py-1.5 pr-3 text-ink">{k} Supertrend</td>
            <td className="pr-3 text-right text-muted">{e[k].trades}</td><td className={`pr-3 text-right ${tone(e[k].net)}`}>{inr(e[k].net)}</td>
            <td className={`pr-3 text-right ${tone(e[k].avg)}`}>{inr(e[k].avg)}</td><td className="pr-3 text-right text-muted">{e[k].avg_hold_min ?? "—"} min</td>
            <td className="pr-3 text-right text-muted">{e[k].trend_exits}</td></tr>)}
        </tbody></table>
        {e.alt_still_open > 0 && <p className="font-mono text-[10px] text-muted">{e.alt_still_open} trade(s) still held by the 15-min book (not counted until closed).</p>}
      </Panel>
      <Panel title="Per commodity"><StatsTable rows={v.by_root} label="Commodity" /></Panel>
      <Panel title="Per commodity × session × regime × expiry distance"><StatsTable rows={v.by_bucket} label="Bucket" /></Panel>
      <Panel title="Per exit reason"><StatsTable rows={v.by_exit} label="Exit" /></Panel>
    </div>
  );
}

const NUM: [string, string][] = [
  ["capital", "MCX desk budget ₹"], ["max_premium_per_trade", "Max premium per trade ₹"], ["daily_loss_limit", "Daily loss limit ₹"],
  ["max_open_positions", "Max open positions"], ["max_lots_per_position", "Lots per position"], ["max_entries_per_day", "Max entries per day"],
  ["premium_stop_pct", "Premium stop %"], ["trail_arm_pct", "Trail arms at +%"], ["trail_giveback_pct", "Trail give-back %"],
  ["intraday_exit_before_close_min", "Intraday: exit N min before close"], ["no_entry_before_close_min", "No entry in last N min"],
  ["min_option_dte", "Min option days to expiry"], ["exit_before_expiry_days", "Exit N days before option expiry"],
  ["st_period", "Supertrend ATR period"], ["st_mult", "Supertrend multiplier"],
];

function Settings({ d, reload }: { d: Any; reload: () => void }) {
  const [f, setF] = useState<Any>(d.settings);
  const [msg, setMsg] = useState("");
  const save = async () => {
    const r = await fetch("/api/mcx-desk/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(f) });
    const j = await r.json();
    setMsg(r.ok ? "Saved (MCX desk only)." : `Not saved: ${j.detail}`);
    if (r.ok) { setF(j); reload(); }
  };
  const input = "w-full rounded border border-line bg-raised px-2 py-1 font-mono text-[12px] text-ink";
  return (
    <Panel title="Risk & settings" note="stored in data/mcx_desk/settings.json — the stock dashboard's limits are separate and unaffected">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {NUM.map(([k, label]) => (
          <label key={k} className="space-y-1 font-mono text-[10px] text-muted">{label}
            <input type="number" step="any" className={input} value={f[k]} onChange={(e) => setF({ ...f, [k]: Number(e.target.value) })} />
          </label>))}
        <label className="space-y-1 font-mono text-[10px] text-muted">Exit policy for NEW positions (fixed at entry)
          <select className={input} value={f.exit_policy} onChange={(e) => setF({ ...f, exit_policy: e.target.value })}>
            <option value="INTRADAY">INTRADAY — square off before the session close</option>
            <option value="OVERNIGHT">OVERNIGHT — may hold across sessions</option>
          </select>
        </label>
        <fieldset className="space-y-1 font-mono text-[10px] text-muted">Commodities
          <div className="flex flex-wrap gap-3">{Object.keys(d.multipliers).map((r) => (
            <label key={r} className="flex items-center gap-1 text-ink"><input type="checkbox" checked={f.roots.includes(r)}
              onChange={(e) => setF({ ...f, roots: e.target.checked ? [...f.roots, r] : f.roots.filter((x: string) => x !== r) })} />{r}</label>))}</div>
        </fieldset>
        <fieldset className="space-y-1 font-mono text-[10px] text-muted">Switches
          {([["auto_paper_entries", "Auto paper entries"], ["alerts", "Phone alerts"]] as const).map(([k, label]) => (
            <label key={k} className="flex items-center gap-1 text-ink"><input type="checkbox" checked={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.checked })} />{label}</label>))}
        </fieldset>
      </div>
      <div className="flex items-center gap-3">
        <button onClick={save} className="rounded bg-gold px-3 py-1.5 font-mono text-[12px] font-bold text-black">Save</button>
        <span className="font-mono text-[11px] text-muted">{msg}</span>
      </div>
      <p className="font-mono text-[10px] text-muted">Mode: <b className="text-ink">PAPER</b> (the only mode — live MCX order routing is not built). Max spread % per commodity: {Object.entries(f.max_spread_pct).map(([k, v]) => `${k} ${v}%`).join(" · ")}. Charges assumed: ₹20/order, CTT 0.05% sell, MCX 0.0418%, stamp 0.003% buy, GST 18%.</p>
    </Panel>
  );
}

// ---------------------------------------------------------------------------- shell
export function McxDesk() {
  const [tab, setTab] = useState<Tab>(() => (TABS.find(([t]) => `#${t}` === location.hash)?.[0] ?? "desk"));
  const [d, setD] = useState<Any>(null);
  const [err, setErr] = useState("");
  const load = useCallback(() => {
    fetch(`/api/mcx-desk?_t=${Date.now()}`).then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((j) => { setD(j); setErr(""); }).catch((e) => setErr(`desk API unreachable (${e})`));
  }, []);
  useEffect(() => { load(); const id = setInterval(load, 5000); return () => clearInterval(id); }, [load]);
  useEffect(() => {
    const on = () => setTab(TABS.find(([t]) => `#${t}` === location.hash)?.[0] ?? "desk");
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const go = (t: Tab) => { setTab(t); history.replaceState(null, "", `#${t}`); };
  return (
    <div className="mx-auto max-w-7xl space-y-4 px-4 py-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-display text-xl font-bold text-ink">MCX Commodity Options Desk <span className="ml-2 rounded bg-gold px-2 py-0.5 align-middle font-mono text-[11px] text-black">PAPER</span></h1>
          <p className="font-mono text-[10px] text-muted">Gold · Silver · Crude Oil · Natural Gas options, signals on the underlying future. A screen and a paper book, not advice.</p>
        </div>
        <a href="/" className="font-mono text-[11px] text-cyan hover:underline">← Stocks & F&O dashboard</a>
      </header>
      <nav className="flex gap-1 border-b border-line" role="tablist">
        {TABS.map(([t, label]) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => go(t)}
            className={`px-3 py-2 font-mono text-[12px] ${tab === t ? "border-b-2 border-gold text-gold" : "text-muted hover:text-ink"}`}>{label}</button>))}
      </nav>
      {err && <p className="font-mono text-[11px] text-[var(--red)]">{err}</p>}
      {!d ? <p className="font-mono text-[11px] text-muted">Loading…</p> : (
        <>
          {tab === "desk" && <div className="grid gap-4"><StatusStrip d={d} /><SignalTable d={d} /><Positions d={d} /><Alerts d={d} /></div>}
          {tab === "history" && <History d={d} />}
          {tab === "validation" && <Validation />}
          {tab === "settings" && <Settings d={d} reload={load} />}
        </>)}
    </div>
  );
}
