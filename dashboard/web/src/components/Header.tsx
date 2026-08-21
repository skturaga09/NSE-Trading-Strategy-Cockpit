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
    <header className="sticky top-0 z-30 border-b border-line bg-[color:var(--bg)]/85 backdrop-blur-md">
      <div className="mx-auto flex w-full max-w-[1400px] flex-wrap items-center gap-3 px-4 py-3 sm:px-6">
        {/* Brand */}
        <div className="flex items-center gap-3">
          <div className="grid h-9 w-9 place-items-center rounded-md border border-gold/40 bg-gold/10 font-display text-lg font-extrabold text-gold">
            ₹
          </div>
          <div>
            <h1 className="font-display text-[15px] font-extrabold leading-none text-ink">
              NSE <span className="text-gold">TERMINAL</span>
            </h1>
            <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.2em] text-muted">
              cockpit · multi-strategy
            </p>
          </div>
        </div>

        <div className="ml-auto flex flex-wrap items-center gap-2 font-mono text-xs">
          {/* Market health readout */}
          <div className="flex items-center gap-2 rounded-md border border-line bg-panel px-3 py-1.5">
            <span className="uppercase tracking-wider text-muted">HEALTH</span>
            <span className="font-bold tnum" style={{ color: c }}>{mh?.score ?? "—"}</span>
            <span className="text-muted">/100</span>
            {data && (
              <span className="flex items-center gap-1 text-[10px] font-bold" style={{ color: data.is_live ? "var(--green)" : "var(--gold)" }}>
                <span className="pip h-1.5 w-1.5 rounded-full" style={{ background: "currentColor" }} />
                {data.is_live ? "LIVE" : "SIM"}
              </span>
            )}
          </div>

          {/* Execution mode */}
          <div className="flex items-center gap-1 rounded-md border border-line bg-panel p-1">
            {(["mock", "live"] as const).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={`rounded px-2.5 py-1 font-bold uppercase tracking-wider transition ${
                  mode === m
                    ? m === "live"
                      ? "bg-signalred/20 text-signalred"
                      : "bg-gold/20 text-gold"
                    : "text-muted hover:text-ink"
                }`}
              >
                {m}
              </button>
            ))}
          </div>

          <button
            onClick={() => setCheckOpen(true)}
            className="rounded-md border border-cyan/40 bg-cyan/10 px-3 py-1.5 font-bold uppercase tracking-wider text-cyan transition hover:bg-cyan/20"
          >
            ⟐ System Check
          </button>
        </div>
      </div>

      {checkOpen && <SystemCheck onClose={() => setCheckOpen(false)} onGoLive={() => setMode("live")} />}
    </header>
  );
}
