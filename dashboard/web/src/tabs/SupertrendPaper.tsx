import { useEffect, useState } from "react";

/* LIVE PAPER TRADING of the Supertrend rules (dashboard/supertrend_paper.py): the orders auto mode WOULD send,
   filled on paper at live prices, exits by your rules, net P&L after charges. Nothing is sent to Kite. */

interface Pos { option: string; underlying?: string; qty: number; entry: number; entry_at: string; ltp: number; peak?: number;
  stock?: number | null; line?: number | null; plan?: string; action?: string; checked?: string }   // plan: the minute job's last exit check
interface Closed extends Pos { exit: number; exit_at: string; exit_why: string; net: number; costs: number }
interface Order { at: string; tradingsymbol: string; transaction_type: string; quantity: number; price: number }
interface Book { start: number; cash: number; open: Pos[]; closed: Closed[] }
interface Paper extends Book { orders: Order[]; shadow?: { open: Pos[]; closed: Closed[] }; strong?: Book; rules?: Book;
  live?: { at: string | null; px: Record<string, number | null>; error?: string } }

const inr = (x: number) => `${x < 0 ? "−" : ""}₹${Math.abs(Math.round(x)).toLocaleString("en-IN")}`;
const hm = (iso: string) => `${iso.slice(5, 10)} ${iso.slice(11, 16)}`;
const NOLIMITS_FROM = "2026-11-20T10:08";       // the main book has run without the two loss rules since then
const tone = (x: number) => (x >= 0 ? "text-[var(--green)]" : "text-[var(--red)]");

export function SupertrendPaper() {
  const [p, setP] = useState<Paper | null>(null);
  const [which, setWhich] = useState<"main" | "rules">("main");     // whose trades the table lists
  useEffect(() => {
    const load = () => fetch(`/api/supertrend/paper?_t=${Date.now()}`).then((r) => r.json()).then(setP).catch(() => {});
    void load();
    const id = setInterval(load, 5000);           // prices: one Kite call per 5 s at most (server cache)
    return () => clearInterval(id);
  }, []);
  if (!p) return null;
  const px = (x: Pos) => p.live?.px[`NFO:${x.option}`] ?? x.ltp;           // live price, else the last minute check's
  const stockPx = (x: Pos) => (x.underlying ? p.live?.px[`NSE:${x.underlying}`] : null) ?? x.stock;
  const mtm = p.open.reduce((a, x) => a + x.qty * px(x), 0);
  const balance = p.cash + mtm;
  const realised = p.closed.reduce((a, c) => a + c.net, 0);
  const wins = p.closed.filter((c) => c.net > 0).length;
  // shadow book: same buys, sold only when a 5-min candle closes against the trade
  const key = (x: Pos) => x.option + x.entry_at;
  const shClosed = new Map((p.shadow?.closed ?? []).map((c) => [key(c), c]));
  const shOpen = new Set((p.shadow?.open ?? []).map(key));
  const both = p.closed.filter((c) => shClosed.has(key(c)));
  const touchNet = both.reduce((a, c) => a + c.net, 0);
  const closeNet = both.reduce((a, c) => a + shClosed.get(key(c))!.net, 0);
  // strong-candle test book (own ₹1L): compared with the main book's trades bought since the test's first buy
  const s = p.strong;
  const since = s ? [...s.open, ...s.closed].map((x) => x.entry_at).sort()[0] : undefined;
  const sum = (b: { open: Pos[]; closed: Closed[] }, from: string) => {
    const c = b.closed.filter((x) => x.entry_at >= from);
    const o = b.open.filter((x) => x.entry_at >= from);
    return { n: c.length, won: c.filter((x) => x.net > 0).length, booked: c.reduce((a, x) => a + x.net, 0),
             open: o.length, mtm: o.reduce((a, x) => a + (x.ltp - x.entry) * x.qty, 0) };
  };
  // rules book (own ₹1L, history from 13 Nov): same signals WITH the live day loss budget and 2-losses rule
  const n = p.rules;
  const nSince = n ? [...n.open, ...n.closed].map((x) => x.entry_at).sort()[0] : undefined;
  const b = which === "rules" && n ? n : p;
  const line = (r: ReturnType<typeof sum>) => <>{r.n} closed, {r.won} won, booked <span className={tone(r.booked)}>{inr(r.booked)}</span>{r.open > 0 && <> · {r.open} open <span className={tone(r.mtm)}>{inr(r.mtm)}</span></>}</>;
  return (
    <div className="panel space-y-3 rounded-lg p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-display text-base font-bold text-ink">📝 Paper trading <span className="font-mono text-[10px] font-normal text-muted">— your signals with NO day loss budget and NO 2-losses stop (since 20 Nov 10:08), filled on paper at live prices. Nothing goes to Kite.</span></h2>
        <span className="font-mono text-[11px] text-muted">
          balance <span className="text-ink">{inr(balance)}</span> (<span className={tone(balance - p.start)}>{inr(balance - p.start)}</span> on {inr(p.start)}) ·
          booked <span className={tone(realised)}>{inr(realised)}</span> · {p.closed.length} trades, {wins} won
        </span>
      </div>
      <div className="font-mono text-[10px] text-muted">
        {p.live?.at ? <>prices live {p.live.at.slice(11, 19)} (every 5 s)</> : <span className="text-gold">live prices unavailable{p.live?.error ? `: ${p.live.error}` : ""}, showing the last minute check</span>}
        {" · "}buy/sell decisions are made by the system once a minute{p.open[0]?.checked ? `, last ${p.open[0].checked.slice(11, 19)}` : ""}
      </div>
      {p.shadow && (
        <p className="font-mono text-[11px] text-muted">
          Exit test, same trades: sell on line touch (used) vs wait for a 5-min candle to close against you (shadow).{" "}
          {both.length === 0 ? "No trade closed in both yet." : <>On {both.length} closed in both: touch <span className={tone(touchNet)}>{inr(touchNet)}</span> · candle close <span className={tone(closeNet)}>{inr(closeNet)}</span>{shOpen.size > 0 && ` · ${shOpen.size} still held by the candle-close exit`}</>}
        </p>
      )}
      {s && (
        <p className="font-mono text-[11px] text-muted">
          Strong-candle test (own ₹1L, buys only flips whose candle is 1.9× a normal 5-min candle or bigger).{" "}
          {!since ? "No strong signal bought yet." : <>Since {hm(since)} — strong: {line(sum(s, since))} · with your rules: {line(sum(n ?? p, since))}</>}
        </p>
      )}
      {n && (
        <p className="font-mono text-[11px] text-muted">
          With your live rules (own ₹1L, day loss budget + 2-losses stop, as on your real account).{" "}
          {!nSince ? "Nothing bought yet." : <>Since 20 Nov 10:08: with rules {line(sum(n, NOLIMITS_FROM))} · no limits {line(sum(p, NOLIMITS_FROM))}</>}
        </p>
      )}
      {p.open.length === 0 && p.closed.length === 0 && <p className="font-mono text-[11px] text-muted">No paper trade yet: the first one is taken at the next signal that fits your rules (market hours, Mac awake).</p>}
      {n && (
        <div className="flex gap-2 font-mono text-[11px]">
          <span className="text-muted">Trades of:</span>
          {(["main", "rules"] as const).map((k) => (
            <button key={k} onClick={() => setWhich(k)}
              className={`rounded px-2 ${which === k ? "bg-gold/20 font-bold text-ink" : "text-muted hover:text-ink"}`}>
              {k === "main" ? "No limits (main)" : `With your live rules (${n.open.length} open, ${n.closed.length} closed)`}
            </button>))}
        </div>
      )}
      <table className="w-full font-mono text-[11px]">
        <tbody>
          {b.open.map((x) => (
            <tr key={x.option} className="border-t border-line/50">
              <td className="py-1.5 pr-3 text-muted">{hm(x.entry_at)}</td>
              <td className="pr-3 font-semibold text-ink">{x.option}</td>
              <td className="pr-3 text-right text-muted">{x.qty} @ ₹{x.entry.toFixed(2)} → ₹{px(x).toFixed(2)}</td>
              <td className={`pr-3 text-right ${tone(px(x) - x.entry)}`}>{inr((px(x) - x.entry) * x.qty)}</td>
              <td className="text-muted" title={x.plan}>
                OPEN · {x.action === "UNKNOWN" ? <span className="text-gold">no line reading: only the option stop applies</span> : x.action ?? "waiting for the first check"}
                {stockPx(x) != null && x.line != null && <> · stock ₹{stockPx(x)!.toFixed(2)} vs line ₹{x.line.toFixed(2)}</>}
              </td>
              <td className="pl-3 text-right text-muted" title="sells if the option falls 25% under its buy price or its high since the buy">
                option stop ₹{(0.75 * Math.max(x.entry, x.peak ?? x.entry)).toFixed(2)}
              </td>
            </tr>))}
          {[...b.closed].reverse().slice(0, 20).map((c) => (
            <tr key={c.option + c.exit_at} className="border-t border-line/50 opacity-80">
              <td className="py-1.5 pr-3 text-muted">{hm(c.entry_at)} → {hm(c.exit_at)}</td>
              <td className="pr-3 text-ink">{c.option}</td>
              <td className="pr-3 text-right text-muted">{c.qty} @ ₹{c.entry.toFixed(2)} → ₹{c.exit.toFixed(2)}</td>
              <td className={`pr-3 text-right ${tone(c.net)}`}>{inr(c.net)}</td>
              <td className="text-muted">{c.exit_why} · charges {inr(c.costs)}</td>
              <td className="pl-3 text-right text-muted" title="What the candle-close exit made on this same trade">
                {b !== p ? "" : shClosed.has(key(c)) ? <>candle close <span className={tone(shClosed.get(key(c))!.net)}>{inr(shClosed.get(key(c))!.net)}</span></> : shOpen.has(key(c)) ? "candle close: still holding" : ""}
              </td>
            </tr>))}
        </tbody>
      </table>
      {p.orders.length > 0 && (
        <details className="font-mono text-[10px] text-muted">
          <summary className="cursor-pointer">Orders auto mode would have sent ({p.orders.length})</summary>
          {[...p.orders].reverse().slice(0, 30).map((o) => (
            <div key={o.at + o.tradingsymbol + o.transaction_type}>{hm(o.at)} {o.transaction_type} {o.quantity} {o.tradingsymbol} LIMIT ₹{o.price}</div>))}
        </details>
      )}
    </div>
  );
}
