import { useEffect, useState } from "react";

type Status = "pending" | "pass" | "warn" | "fail";
interface CheckResult {
  name: string;
  critical: boolean;
  status: Status;
  detail: string;
}

// Each check probes one integration. `critical` checks gate go-live.
const CHECKS: {
  name: string;
  critical: boolean;
  run: () => Promise<{ status: Status; detail: string }>;
}[] = [
  {
    name: "Backend API",
    critical: true,
    run: async () => {
      const r = await fetch("/api/plumbing/status");
      return r.ok
        ? { status: "pass", detail: "Diagnostic server online" }
        : { status: "fail", detail: `HTTP ${r.status}` };
    },
  },
  {
    name: "Zerodha Kite connection",
    critical: false,
    run: async () => {
      const d = await (await fetch("/api/zerodha/config")).json();
      return d.is_connected
        ? { status: "pass", detail: `${d.data_source}` }
        : { status: "warn", detail: "Not connected — running on fallback data" };
    },
  },
  {
    name: "Live market data feed",
    critical: false,
    run: async () => {
      const d = await (await fetch("/api/strategy/recommendations")).json();
      return d.is_live
        ? { status: "pass", detail: d.data_source }
        : { status: "warn", detail: "Calibrated/simulated (live feed unavailable)" };
    },
  },
  {
    name: "Options pricing engine",
    critical: true,
    run: async () => {
      const d = await (
        await fetch("/api/options/pricing", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ spot: 24000, strike: 24000, days_to_expiry: 7, volatility: 0.15, option_type: "CALL" }),
        })
      ).json();
      return d.calculated_price != null
        ? { status: "pass", detail: `Black-Scholes OK (₹${d.calculated_price})` }
        : { status: "fail", detail: d.error || "engine unavailable" };
    },
  },
  {
    name: "Backtest engine",
    critical: true,
    run: async () => {
      const d = await (await fetch("/api/backtest/evaluate", { method: "POST" })).json();
      return d.total_score != null
        ? { status: "pass", detail: `Scored ${d.total_score}/${d.max_possible}` }
        : { status: "fail", detail: d.error || "engine unavailable" };
    },
  },
  {
    name: "Order validation plumbing",
    critical: true,
    run: async () => {
      const d = await (
        await fetch("/api/plumbing/validate-trade", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ symbol: "NIFTY", product: "NRML", order_type: "LIMIT", transaction_type: "BUY", quantity: 75, price: 140, is_option: true, available_margin: 1e7 }),
        })
      ).json();
      return typeof d.is_valid === "boolean"
        ? { status: d.is_valid ? "pass" : "warn", detail: d.is_valid ? "Validation passed" : "Validator returned errors" }
        : { status: "fail", detail: "no validation response" };
    },
  },
  {
    name: "Trade book / positions",
    critical: true,
    run: async () => {
      const r = await fetch(`/api/trade/positions?_t=${Date.now()}`);
      return r.ok
        ? { status: "pass", detail: "Trade book reachable" }
        : { status: "fail", detail: `HTTP ${r.status}` };
    },
  },
];

const DOT: Record<Status, string> = {
  pending: "bg-slate-600 animate-pulse",
  pass: "bg-emerald-500",
  warn: "bg-amber-500",
  fail: "bg-rose-500",
};

export function SystemCheck({ onClose, onGoLive }: { onClose: () => void; onGoLive?: () => void }) {
  const [results, setResults] = useState<CheckResult[]>(
    CHECKS.map((c) => ({ name: c.name, critical: c.critical, status: "pending", detail: "checking…" }))
  );
  const [done, setDone] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      for (let i = 0; i < CHECKS.length; i++) {
        let out: { status: Status; detail: string };
        try {
          out = await CHECKS[i].run();
        } catch (e) {
          out = { status: "fail", detail: e instanceof Error ? e.message : "error" };
        }
        if (cancelled) return;
        setResults((prev) => {
          const next = [...prev];
          next[i] = { ...next[i], ...out };
          return next;
        });
      }
      if (!cancelled) setDone(true);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const criticalFail = results.some((r) => r.critical && r.status === "fail");
  const anyWarn = results.some((r) => r.status === "warn");
  const kiteConnected = results.find((r) => r.name.includes("Kite"))?.status === "pass";
  const readyLive = done && !criticalFail && kiteConnected;

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-4 backdrop-blur-sm" onClick={onClose}>
      <div
        className="w-full max-w-lg rounded-2xl border border-slate-700 bg-slate-900 p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <h2 className="flex items-center gap-2 text-base font-bold text-white">⚡ System Check — Go-Live Pre-flight</h2>
          <button onClick={onClose} className="text-slate-500 hover:text-white">✕</button>
        </div>

        <ul className="mt-4 space-y-2">
          {results.map((r) => (
            <li key={r.name} className="flex items-center gap-3 rounded-lg bg-slate-800/40 px-3 py-2">
              <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${DOT[r.status]}`} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 text-sm text-slate-200">
                  {r.name}
                  {r.critical && <span className="text-[9px] font-bold uppercase text-slate-500">critical</span>}
                </div>
                <div className="truncate text-[11px] text-slate-500">{r.detail}</div>
              </div>
            </li>
          ))}
        </ul>

        <div className="mt-5 rounded-xl border p-3 text-xs"
          style={{
            borderColor: criticalFail ? "#f43f5e55" : readyLive ? "#22c55e55" : "#eab30855",
            background: criticalFail ? "#f43f5e11" : readyLive ? "#22c55e11" : "#eab30811",
          }}
        >
          {!done && "Running pre-flight checks…"}
          {done && criticalFail && "❌ Critical checks failed — resolve these before going live."}
          {done && !criticalFail && !kiteConnected && "⚠ Systems healthy, but Zerodha Kite isn't connected. Connect Kite to enable live trading."}
          {readyLive && anyWarn && "✅ Core systems healthy (some non-critical warnings). Ready to go live."}
          {readyLive && !anyWarn && "✅ All systems go. Ready to go live."}
        </div>

        <div className="mt-4 flex justify-end gap-2">
          <button onClick={onClose} className="rounded-lg bg-slate-700 px-4 py-2 text-xs font-bold text-slate-200 hover:bg-slate-600">
            Close
          </button>
          <button
            disabled={!readyLive}
            onClick={() => {
              onGoLive?.();
              onClose();
            }}
            className="rounded-lg bg-gradient-to-b from-emerald-500 to-emerald-600 px-4 py-2 text-xs font-bold text-white shadow disabled:cursor-not-allowed disabled:opacity-40"
          >
            🚀 Go Live
          </button>
        </div>
      </div>
    </div>
  );
}
