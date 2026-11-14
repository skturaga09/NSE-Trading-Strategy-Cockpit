import { useEffect, useState } from "react";
import { SupertrendJournal } from "./SupertrendJournal";
import { SupertrendTrade } from "./SupertrendTrade";
import { SupertrendPaper } from "./SupertrendPaper";
import { SupertrendAuto } from "./SupertrendAuto";

interface SupertrendRow {
  symbol: string;
  trend: "UP" | "DOWN";
  close: number;
  open?: number;                 // the board day's opening price (first 5-minute candle)
  line: number;
  gap_pct: number;
  bar: string;
  since: string | null;          // start of the candle the trend flipped on
  since_close: number | null;
  since_at_least: string | null; // no flip inside the fetched history: the trend holds at least since then
  trend_15m: "UP" | "DOWN" | null; // same indicator on 15-minute candles (null: too little history)
  since_15m: string | null;
  since_at_least_15m: string | null;
  agree: boolean;                // 5-minute and 15-minute trends point the same way
  agree_since: string | null;    // when the later of the two flips closed (null: one of them flipped before the history)
}
interface SupertrendBoard {
  bar?: string;
  scanned_at?: string;
  rows: SupertrendRow[];
  errors?: Record<string, string>;
  market_open: boolean;
  setting: string;
  // today's pre-open check (from 09:09): stocks whose auction open is already across their 5m line
  preopen?: { day: string; at: string; priced: number; opens?: Record<string, number>;
    rows: { symbol: string; trend: "UP" | "DOWN"; may_turn: "UP" | "DOWN"; line: number; open: number; gap_pct: number }[] };
}

const getBoard = async (): Promise<SupertrendBoard> => {
  const res = await fetch(`/api/supertrend?_t=${Date.now()}`, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`GET /api/supertrend failed: ${res.status}`);
  return res.json() as Promise<SupertrendBoard>;
};

/* =============================================================================
   SUPERTREND BOARD — every F&O stock and index, UP or DOWN on the owner's own Kite
   chart setting (Supertrend 10, 3 on 5-minute candles). Kite chart alerts can't be read
   through the API, so the server recomputes the indicator from Kite's candles after
   every closed 5-minute candle and phones each flip. "Both agree" lists only instruments whose
   5-minute and 15-minute trends point the same way. A heads-up screen, not advice.
============================================================================= */

const LAST_ENTRY = "14:00";   // same cut-off as the server's phone alerts (dashboard/supertrend.py LAST_ALERT)

type Filter = "BOTH" | "ALL" | "TODAY";

const hhmm = (iso: string) => iso.slice(11, 16);
const day = (iso: string) => iso.slice(0, 10);
const closeTime = (iso: string, min = 5) => {   // a candle's start + its length = when the flip became final
  const d = new Date(iso);
  d.setMinutes(d.getMinutes() + min);
  return d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Kolkata" });
};

export function Supertrend() {
  const [view, setView] = useState<"board" | "journal">("board");
  return (
    <div className="space-y-3">
      <div className="flex gap-1 font-mono text-[11px]">
        {(["board", "journal"] as const).map((x) => (
          <button key={x} onClick={() => setView(x)}
            className={`rounded border px-3 py-1 ${view === x ? "border-gold/60 bg-gold/15 text-gold" : "border-line text-muted hover:text-ink"}`}>
            {x === "board" ? "📈 Live board" : "📒 Journal (paper trades)"}
          </button>
        ))}
      </div>
      {view === "board" ? <><SupertrendTrade /><SupertrendAuto /><SupertrendPaper /><Board /></> : <SupertrendJournal />}
    </div>
  );
}

function Board() {
  const [b, setB] = useState<SupertrendBoard | null>(null);
  const [filter, setFilter] = useState<Filter>("BOTH");
  const [showAll, setShowAll] = useState(false);   // owner 2026-11-14: trade from Entries; this board is reference only
  const [checked, setChecked] = useState<string>("");

  useEffect(() => {
    const load = () => getBoard().then((x) => {
      setB(x);
      setChecked(new Date().toLocaleTimeString("en-IN", { hour12: false, timeZone: "Asia/Kolkata" }));
    }).catch(() => {});
    // browsers pause timers on hidden tabs / a locked phone: re-check the moment the page is looked at again
    const onShow = () => { if (document.visibilityState === "visible") void load(); };
    void load();
    const id = setInterval(load, 10000);   // the endpoint only reads a saved file, so a short interval is cheap
    document.addEventListener("visibilitychange", onShow);
    window.addEventListener("focus", onShow);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", onShow);
      window.removeEventListener("focus", onShow);
    };
  }, []);

  const today = b?.bar ? day(b.bar) : "";
  // 09:09 until the first scan the rows are still last session's: show today's auction opens instead of its opens
  const preOpens = b?.preopen?.opens && today < b.preopen.day ? b.preopen.opens : null;
  const rows = (b?.rows ?? []).filter((r) =>
    filter === "ALL" ? true : filter === "BOTH" ? r.agree : !!r.since && day(r.since) === today);
  if (filter === "BOTH")   // newest agreement first; "agreed before the history" last
    rows.sort((x, y) => (y.agree_since ?? "").localeCompare(x.agree_since ?? "") || x.symbol.localeCompare(y.symbol));
  const bothUp = b?.rows.filter((r) => r.agree && r.trend === "UP").length ?? 0;
  const bothDown = b?.rows.filter((r) => r.agree && r.trend === "DOWN").length ?? 0;
  const up = b?.rows.filter((r) => r.trend === "UP").length ?? 0;
  const down = b?.rows.filter((r) => r.trend === "DOWN").length ?? 0;
  const flippedToday = b?.rows.filter((r) => r.since && day(r.since) === today).length ?? 0;

  return (
    <div className="space-y-4">
      {showAll && <div className="rounded-md border border-gold/25 bg-gold/[0.05] px-4 py-2.5 font-mono text-[10px] leading-relaxed text-muted">
        📈 SUPERTREND BOARD — <span className="text-ink/80">{b?.setting ?? "Supertrend(10,3) on 5-minute candles"}</span>, on the stock / index
        price, same as your Kite chart. Updated after every closed 5-minute candle (about 2 min later); this page re-checks every 10 s and whenever you come back to it; flips from 14:00 are greyed out (in the real-option test they lost money). Your phone is alerted only for signals your rules TAKE (Entries, top of this tab).
        <span className="text-[var(--green)]"> UP</span> = price above the line (CE side), <span className="text-[var(--red)]">DOWN</span> = below
        (PE side). The line is where the trend would flip back: a natural stop. A heads-up screen, not advice.
      </div>}

      <div className="panel space-y-3 rounded-lg p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="font-display text-base font-bold text-ink">
            📈 All {b?.rows.length ?? ""} instruments <span className="font-mono text-[11px] font-normal text-muted">(reference, not signals: trade only from Entries above)</span>{" "}
            <span className="font-mono text-[11px] font-normal text-muted">
              — both agree: <span className="text-[var(--green)]">{bothUp} UP</span> · <span className="text-[var(--red)]">{bothDown} DOWN</span>
              {" "}(5 min alone: {up} UP · {down} DOWN · {flippedToday} flipped today)
            </span>
          </h2>
          <div className="flex gap-1 font-mono text-[11px]">
            {showAll && (["BOTH", "ALL", "TODAY"] as Filter[]).map((f) => (
              <button key={f} onClick={() => setFilter(f)}
                className={`rounded border px-3 py-1 ${filter === f ? "border-gold/60 bg-gold/15 text-gold" : "border-line text-muted hover:text-ink"}`}>
                {f === "BOTH" ? "5m + 15m agree" : f === "TODAY" ? "5m flipped today" : f === "ALL" ? "All" : `5m ${f}`}
              </button>
            ))}
            <button onClick={() => setShowAll(!showAll)} aria-expanded={showAll}
              className="rounded border border-line px-3 py-1 text-muted hover:text-ink">{showAll ? "Hide ▴" : "Show ▾"}</button>
          </div>
        </div>

        {!b ? (
          <p className="font-mono text-[11px] text-muted">Loading…</p>
        ) : !b.bar ? (
          <p className="font-mono text-[11px] text-gold">
            ⚠ No scan yet — the first one runs after the 09:15–09:20 candle closes on a trading day (Kite must be connected on System Check).
          </p>
        ) : (
          <>
            <div className="font-mono text-[10px] text-muted">
              ● {b.market_open ? "live" : "market closed — last scan"} · candle {hhmm(b.bar)}–{closeTime(b.bar)} on {day(b.bar)} · {b.rows.length} instruments · page checked {checked} (every 10 s)
              {b.errors && Object.keys(b.errors).length > 0 && (
                <span className="text-gold"> · {Object.keys(b.errors).length} not available: {Object.keys(b.errors).slice(0, 5).join(", ")}</span>
              )}
              {showAll && <><br />Times are today unless a date is shown · <span className="text-gold">gold</span> = 5m and 15m started agreeing today ·
              greyed = 5m flip after {LAST_ENTRY}, no new entry (listed last)</>}
            </div>
            {showAll && b.preopen && (
              <div className="rounded-md border border-gold/40 bg-gold/[0.05] px-3 py-2 font-mono text-[11px]">
                <div className="mb-1 text-[10px] text-muted">
                  🔔 PRE-OPEN CHECK {hhmm(b.preopen.at)} — {b.preopen.rows.length} of {b.preopen.priced} open across their 5m line,
                  so the 09:15–09:20 candle may flip them. A forecast: confirmed (or not) by the first scan at about 09:22.
                </div>
                {(["UP", "DOWN"] as const).map((t) => {
                  const xs = b.preopen!.rows.filter((r) => r.may_turn === t);
                  return xs.length > 0 && (
                    <div key={t} className="leading-relaxed">
                      <span className="font-bold" style={{ color: tint(t) }}>{t === "UP" ? "▲ may turn UP" : "▼ may turn DOWN"} ({xs.length}):</span>{" "}
                      {xs.map((r) => (
                        <span key={r.symbol} className="mr-3 text-ink" title={`open ${r.open} vs line ${r.line.toFixed(2)}`}>
                          {r.symbol} <span className="text-muted">{r.open}</span> <span style={{ color: tint(t) }}>{r.gap_pct > 0 ? "+" : ""}{r.gap_pct.toFixed(1)}%</span>
                        </span>
                      ))}
                    </div>
                  );
                })}
                {b.preopen.rows.length === 0 && <div className="text-muted">No stock opens across its line.</div>}
              </div>
            )}
            {showAll && <div className="grid gap-4 xl:grid-cols-2">
              {(["UP", "DOWN"] as const).map((t) => {
                // stable sort: keeps the filter's order, tradeable rows first
                const side = rows.filter((r) => r.trend === t).sort((x, y) => +isLate(x, today) - +isLate(y, today));
                return (
                  <div key={t} className="min-w-0 overflow-x-auto">
                    <h3 className="mb-1 font-mono text-[11px] font-bold" style={{ color: tint(t) }}>
                      {t === "UP" ? "▲ 5m UP (CE side)" : "▼ 5m DOWN (PE side)"} · {side.length}
                    </h3>
                    <table className="w-full whitespace-nowrap font-mono text-[11px]">
                      <thead className="text-left text-[10px] uppercase tracking-wide text-muted">
                        <tr>
                          <th className="py-1.5 pr-3">Symbol</th><th className="pr-3">5m since</th>
                          <th className="pr-3">15m since</th><th className="pr-3">Agree since</th>
                          <th className="pr-3 text-right">{preOpens ? "Open today" : "Open"}</th><th className="pr-3 text-right">Close</th><th className="pr-3 text-right">Stop (line)</th>
                          <th className="text-right">To stop</th>
                        </tr>
                      </thead>
                      <tbody>{side.map((r) => <Row key={r.symbol} r={r} today={today} open={preOpens ? preOpens[r.symbol] : r.open} />)}</tbody>
                    </table>
                    {side.length === 0 && <p className="py-3 font-mono text-[11px] text-muted">Nothing in this filter.</p>}
                  </div>
                );
              })}
            </div>}
          </>
        )}
      </div>
    </div>
  );
}

// today -> "15:15", another day -> "12 Nov 09:30"
const short = (iso: string, today: string, time: string) => day(iso) === today ? time :
  `${new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "Asia/Kolkata" })} ${time}`;
const when = (iso: string, today: string, min = 5) => short(iso, today, closeTime(iso, min));
const atLeast = (iso: string | null, today: string) => iso ? `≥ ${short(iso, today, "").trim() || "today"}` : "—";
const tint = (t: string | null) => (t === "UP" ? "var(--green)" : t === "DOWN" ? "var(--red)" : "var(--muted)");
// owner rule: a flip whose candle closed at/after 14:00 is not a new entry (real-option test: 23 % wins); no phone alert either
const isLate = (r: SupertrendRow, today: string) => !!r.since && day(r.since) === today && closeTime(r.since) >= LAST_ENTRY;

function Row({ r, today, open }: { r: SupertrendRow; today: string; open?: number }) {
  const color = tint(r.trend);
  const since = r.since ? when(r.since, today) : atLeast(r.since_at_least, today);
  const since15 = r.since_15m ? when(r.since_15m, today, 15) : atLeast(r.since_at_least_15m, today);
  const agree = !r.agree ? "conflict" : r.agree_since ? short(r.agree_since, today, hhmm(r.agree_since)) : "before history";
  const fresh = !!r.agree_since && day(r.agree_since) === today;
  const late = isLate(r, today);
  return (
    <tr className={`border-t border-line/50 ${late ? "opacity-40" : fresh ? "bg-gold/[0.04]" : ""}`}
      title={late ? `5-minute flip at ${closeTime(r.since!)}: after ${LAST_ENTRY}, no new entry` : undefined}>
      <td className="py-1.5 pr-3 font-semibold text-ink">{r.symbol}</td>
      <td className="pr-3 text-muted">{since}</td>
      <td className="pr-3 text-muted"><span className="font-bold" style={{ color: tint(r.trend_15m) }}>
        {r.trend_15m === "UP" ? "▲" : r.trend_15m === "DOWN" ? "▼" : "–"}</span> {since15}</td>
      <td className={`pr-3 ${fresh ? "text-gold" : r.agree ? "text-ink" : "text-muted"}`}>{agree}</td>
      <td className="pr-3 text-right text-muted">{open?.toFixed(2) ?? "—"}</td>
      <td className="pr-3 text-right text-ink">{r.close.toFixed(2)}</td>
      <td className="pr-3 text-right text-ink">{r.line.toFixed(2)}</td>
      <td className="text-right" style={{ color }}>{r.gap_pct > 0 ? "+" : ""}{r.gap_pct.toFixed(2)}%</td>
    </tr>
  );
}
