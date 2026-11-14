// F&O Engine tab: advisory and paper-trading only. Read-only over backend state, except the Phase 9 journal / feedback
// forms (stored only). Lazy-loaded by src/App.tsx; all styles and fonts load with this chunk and apply only inside the root.
import "@fontsource/inter/400.css";
import "@fontsource/inter/600.css";
import "@fontsource/jetbrains-mono/400.css";
import "./fo-engine.css";
import { useEffect, useMemo, useState } from "react";
import { useSessions, type View } from "./api";
import { Chip, FoRoot, ist } from "./core";
import { Radar } from "./panels/Radar";
import { Overview } from "./panels/Overview";
import { Positioning } from "./panels/Positioning";
import { OptionChain } from "./panels/OptionChain";
import { SignalDetail } from "./panels/SignalDetail";
import { Trades } from "./panels/Trades";
import { Performance } from "./panels/Performance";
import { Journal } from "./panels/Journal";
import { Health } from "./panels/Health";

const SECTIONS = [["overview", "Market"], ["radar", "Radar"], ["positioning", "Positioning"], ["chain", "Option chain"],
  ["signal", "Signal"], ["trades", "Trades"], ["performance", "Performance"], ["journal", "Journal"], ["health", "System"]] as const;
type Section = (typeof SECTIONS)[number][0];
const MIN = 60_000_000_000;

export default function FoEngineTab() {
  const s = useSessions();
  const sessions = useMemo(() => (s.data?.sessions ?? []).filter((x) => x.signals || x.dashboard || x.status), [s.data]);
  const [date, setDate] = useState<string | null>(null);
  const [asOf, setAsOf] = useState<number | null>(null);
  const [section, setSection] = useState<Section>("radar");
  const [signal, setSignal] = useState<string | null>(null);
  const sess = sessions.find((x) => x.date === date);
  const today = s.data?.today;

  useEffect(() => {                                   // default: the latest recorded session
    if (!date && sessions.length) setDate(sessions[sessions.length - 1].date);
  }, [sessions, date]);
  useEffect(() => {                                   // a past session can only be replayed; today may be live
    if (sess && sess.date !== today && asOf == null) setAsOf(sess.close_ns);
  }, [sess, today, asOf]);

  const view: View | null = date ? { date, asOf } : null;
  const live = asOf == null;

  return (
    <FoRoot>
      <div className="fo-flex fo-flex-wrap fo-items-center fo-gap-5 fo-pb-5">
        <div>
          <div className="fo-text-xl fo-font-semibold fo-tracking-tight">F&amp;O Engine</div>
          <div className="fo-text-2xs fo-uppercase fo-tracking-widest fo-text-muted">positioning hypotheses · advisory &amp; paper only · no order placement</div>
        </div>
        <div className="fo-ml-auto fo-flex fo-flex-wrap fo-items-center fo-gap-4 fo-text-xs">
          <label className="fo-flex fo-items-center fo-gap-3">session
            <select aria-label="session" value={date ?? ""} onChange={(e) => { setDate(e.target.value); setAsOf(null); }}
              className="fo-h-control fo-rounded-md fo-border fo-border-line fo-bg-raised fo-px-3 fo-num">
              {sessions.map((x) => <option key={x.date} value={x.date}>{x.date}</option>)}
            </select>
          </label>
          {sess && (
            <label className="fo-flex fo-items-center fo-gap-3">
              {live ? <Chip tone="ok">live</Chip> : <Chip tone="accent">replay</Chip>}
              <input aria-label="replay time" type="range" min={sess.open_ns / MIN} max={sess.close_ns / MIN} step={1}
                value={(asOf ?? sess.close_ns) / MIN} onChange={(e) => setAsOf(Number(e.target.value) * MIN)} disabled={live} />
              <span className="fo-num">{asOf ? `${ist(asOf)} IST` : "now"}</span>
              {sess.date === today && (
                <button onClick={() => setAsOf(live ? sess.close_ns : null)}
                  className="fo-h-control fo-cursor-pointer fo-rounded-md fo-border fo-border-line fo-bg-raised fo-px-4">
                  {live ? "replay" : "go live"}
                </button>)}
            </label>)}
        </div>
      </div>
      <nav aria-label="engine sections" className="fo-mb-5 fo-flex fo-flex-wrap fo-gap-2 fo-border-b fo-border-line">
        {SECTIONS.map(([id, label]) => (
          <button key={id} onClick={() => setSection(id)} aria-current={section === id ? "page" : undefined}
            className={`fo-cursor-pointer fo-border-0 fo-border-b-2 fo-border-solid fo-bg-transparent fo-px-5 fo-py-3 fo-text-sm ${
              section === id ? "fo-border-accent fo-font-semibold fo-text-ink" : "fo-border-transparent fo-text-muted"}`}>
            {label}
          </button>))}
      </nav>
      {!view ? <p className="fo-text-muted">{s.error ? `Backend error: ${String(s.error)}` : "Loading sessions…"}</p> : (
        <div className="fo-grid fo-gap-5">
          {section === "overview" && <Overview view={view} />}
          {section === "radar" && <Radar view={view} onOpen={(id) => { setSignal(id); setSection("signal"); }} />}
          {section === "positioning" && <Positioning view={view} />}
          {section === "chain" && <OptionChain view={view} />}
          {section === "signal" && <SignalDetail view={view} id={signal} onPick={setSignal} />}
          {section === "trades" && <Trades view={view} />}
          {section === "performance" && <Performance />}
          {section === "journal" && <Journal view={view} />}
          {section === "health" && <Health view={view} />}
        </div>)}
    </FoRoot>
  );
}
