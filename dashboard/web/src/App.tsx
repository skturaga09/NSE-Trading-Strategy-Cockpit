import { createContext, useContext, useState } from "react";
import { Header } from "./components/Header";
import { TabNav, type TabId } from "./components/TabNav";
import { TradeIdeas } from "./tabs/TradeIdeas";
import { Placeholder } from "./tabs/Placeholder";

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
      <div className="min-h-screen bg-slate-950">
        <Header mode={mode} setMode={setMode} />
        <main className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6">
          <TabNav active={tab} onChange={setTab} />
          <div className="mt-6">
            {tab === "ideas" && <TradeIdeas />}
            {tab === "plumbing" && <Placeholder title="Trade Plumbing & Orders" />}
            {tab === "vcp" && <Placeholder title="VCP Screener" />}
            {tab === "options" && <Placeholder title="Options & Greeks Engine" />}
            {tab === "fno" && <Placeholder title="Weekly F&O Planner" />}
            {tab === "backtest" && <Placeholder title="Backtest & Tax Friction" />}
          </div>
        </main>
      </div>
    </ModeCtx.Provider>
  );
}
