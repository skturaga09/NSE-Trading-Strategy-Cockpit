import { useEffect, useState } from "react";

/* LIVE PAPER TRADING of the Supertrend rules (dashboard/supertrend_paper.py): the orders auto mode WOULD send,
   filled on paper at live prices, exits by your rules, net P&L after charges. Nothing is sent to Kite. */

interface Pos { option: string; qty: number; entry: number; entry_at: string; ltp: number }
interface Closed extends Pos { exit: number; exit_at: string; exit_why: string; net: number; costs: number }
interface Order { at: string; tradingsymbol: string; transaction_type: string; quantity: number; price: number }
interface Paper { start: number; cash: number; open: Pos[]; closed: Closed[]; orders: Order[]; shadow?: { open: Pos[]; closed: Closed[] } }

const inr = (x: number) => `${x < 0 ? "−" : ""}₹${Math.abs(Math.round(x)).toLocaleString("en-IN")}`;
const hm = (iso: string) => `${iso.slice(5, 10)} ${iso.slice(11, 16)}`;
const tone = (x: number) => (x >= 0 ? "text-[var(--green)]" : "text-[var(--red)]");

export function SupertrendPaper() {
  const [p, setP] = useState<Paper | null>(null);
  useEffect(() => {
    const load = () => fetch(`/api/supertrend/paper?_t=${Date.now()}`).then((r) => r.json()).then(setP).catch(() => {});
    void load();
    const id = setInterval(load, 20000);
    return () => clearInterval(id);
  }, []);
  if (!p) return null;
  const mtm = p.open.reduce((a, x) => a + x.qty * x.ltp, 0);
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
  return (
    <div className="panel space-y-3 rounded-lg p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-display text-base font-bold text-ink">📝 Paper trading <span className="font-mono text-[10px] font-normal text-muted">— the orders auto mode would send, filled on paper at live prices. Nothing goes to Kite.</span></h2>
        <span className="font-mono text-[11px] text-muted">
          balance <span className="text-ink">{inr(balance)}</span> (<span className={tone(balance - p.start)}>{inr(balance - p.start)}</span> on {inr(p.start)}) ·
          booked <span className={tone(realised)}>{inr(realised)}</span> · {p.closed.length} trades, {wins} won
        </span>
      </div>
      {p.shadow && (
        <p className="font-mono text-[11px] text-muted">
          Exit test, same trades: sell on line touch (used) vs wait for a 5-min candle to close against you (shadow).{" "}
          {both.length === 0 ? "No trade closed in both yet." : <>On {both.length} closed in both: touch <span className={tone(touchNet)}>{inr(touchNet)}</span> · candle close <span className={tone(closeNet)}>{inr(closeNet)}</span>{shOpen.size > 0 && ` · ${shOpen.size} still held by the candle-close exit`}</>}
        </p>
      )}
      {p.open.length === 0 && p.closed.length === 0 && <p className="font-mono text-[11px] text-muted">No paper trade yet: the first one is taken at the next signal that fits your rules (market hours, Mac awake).</p>}
      <table className="w-full font-mono text-[11px]">
        <tbody>
          {p.open.map((x) => (
            <tr key={x.option} className="border-t border-line/50">
              <td className="py-1.5 pr-3 text-muted">{hm(x.entry_at)}</td>
              <td className="pr-3 font-semibold text-ink">{x.option}</td>
              <td className="pr-3 text-right text-muted">{x.qty} @ ₹{x.entry.toFixed(2)} → ₹{x.ltp.toFixed(2)}</td>
              <td className={`pr-3 text-right ${tone(x.ltp - x.entry)}`}>{inr((x.ltp - x.entry) * x.qty)}</td>
              <td className="text-muted">OPEN (before charges)</td>
              <td />
            </tr>))}
          {[...p.closed].reverse().slice(0, 20).map((c) => (
            <tr key={c.option + c.exit_at} className="border-t border-line/50 opacity-80">
              <td className="py-1.5 pr-3 text-muted">{hm(c.entry_at)} → {hm(c.exit_at)}</td>
              <td className="pr-3 text-ink">{c.option}</td>
              <td className="pr-3 text-right text-muted">{c.qty} @ ₹{c.entry.toFixed(2)} → ₹{c.exit.toFixed(2)}</td>
              <td className={`pr-3 text-right ${tone(c.net)}`}>{inr(c.net)}</td>
              <td className="text-muted">{c.exit_why} · charges {inr(c.costs)}</td>
              <td className="pl-3 text-right text-muted" title="What the candle-close exit made on this same trade">
                {shClosed.has(key(c)) ? <>candle close <span className={tone(shClosed.get(key(c))!.net)}>{inr(shClosed.get(key(c))!.net)}</span></> : shOpen.has(key(c)) ? "candle close: still holding" : ""}
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
