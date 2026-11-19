import { useEffect, useState } from "react";

/* =============================================================================
   SUPERTREND ORDER TICKETS — Buy / Sell buttons that FILL IN Kite's own order window
   (Kite Publisher: https://kite.trade/publisher.js). The owner reviews each order in
   Kite and presses Buy / Sell there; this page never sends an order by itself.
============================================================================= */

interface KiteOrder { [k: string]: string | number | boolean }
interface Signal {
  symbol: string; trend: "UP" | "DOWN"; signal_at: string; age_min: number; stop_line: number;
  option?: string; lot?: number; lots?: number; ltp?: number | null; ask?: number | null; bid?: number | null; premium?: number | null; delta?: number | null;
  verdict: "TAKE" | "SKIP"; why: string; orders?: KiteOrder[];
  strength?: number | null; strong?: boolean | null;   // flip candle body vs a normal 5-min candle
}
interface Position {
  option: string; underlying: string; qty: number; avg: number; ltp: number | null; pnl: number;
  stock_ltp: number | null; line: number | null; action: "SELL" | "HOLD" | "UNKNOWN"; why: string;
  sl_in_zerodha: boolean; sell: KiteOrder[]; backstop: KiteOrder[]; managed?: boolean;
}
interface View {
  api_key?: string; account?: { cash: number; balance: number; day_open: number; budget: number; open: number; orders_today: number };
  limits: { max_open: number; max_orders_per_day: number }; signals: Signal[]; positions: Position[]; errors: string[];
}

declare global { interface Window { KiteConnect?: new (apiKey: string) => { add: (o: KiteOrder) => void; connect: () => void; finished: (cb: () => void) => void } } }

const inr = (x: number | null | undefined) => (x == null ? "—" : `₹${Math.round(x).toLocaleString("en-IN")}`);

function loadPublisher(): Promise<void> {
  if (window.KiteConnect) return Promise.resolve();
  return new Promise((ok, fail) => {
    const s = document.createElement("script");
    s.src = "https://kite.trade/publisher.js?v=3";
    s.onload = () => ok();
    s.onerror = () => fail(new Error("could not load Kite's publisher.js"));
    document.body.appendChild(s);
  });
}

export function SupertrendTrade() {
  const [v, setV] = useState<View | null>(null);
  const [err, setErr] = useState("");
  const [autoBuys, setAutoBuys] = useState(false);     // auto entries buys TAKE itself: a Buy button here would buy twice
  const load = () => {
    fetch(`/api/supertrend/trades?_t=${Date.now()}`).then((r) => r.json()).then(setV).catch(() => {});
    fetch("/api/supertrend/auto").then((r) => r.json()).then((a) => setAutoBuys(!!(a.armed && a.entries))).catch(() => {});
  };
  useEffect(() => {
    void load();
    const id = setInterval(load, 20000);
    return () => clearInterval(id);
  }, []);

  const openInKite = async (orders: KiteOrder[]) => {
    setErr("");
    try {
      await loadPublisher();
      if (!v?.api_key || !window.KiteConnect) throw new Error("Kite API key not available");
      const kite = new window.KiteConnect(v.api_key);
      orders.forEach((o) => kite.add(o));
      kite.finished(() => void load());
      kite.connect();                       // opens Kite's window with the order filled in; you press Buy / Sell there
    } catch (e) {
      setErr(String(e));
    }
  };

  const manage = async (option: string, on: boolean) => {
    setErr("");
    try {
      const r = await fetch("/api/supertrend/auto/manage", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ option, manage: on }) });
      if (!r.ok) throw new Error((await r.json()).error || `refused (${r.status})`);
      await load();
    } catch (e) {
      setErr(String(e));
    }
  };

  if (!v) return null;
  const take = v.signals.filter((s) => s.verdict === "TAKE");
  const skipped = v.signals.filter((s) => s.verdict !== "TAKE");
  const row = (s: Signal) => (
    <tr key={s.symbol + s.signal_at} className="border-t border-line/50">
      <td className="py-1.5 pr-3 text-muted">{s.signal_at}</td>
      <td className="pr-3 font-semibold text-ink">{s.trend === "UP" ? "▲" : "▼"} {s.symbol} <Strength v={s.strength} strong={s.strong} /></td>
      <td className="pr-3 text-ink">{s.option ?? "—"}</td>
      <td className="pr-3 text-right text-muted">{s.lots && s.lot ? `${s.lots} lot${s.lots > 1 ? "s" : ""} · ${s.lots * s.lot} qty` : s.lot ? `lot ${s.lot}` : ""}</td>
      <td className="pr-3 text-right text-ink" title={`best seller ₹${s.ask ?? "—"} · best buyer ₹${s.bid ?? "—"} · last trade ₹${s.ltp ?? "—"}`}>{s.ask ? `ask ₹${s.ask.toFixed(2)}` : "no seller"}{s.ltp && s.ask && Math.abs(s.ltp - s.ask) / s.ask > 0.03 ? <span className="text-muted"> (last ₹{s.ltp.toFixed(2)})</span> : null}</td>
      <td className="pr-3 text-right text-ink" title="delta: how many ₹ the option moves for ₹1 of stock move (worked out from the option's own price)">{s.delta != null ? `Δ ${s.delta.toFixed(2)}` : "Δ —"}</td>
      <td className="pr-3 text-right text-ink" title="what the lot(s) cost at the ask">{inr(s.premium != null && s.lots ? s.premium * s.lots : s.premium)}</td>
      <td className="pr-3 text-muted">stop: stock {s.trend === "UP" ? "below" : "above"} ₹{s.stop_line.toFixed(2)}</td>
      <td className="text-right">{s.verdict === "TAKE" && autoBuys
        ? <span className="font-bold text-[var(--green)]">auto mode buys this</span>
        : s.verdict === "TAKE" && s.orders
        ? <button onClick={() => void openInKite(s.orders!)} className="rounded border border-[var(--green)] px-3 py-1 font-bold text-[var(--green)] hover:bg-[var(--green)]/10">Buy in Kite</button>
        : <span className="text-muted">{s.why}</span>}</td>
    </tr>);
  return (
    <div className="panel space-y-3 rounded-lg p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-display text-base font-bold text-ink">🧾 Your orders <span className="font-mono text-[10px] font-normal text-muted">— buttons fill in Kite's order window; you press Buy / Sell in Kite. Nothing is sent without you.</span></h2>
        {v.account && (
          <span className="font-mono text-[11px] text-muted">
            cash <span className="text-ink">{inr(v.account.cash)}</span> · day loss budget left <span className="text-ink" title="Balance (cash + what you paid for open options) minus 90 % of this morning's balance, minus 30 % of what the open options cost. Lots are sized to fit it.">{inr(v.account.budget)}</span> · open <span className="text-ink">{v.account.open}/{v.limits.max_open}</span> ·
            orders today <span className="text-ink">{v.account.orders_today}/{v.limits.max_orders_per_day}</span>
          </span>
        )}
      </div>
      {v.errors.map((e) => <p key={e} className="font-mono text-[11px] text-gold">⚠ {e}</p>)}
      {err && <p className="font-mono text-[11px] text-[var(--red)]">⚠ {err}</p>}

      <div>
        <h3 className="mb-1 font-mono text-[11px] font-bold uppercase tracking-wide text-muted">Entries (flip before 14:00, 15m agreeing, 1-strike OTM, lots that fit your cash and day loss budget, LIMIT at the best ask)</h3>
        {take.length === 0 ? <p className="font-mono text-[11px] text-muted">Nothing to take right now.{autoBuys ? " Auto entries will buy the next one itself." : ""}</p> : (
          <table className="w-full font-mono text-[11px]">
            <tbody>{take.map(row)}</tbody>
          </table>
        )}
        {take.length > 1 && !autoBuys && <p className="mt-1 font-mono text-[9px] text-muted">Several fit your limits: take them newest first; each button is one order.</p>}
        {skipped.length > 0 && (
          <details className="mt-2 font-mono text-[10px] text-muted">
            <summary className="cursor-pointer">Today's signals your rules skipped ({skipped.length}), newest first: price is live now, not at the signal. A manual buy here is outside the rules and auto exits won't manage it unless you press Auto-manage after.</summary>
            <table className="mt-1 w-full font-mono text-[11px]"><tbody>{skipped.map(row)}</tbody></table>
          </details>
        )}
      </div>

      <div>
        <h3 className="mb-1 font-mono text-[11px] font-bold uppercase tracking-wide text-muted">Your options (from Kite) and their exits</h3>
        {v.positions.length === 0 ? <p className="font-mono text-[11px] text-muted">No option position open.</p> : (
          <table className="w-full font-mono text-[11px]">
            <tbody>{v.positions.map((p) => {
              const sell = p.action === "SELL";
              return (
                <tr key={p.option} className={`border-t border-line/50 ${sell ? "bg-[var(--red)]/[0.06]" : ""}`}>
                  <td className="py-1.5 pr-3 font-semibold text-ink">{p.option}</td>
                  <td className="pr-3 text-right text-muted">{p.qty} qty @ ₹{p.avg.toFixed(2)}</td>
                  <td className="pr-3 text-right text-ink">{p.ltp ? `₹${p.ltp.toFixed(2)}` : "—"}</td>
                  <td className={`pr-3 text-right ${p.pnl >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}`}>{p.pnl >= 0 ? "+" : ""}{inr(p.pnl)}</td>
                  <td className={`pr-3 ${sell ? "font-bold text-[var(--red)]" : "text-muted"}`}>{sell ? "SELL NOW: " : p.action === "HOLD" ? "HOLD · " : ""}{p.why}</td>
                  <td className="whitespace-nowrap text-right">
                    {p.sell.length > 0 && <button onClick={() => void openInKite(p.sell)}
                      className={`rounded border px-3 py-1 font-bold ${sell ? "border-[var(--red)] text-[var(--red)] hover:bg-[var(--red)]/10" : "border-line text-muted hover:text-ink"}`}>Sell in Kite</button>}
                    {!p.sl_in_zerodha && p.backstop.length > 0 && <button onClick={() => void openInKite(p.backstop)} title="Stop-loss SELL at 25% below your buy price; it sits in Zerodha and fires even if this Mac is off. Cancel it in Kite when you sell."
                      className="ml-1 rounded border border-line px-2 py-1 text-muted hover:text-ink">+ stop-loss ₹{Number(p.backstop[0].trigger_price).toFixed(2)}</button>}
                    {p.sl_in_zerodha && <span className="ml-1 text-[10px] text-muted">stop-loss in Zerodha ✓</span>}
                    {p.managed
                      ? <button onClick={() => void manage(p.option, false)} title="Auto exits sells this on your rules and keeps a trailing GTT stop (when switched on). Click to take it back."
                          className="ml-1 rounded border border-[var(--green)] px-2 py-1 text-[var(--green)] hover:bg-[var(--green)]/10">Auto-managed ✓</button>
                      : <button onClick={() => void manage(p.option, true)} title="Hand this position to auto exits: it will sell it on your rules and keep a trailing GTT stop in Zerodha once auto exits is switched on."
                          className="ml-1 rounded border border-line px-2 py-1 text-muted hover:text-ink">Auto-manage</button>}
                  </td>
                </tr>);
            })}</tbody>
          </table>
        )}
      </div>
    </div>
  );
}

export function Strength({ v, strong }: { v?: number | null; strong?: boolean | null }) {
  if (v == null || strong == null) return null;
  return <span className={`ml-1 rounded px-1 text-[10px] font-bold ${strong ? "bg-gold/20 text-gold" : "bg-line/60 text-muted"}`}
    title={`flip candle ${v.toFixed(1)}x a normal 5-minute candle (STRONG from 1.9x; on paper test since 19 Nov, not a live rule yet)`}>
    {strong ? "STRONG" : "WEAK"}</span>;
}
