import { createContext, useContext, useState } from "react";
import { Header } from "./components/Header";
import { TabNav, type TabId } from "./components/TabNav";
import { TradeIdeas } from "./tabs/TradeIdeas";
import { Plumbing } from "./tabs/Plumbing";
import { VcpScreener } from "./tabs/VcpScreener";
import { Options } from "./tabs/Options";
import { Backtest } from "./tabs/Backtest";
import { FnoPlanner } from "./tabs/FnoPlanner";

type Mode = "mock" | "live";
const ModeCtx = createContext<{ mode: Mode; setMode: (m: Mode) => void }>({
  mode: "mock",
  setMode: () => {},
});
export const useMode = () => useContext(ModeCtx);

export default function App() {
  const [tab, setTab] = useState<TabId>("ideas");
  const [mode, setMode] = useState<Mode>("mock");

  return (
    <ModeCtx.Provider value={{ mode, setMode }}>
      <div className="min-h-screen">
        <Header mode={mode} setMode={setMode} />
        <main className="mx-auto w-full max-w-[1400px] px-4 py-6 sm:px-6">
          <TabNav active={tab} onChange={setTab} />
          <div className="mt-6">
            {tab === "ideas" && <TradeIdeas />}
            {tab === "plumbing" && <Plumbing />}
            {tab === "vcp" && <VcpScreener />}
            {tab === "options" && <Options />}
            {tab === "fno" && <FnoPlanner />}
            {tab === "backtest" && <Backtest />}
          </div>
        </main>
      </div>
    </ModeCtx.Provider>
  );
}
