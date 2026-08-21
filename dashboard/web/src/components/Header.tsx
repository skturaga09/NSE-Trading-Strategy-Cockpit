import { useState } from "react";
import { useRecommendations, biasColor } from "../hooks";
import { SystemCheck } from "./SystemCheck";

export function Header({
  mode,
  setMode,
}: {
  mode: "mock" | "live";
  setMode: (m: "mock" | "live") => void;
}) {
  const { data } = useRecommendations();
  const mh = data?.market_health;
  const c = biasColor(data?.market_bias.bias);
  const [checkOpen, setCheckOpen] = useState(false);

  return (
    <header className="sticky top-0 z-30 border-b border-slate-800 bg-slate-950/80 backdrop-blur">
      <div className="mx-auto flex w-full max-w-7xl flex-wrap items-center gap-3 px-4 py-3 sm:px-6">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 text-lg shadow-lg shadow-indigo-900/40">
            📈
          </div>
          <div>
            <h1 className="text-sm font-extrabold leading-tight text-white">
              NSE Trading &amp; Strategy Cockpit
            </h1>
            <p className="text-[11px] text-slate-400">Zerodha Kite · Multi-Strategy Optimizer</p>
          </div>
        </div>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          {/* Live market health */}
          <div className="flex items-center gap-2 rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-1.5 text-xs">
            <span className="text-slate-400">Market Health</span>
            <span className="font-bold" style={{ color: c }}>
              {mh?.score ?? "—"} / 100
            </span>
            {data && (
              <span
                className="rounded-full px-1.5 py-0.5 text-[9px] font-bold"
                style={{
                  background: data.is_live ? "#22c55e22" : "#eab30822",
                  color: data.is_live ? "#22c55e" : "#eab308",
                }}
              >
                {data.is_live ? "● LIVE" : "SIM"}
              </span>
            )}
          </div>

          {/* Execution mode */}
          <div className="flex items-center gap-1 rounded-lg border border-slate-800 bg-slate-900/70 p-1 text-xs">
            {(["mock", "live"] as const).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={`rounded-md px-2.5 py-1 font-bold transition ${
                  mode === m
                    ? m === "live"
                      ? "bg-rose-600 text-white"
                      : "bg-slate-700 text-white"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                {m === "mock" ? "MOCK" : "LIVE"}
              </button>
            ))}
          </div>

          {/* System check / go-live pre-flight */}
          <button
            onClick={() => setCheckOpen(true)}
            className="rounded-lg bg-gradient-to-b from-emerald-500 to-emerald-600 px-3 py-1.5 text-xs font-bold text-white shadow-lg shadow-emerald-900/30 hover:from-emerald-400"
          >
            ⚡ System Check
          </button>
        </div>
      </div>

      {checkOpen && <SystemCheck onClose={() => setCheckOpen(false)} onGoLive={() => setMode("live")} />}
    </header>
  );
}
