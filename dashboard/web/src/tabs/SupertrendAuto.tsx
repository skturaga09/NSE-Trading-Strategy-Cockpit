import { useEffect, useState } from "react";

/* AUTO EXITS (stage 2, dashboard/supertrend_auto.py): for options bought with the Supertrend "Buy in Kite" button,
   sells on your exit rules and keeps a 25 % stop-loss in Zerodha. OFF = it only logs what it would send. */

interface Act { at: string; option: string; action: string; why: string; armed: boolean; order_id?: string }
interface Status { armed: boolean; entries: boolean; no_limits?: boolean; managed: Record<string, { since: string }>; log: Act[] }

export function SupertrendAuto() {
  const [s, setS] = useState<Status | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [confirmBuy, setConfirmBuy] = useState(false);
  const [confirmRules, setConfirmRules] = useState(false);
  const [err, setErr] = useState("");
  const load = () => fetch(`/api/supertrend/auto?_t=${Date.now()}`).then((r) => r.json()).then(setS).catch(() => {});
  useEffect(() => {
    void load();
    const id = setInterval(load, 20000);
    return () => clearInterval(id);
  }, []);
  const flip = async (body: { armed: boolean } | { entries: boolean } | { no_limits: boolean }) => {
    setErr("");
    setConfirming(false);
    setConfirmBuy(false);
    setConfirmRules(false);
    try {
      const r = await fetch("/api/supertrend/auto", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      if (!r.ok) throw new Error((await r.json()).error || `switch refused (${r.status})`);
      await load();
    } catch (e) {
      setErr(String(e));
    }
  };
  if (!s) return null;
  const managed = Object.keys(s.managed);
  return (
    <div className={`panel space-y-2 rounded-lg p-5 ${s.armed ? "border border-[var(--red)]/60" : ""}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-display text-base font-bold text-ink">
          🤖 Auto exits{" "}
          <span className={`ml-1 rounded px-2 py-0.5 font-mono text-[11px] ${s.armed ? "bg-[var(--red)]/15 text-[var(--red)]" : "bg-line/40 text-muted"}`}>{s.armed ? "ON: sends real orders" : "OFF: logs only"}</span>
        </h2>
        <div className="flex items-center gap-2 font-mono text-[11px]">
          {s.armed ? (
            <button onClick={() => void flip({ armed: false })} className="rounded border border-line px-3 py-1 font-bold text-ink hover:bg-line/30">Switch off</button>
          ) : confirming ? (
            <>
              <span className="text-[var(--red)]">Real SELL and stop-loss orders will go to Kite.</span>
              <button onClick={() => void flip({ armed: true })} className="rounded border border-[var(--red)] px-3 py-1 font-bold text-[var(--red)] hover:bg-[var(--red)]/10">Yes, switch on</button>
              <button onClick={() => setConfirming(false)} className="rounded border border-line px-3 py-1 text-muted hover:text-ink">Cancel</button>
            </>
          ) : (
            <button onClick={() => setConfirming(true)} className="rounded border border-line px-3 py-1 text-muted hover:text-ink">Switch on…</button>
          )}
        </div>
      </div>
      <p className="font-mono text-[10px] text-muted">
        Only options bought with the Buy in Kite button above. On a SELL it cancels the stop-loss in Zerodha first, then sells at the best bid; while holding it keeps the 25 % stop-loss in Zerodha. Auto entries (below) buy 1 lot of each TAKE signal at the ask; an unfilled buy is cancelled after 5 minutes.
      </p>
      <div className="flex flex-wrap items-center gap-2 font-mono text-[11px]">
        <span className="font-bold text-ink">Auto entries</span>
        <span className={`rounded px-2 py-0.5 ${s.entries && s.armed ? "bg-[var(--red)]/15 text-[var(--red)]" : "bg-line/40 text-muted"}`}>{s.entries && s.armed ? "ON: buys TAKE signals itself, 1 lot" : s.entries ? "waiting: needs auto exits ON" : "OFF: logs WOULD BUY only"}</span>
        {s.entries ? (
          <button onClick={() => void flip({ entries: false })} className="rounded border border-line px-3 py-1 font-bold text-ink hover:bg-line/30">Switch off</button>
        ) : confirmBuy ? (
          <>
            <span className="text-[var(--red)]">Real BUY orders will go to Kite without asking you.</span>
            <button onClick={() => void flip({ entries: true })} className="rounded border border-[var(--red)] px-3 py-1 font-bold text-[var(--red)] hover:bg-[var(--red)]/10">Yes, switch on</button>
            <button onClick={() => setConfirmBuy(false)} className="rounded border border-line px-3 py-1 text-muted hover:text-ink">Cancel</button>
          </>
        ) : (
          <button onClick={() => setConfirmBuy(true)} className="rounded border border-line px-3 py-1 text-muted hover:text-ink">Switch on…</button>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2 font-mono text-[11px]">
        <span className="font-bold text-ink">Strategy</span>
        <span className={`rounded px-2 py-0.5 ${s.no_limits ? "bg-[var(--red)]/15 text-[var(--red)]" : "bg-line/40 text-muted"}`}>
          {s.no_limits ? "NO LIMITS: no day loss budget, no 4-open cap, 1 lot; cash and 20 orders a day decide"
            : "YOUR RULES: 10 % day loss budget, max 4 open"}</span>
        {s.no_limits ? (
          <button onClick={() => void flip({ no_limits: false })} className="rounded border border-line px-3 py-1 font-bold text-ink hover:bg-line/30">Back to your rules</button>
        ) : confirmRules ? (
          <>
            <span className="text-[var(--red)]">Real tickets and auto entries stop checking the day loss budget and the 4-open limit.</span>
            <button onClick={() => void flip({ no_limits: true })} className="rounded border border-[var(--red)] px-3 py-1 font-bold text-[var(--red)] hover:bg-[var(--red)]/10">Yes, no limits</button>
            <button onClick={() => setConfirmRules(false)} className="rounded border border-line px-3 py-1 text-muted hover:text-ink">Cancel</button>
          </>
        ) : (
          <button onClick={() => setConfirmRules(true)} className="rounded border border-line px-3 py-1 text-muted hover:text-ink">Switch to no limits…</button>
        )}
      </div>
      {err && <p className="font-mono text-[11px] text-[var(--red)]">⚠ {err}</p>}
      <p className="font-mono text-[11px] text-muted">Managing: {managed.length ? <span className="text-ink">{managed.join(", ")}</span> : "nothing yet"}</p>
      {s.log.length > 0 && (
        <table className="w-full font-mono text-[11px]">
          <tbody>{s.log.slice(0, 12).map((a) => (
            <tr key={a.at + a.option + a.action} className="border-t border-line/50">
              <td className="py-1 pr-3 text-muted">{a.at.slice(5, 16).replace("T", " ")}</td>
              <td className={`pr-3 font-semibold ${a.action.includes("FAILED") || a.action === "ALERT" ? "text-[var(--red)]" : a.action.startsWith("WOULD") ? "text-muted" : "text-ink"}`}>{a.action}</td>
              <td className="pr-3 text-ink">{a.option}</td>
              <td className="text-muted">{a.why}{a.order_id ? ` · order ${a.order_id}` : ""}</td>
            </tr>))}</tbody>
        </table>
      )}
    </div>
  );
}
