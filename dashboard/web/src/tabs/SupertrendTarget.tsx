import { useState } from "react";

/* TARGET PRICE CALCULATOR (dashboard/target_calc.forward): "if the stock reaches X, what is my option worth?" for the
   option the Supertrend rules would buy in that direction, priced from live Kite quotes, with reward : risk against
   the stock's Supertrend stop line. */

interface Result {
  error?: string;
  symbol: string; spot: number; target: number; move_pct: number;
  option: string; strike: number; expiry: string; days: number; lot: number;
  premium: number; bid: number | null; ask: number | null; quote_at: string;
  trend: "UP" | "DOWN" | null; with_trend: boolean; stop_line: number | null;
  iv_pct: number; delta: number; est_premium: number; gain_per_lot: number; at_expiry: number;
  premium_at_stop?: number; loss_per_lot?: number; reward_risk?: number | null;
  which: "yours" | "typed" | "rules"; kind: "CE" | "PE";
  qty?: number; avg?: number; pnl_now?: number; pnl_at_target?: number; pnl_at_stop?: number;   // only for your own position
}

const inr = (x: number) => `₹${Math.round(x).toLocaleString("en-IN")}`;
const signed = (x: number) => `${x >= 0 ? "+" : "−"}${inr(Math.abs(x))}`;
const pl = (x: number) => <span className="font-bold" style={{ color: x >= 0 ? "var(--green)" : "var(--red)" }}>{signed(x)}</span>;
const rs = (x: number) => `₹${x.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

export function SupertrendTarget() {
  const [symbol, setSymbol] = useState("");
  const [target, setTarget] = useState("");
  const [r, setR] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);

  const calc = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const q = new URLSearchParams({ symbol: symbol.trim(), target });
      const res = await fetch(`/api/supertrend/target?${q}`);
      setR(res.ok ? await res.json() : ({ error: `request failed: ${res.status}` } as Result));
    } catch {
      setR({ error: "dashboard server not reachable" } as Result);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel space-y-3 rounded-lg p-5">
      <h2 className="font-display text-base font-bold text-ink">
        🎯 Target price calculator{" "}
        <span className="font-mono text-[11px] font-normal text-muted">— if the stock reaches your price, what is the option worth? Live Kite prices.</span>
      </h2>
      <form onSubmit={calc} className="flex flex-wrap items-end gap-2 font-mono text-[11px]">
        <label className="flex flex-col gap-1 text-muted">Stock, index or option
          <input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} placeholder="BAJFINANCE or an option" required
            className="w-56 rounded border border-line bg-transparent px-2 py-1 text-ink" />
        </label>
        <label className="flex flex-col gap-1 text-muted">Target price (₹)
          <input value={target} onChange={(e) => setTarget(e.target.value)} placeholder="1140" required
            type="number" step="any" min="0" className="w-32 rounded border border-line bg-transparent px-2 py-1 text-ink" />
        </label>
        <button disabled={busy} className="rounded border border-gold/60 bg-gold/15 px-3 py-1 text-gold disabled:opacity-50">
          {busy ? "Reading Kite…" : "Calculate"}
        </button>
      </form>

      {r?.error && <p className="font-mono text-[11px] text-[var(--red)]">⚠ {r.error}</p>}
      {r && !r.error && (
        <div className="space-y-1.5 font-mono text-[11px] leading-relaxed text-muted">
          {Math.abs(r.move_pct) > 15 && (
            <div className="text-gold">⚠ {rs(r.target)} is a {Math.abs(r.move_pct)}% move from {rs(r.spot)}: check the target.</div>
          )}
          <div>
            <span className="text-ink">{r.symbol} {rs(r.spot)} → {rs(r.target)}</span> ({r.move_pct > 0 ? "+" : ""}{r.move_pct}%) ·{" "}
            {r.which === "yours" ? "your option" : r.which === "typed" ? "the option you typed" : "option your rules would buy"}:{" "}
            <span className="text-ink">{r.option}</span> (expires {r.expiry}, {r.days} days, lot {r.lot})
            {r.qty != null && r.avg != null && <> · <span className="text-ink">you hold {r.qty} qty bought at {rs(r.avg)}</span></>}
          </div>
          <div>
            Premium now <span className="text-ink">{rs(r.premium)}</span> {r.bid && r.ask ? `(mid of bid ${rs(r.bid)} / ask ${rs(r.ask)})` : "(last traded: no live bid/ask)"} ·
            delta {r.delta} · volatility {r.iv_pct}% · Kite price at {r.quote_at || "—"}
            {r.pnl_now != null && <> · your P&L now {pl(r.pnl_now)}</>}
          </div>
          <div className="text-[12px]">
            If {r.symbol} reaches {rs(r.target)} soon: premium ≈ <span className="font-bold text-ink">{rs(r.est_premium)}</span> →{" "}
            {r.pnl_at_target != null ? <>your P&L {pl(r.pnl_at_target)}</> : <>{pl(r.gain_per_lot)} per lot</>}
            <span className="text-muted"> · at expiry it would be worth {rs(r.at_expiry)}</span>
          </div>
          {r.stop_line != null && r.premium_at_stop != null ? (
            <div className="text-[12px]">
              At the stop line {rs(r.stop_line)}: premium ≈ <span className="text-ink">{rs(r.premium_at_stop)}</span> →{" "}
              {r.pnl_at_stop != null ? <>your P&L {pl(r.pnl_at_stop)}</> : <>{pl(-(r.loss_per_lot ?? 0))} per lot</>}
              {r.reward_risk != null && r.reward_risk > 0 && <> · reward : risk <span className="font-bold text-ink">{r.reward_risk} : 1</span></>}
            </div>
          ) : (
            <div className="text-gold">
              {r.trend ? `This ${r.kind === "CE" ? "call" : "put"} is against the 5-minute trend (${r.trend})${r.which === "rules" ? ": your rules would not buy it" : ""}, so there is no stop line to measure risk.`
                : "Not on the Supertrend board, so there is no stop line to measure risk."}
            </div>
          )}
          <div className="text-[10px]">
            An estimate for a move that happens soon (same day or next): time decay and a fall in volatility make a slower move worth less. Not advice.
          </div>
        </div>
      )}
    </div>
  );
}
