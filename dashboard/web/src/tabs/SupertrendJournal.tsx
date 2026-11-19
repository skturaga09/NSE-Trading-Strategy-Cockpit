import { useEffect, useState } from "react";

/* =============================================================================
   SUPERTREND JOURNAL — paper trades of the owner's Supertrend rules on REAL option
   prices (scripts/supertrend_journal.py, every weekday 16:30). ₹1,00,000 start as the paper account, the whole
   balance usable, profits reused. Each version is the same signals under different
   risk rules, so the rules can be judged on our own trades. Paper only: no orders.
============================================================================= */

interface Summary {
  start: number; balance: number; closed_pnl: number; open_pnl: number; trades: number; open: number;
  win_rate: number | null; avg_win: number | null; avg_loss: number | null; worst_drawdown: number; lowest_balance: number;
}
interface Trade { entry: string; sym: string; contract: string; side: string; lot: number; entry_px: number; exit_px: number; premium: number; exit: string | null; why: string; nights: number; net: number }
interface Version {
  id: string; label: string; exit: string; summary: Summary;
  curve: { day: string; pnl: number; balance: number }[];
  trades: Trade[];
  skipped: { reason: string; count: number; would_have_made: number }[];
}
interface JournalData { generated_at?: string; capital?: number; versions: Version[]; days: Record<string, Record<string, number>>; note?: string }

const inr = (x: number | null | undefined, sign = true) =>
  x == null ? "—" : `${sign && x > 0 ? "+" : x < 0 ? "−" : ""}₹${Math.abs(Math.round(x)).toLocaleString("en-IN")}`;
const tone = (x: number | null | undefined) => (x == null || x === 0 ? "text-muted" : x > 0 ? "text-[var(--green)]" : "text-[var(--red)]");
const when = (iso: string | null) => (iso ? `${iso.slice(5, 10)} ${iso.slice(11, 16)}` : "open");

export function SupertrendJournal() {
  const [j, setJ] = useState<JournalData | null>(null);
  const [pick, setPick] = useState("MAIN");
  useEffect(() => {
    fetch(`/api/supertrend/journal?_t=${Date.now()}`).then((r) => r.json()).then(setJ).catch(() => setJ(null));
  }, []);

  if (!j) return <p className="font-mono text-[11px] text-muted">Loading the journal…</p>;
  if (!j.versions.length) return <p className="font-mono text-[11px] text-gold">⚠ {j.note ?? "No journal yet."}</p>;
  const v = j.versions.find((x) => x.id === pick) ?? j.versions[0];
  const days = Object.keys(j.days);

  return (
    <div className="space-y-4">
      <div className="rounded-md border border-gold/25 bg-gold/[0.05] px-4 py-2.5 font-mono text-[10px] leading-relaxed text-muted">
        📒 PAPER TRADES on real option prices — your Supertrend rules: 5-min flip before 14:00 with the 15-min trend agreeing,
        1 lot of the 1-strike-ITM current-month option, the Supertrend line as the stop, overnight only if 5m and 15m agree at 15:15.
        Start ₹{(j.capital ?? 50000).toLocaleString("en-IN")}, the whole balance usable, profits reused; max 4 open, 5 a day.
        ASSUMED 1% buy/sell gap each side + real charges. {days.length} trading days ({days[0]} to {days[days.length - 1]}) ·
        updated {j.generated_at?.slice(0, 16).replace("T", " ")}. No orders are ever placed.
      </div>

      <div className="panel space-y-2 rounded-lg p-5">
        <h3 className="font-display text-sm font-bold text-ink">Same signals, different risk rules <span className="font-mono text-[10px] font-normal text-muted">— click one to see its trades</span></h3>
        <div className="overflow-x-auto">
          <table className="w-full font-mono text-[11px]">
            <thead className="text-left text-[10px] uppercase tracking-wide text-muted">
              <tr><th className="py-1.5 pr-3">Rules</th><th className="pr-3 text-right">Balance</th><th className="pr-3 text-right">Profit</th>
                <th className="pr-3 text-right">Open trades</th><th className="pr-3 text-right">Trades</th><th className="pr-3 text-right">Win rate</th>
                <th className="pr-3 text-right">Avg win / loss</th><th className="pr-3 text-right">Worst drop</th><th className="text-right">Lowest balance</th></tr>
            </thead>
            <tbody>
              {j.versions.map((x) => (
                <tr key={x.id} onClick={() => setPick(x.id)}
                  className={`cursor-pointer border-t border-line/50 ${x.id === v.id ? "bg-gold/[0.08]" : "hover:bg-white/[0.03]"}`}>
                  <td className="py-1.5 pr-3 text-ink">{x.id === v.id ? "▸ " : ""}{x.label}</td>
                  <td className="pr-3 text-right font-semibold text-ink">{inr(x.summary.balance, false)}</td>
                  <td className={`pr-3 text-right ${tone(x.summary.closed_pnl)}`}>{inr(x.summary.closed_pnl)}</td>
                  <td className={`pr-3 text-right ${tone(x.summary.open_pnl)}`}>{x.summary.open ? `${x.summary.open} · ${inr(x.summary.open_pnl)}` : "—"}</td>
                  <td className="pr-3 text-right text-ink">{x.summary.trades}</td>
                  <td className="pr-3 text-right text-ink">{x.summary.win_rate == null ? "—" : `${x.summary.win_rate}%`}</td>
                  <td className="pr-3 text-right"><span className={tone(x.summary.avg_win)}>{inr(x.summary.avg_win)}</span> / <span className={tone(x.summary.avg_loss)}>{inr(x.summary.avg_loss)}</span></td>
                  <td className="pr-3 text-right text-[var(--red)]">{inr(x.summary.worst_drawdown)}</td>
                  <td className="text-right text-ink">{inr(x.summary.lowest_balance, false)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="panel rounded-lg p-5">
          <h3 className="mb-2 font-display text-sm font-bold text-ink">Day by day <span className="font-mono text-[10px] font-normal text-muted">— {v.id}</span></h3>
          <table className="w-full font-mono text-[11px]">
            <thead className="text-left text-[10px] uppercase tracking-wide text-muted"><tr><th className="py-1 pr-3">Day</th><th className="pr-3 text-right">Closed P&amp;L</th><th className="text-right">Balance</th></tr></thead>
            <tbody>{v.curve.map((d) => (
              <tr key={d.day} className="border-t border-line/50">
                <td className="py-1 pr-3 text-muted">{d.day}</td><td className={`pr-3 text-right ${tone(d.pnl)}`}>{inr(d.pnl)}</td>
                <td className="text-right text-ink">{inr(d.balance, false)}</td></tr>))}</tbody>
          </table>
        </div>
        <div className="panel rounded-lg p-5">
          <h3 className="mb-2 font-display text-sm font-bold text-ink">Signals the rules turned away <span className="font-mono text-[10px] font-normal text-muted">— and what they would have made</span></h3>
          {v.skipped.length === 0 ? <p className="font-mono text-[11px] text-muted">None.</p> : (
            <table className="w-full font-mono text-[11px]">
              <thead className="text-left text-[10px] uppercase tracking-wide text-muted"><tr><th className="py-1 pr-3">Why skipped</th><th className="pr-3 text-right">Signals</th><th className="text-right">Would have made</th></tr></thead>
              <tbody>{v.skipped.map((s) => (
                <tr key={s.reason} className="border-t border-line/50">
                  <td className="py-1 pr-3 text-ink">{s.reason}</td><td className="pr-3 text-right text-ink">{s.count}</td>
                  <td className={`text-right ${tone(s.would_have_made)}`}>{inr(s.would_have_made)}</td></tr>))}</tbody>
            </table>
          )}
          <p className="mt-2 font-mono text-[9px] leading-relaxed text-muted">
            A rule that keeps turning away signals that would have made money is costing you; one whose skipped signals lose is protecting you.
            "Would have made" prices each skipped signal alone, as if you had taken it.
          </p>
        </div>
      </div>

      <div className="panel rounded-lg p-5">
        <h3 className="mb-2 font-display text-sm font-bold text-ink">Trades <span className="font-mono text-[10px] font-normal text-muted">— {v.label} · newest first ·
          prices are the option's real traded prices per unit; premium = bought at × lot; net also pays the 1% gap each side + charges; * = still open, last price</span></h3>
        <div className="overflow-x-auto">
          <table className="w-full font-mono text-[11px]">
            <thead className="text-left text-[10px] uppercase tracking-wide text-muted">
              <tr><th className="py-1.5 pr-3">Bought</th><th className="pr-3">Option</th><th className="pr-3 text-right">Lot</th>
                <th className="pr-3 text-right">Bought at</th><th className="pr-3 text-right">Premium</th><th className="pr-3">Sold</th>
                <th className="pr-3 text-right">Sold at</th><th className="pr-3">Why</th><th className="pr-3 text-right">Nights</th><th className="text-right">Net</th></tr>
            </thead>
            <tbody>{v.trades.map((t) => (
              <tr key={t.entry + t.sym} className="border-t border-line/50">
                <td className="py-1.5 pr-3 text-muted">{when(t.entry)}</td>
                <td className="pr-3 text-ink"><span className={t.side === "CE" ? "text-[var(--green)]" : "text-[var(--red)]"}>{t.side === "CE" ? "▲" : "▼"}</span> {t.contract}</td>
                <td className="pr-3 text-right text-muted">{t.lot}</td>
                <td className="pr-3 text-right text-ink">₹{t.entry_px.toFixed(2)}</td>
                <td className="pr-3 text-right text-ink">{inr(t.premium, false)}</td>
                <td className="pr-3 text-muted">{when(t.exit)}</td>
                <td className="pr-3 text-right text-ink">₹{t.exit_px.toFixed(2)}{t.exit ? "" : "*"}</td>
                <td className="pr-3 text-muted">{t.why.replace(/_/g, " ").toLowerCase()}</td>
                <td className="pr-3 text-right text-muted">{t.nights || ""}</td>
                <td className={`text-right font-semibold ${tone(t.net)}`}>{inr(t.net)}{t.exit ? "" : " (open)"}</td>
              </tr>))}</tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
