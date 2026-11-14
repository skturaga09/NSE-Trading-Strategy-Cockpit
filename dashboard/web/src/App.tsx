import { createContext, lazy, Suspense, useContext, useEffect, useState } from "react";
import { Header } from "./components/Header";
import { TAB_IDS, TabNav, type TabId } from "./components/TabNav";
import { TradeIdeas } from "./tabs/TradeIdeas";
import { Plumbing } from "./tabs/Plumbing";
import { Journal } from "./tabs/Journal";
import { Intraday } from "./tabs/Intraday";
import { Swing } from "./tabs/Swing";
import { Radar } from "./tabs/Radar";
import { Supertrend } from "./tabs/Supertrend";
import { Commodities } from "./tabs/Commodities";
import { Exits } from "./tabs/Exits";
import { VcpScreener } from "./tabs/VcpScreener";
import { Options } from "./tabs/Options";
import { Backtest } from "./tabs/Backtest";
import { FnoPlanner } from "./tabs/FnoPlanner";
// F&O Engine dashboard: separate module and design system (fo-engine/), loaded only when its tab opens.
const FoEngineTab = lazy(() => import("../fo-engine/FoEngineTab"));

type Mode = "mock" | "live";
const ModeCtx = createContext<{
  mode: Mode; setMode: (m: Mode) => void;
  afterHours: boolean; setAfterHours: (b: boolean) => void;
}>({
  mode: "mock", setMode: () => {},
  afterHours: false, setAfterHours: () => {},
});
export const useMode = () => useContext(ModeCtx);

export default function App() {
  // the URL hash names the tab (#foengine), so a link or a reload opens the same tab
  const fromHash = () => TAB_IDS.find((t) => t === window.location.hash.slice(1)) ?? "intraday";
  const [tab, setTab] = useState<TabId>(fromHash);
  useEffect(() => { window.history.replaceState(null, "", `#${tab}`); }, [tab]);
  useEffect(() => {
    const onHash = () => setTab(fromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  const [mode, setMode] = useState<Mode>("mock");
  const [afterHours, setAfterHours] = useState(false);

  return (
    <ModeCtx.Provider value={{ mode, setMode, afterHours, setAfterHours }}>
      <div className="min-h-screen">
        <Header mode={mode} setMode={setMode} />
        <main className="mx-auto w-full max-w-[1400px] px-4 py-6 sm:px-6">
          <TabNav active={tab} onChange={setTab} />
          <div className="mt-6">
            {tab === "ideas" && <TradeIdeas />}
            {tab === "plumbing" && <Plumbing />}
            {tab === "journal" && <Journal />}
            {tab === "intraday" && <Intraday />}
            {tab === "swing" && <Swing />}
            {tab === "radar" && <Radar />}
            {tab === "supertrend" && <Supertrend />}
            {tab === "commodities" && <Commodities />}
            {tab === "exits" && <Exits />}
            {tab === "vcp" && <VcpScreener />}
            {tab === "options" && <Options />}
            {tab === "fno" && <FnoPlanner />}
            {tab === "backtest" && <Backtest />}
            {tab === "foengine" && <Suspense fallback={null}><FoEngineTab /></Suspense>}
          </div>
        </main>
      </div>
    </ModeCtx.Provider>
  );
}
