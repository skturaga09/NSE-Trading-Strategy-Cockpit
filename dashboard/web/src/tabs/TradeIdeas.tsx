import { useMutation } from "@tanstack/react-query";
import { api } from "../api";
import { useRecommendations, biasColor } from "../hooks";
import { useMode } from "../App";
import { useToast } from "../components/Toast";
import type { TradeIdea } from "../types";

function convColor(c: number): string {
  if (c >= 85) return "#22c55e";
  if (c >= 70) return "#38bdf8";
  if (c >= 55) return "#eab308";
  return "#f43f5e";
}

function dirColor(dir: string): string {
  if (dir === "LONG" || dir === "BULLISH") return "#22c55e";
  if (dir === "BEARISH") return "#f43f5e";
  return "#eab308";
}

export function TradeIdeas() {
  const { data, isLoading, isError, refetch, isFetching } = useRecommendations();
  const { mode } = useMode();
  const toast = useToast();

  const place = useMutation({
    mutationFn: api.placeTrade,
    onSuccess: (res, req) => {
      if (res.success) {
        toast.push(`✅ ${mode.toUpperCase()} order placed\nBUY ${req.quantity} ${req.symbol} @ ₹${req.price}\nOrder ${res.order_id ?? ""}`, "success");
      } else {
        toast.push(`❌ Rejected: ${res.message ?? "validation failed"}${res.errors?.length ? "\n• " + res.errors.join("\n• ") : ""}`, "error");
      }
    },
    onError: () => toast.push("❌ Network error placing order.", "error"),
  });

  function tradeNow(idea: TradeIdea) {
    const qty = idea.qty ?? idea.suggested_qty ?? 1;
    if (mode === "live" && !confirm(`LIVE ORDER\n\nBUY ${qty} ${idea.symbol} @ ₹${idea.entry_price}\nSL ₹${idea.stop_loss} · Target ₹${idea.target}\n\nPlace now?`)) return;
    place.mutate({
      mode,
      symbol: idea.symbol,
      quantity: qty,
      price: idea.entry_price!,
      stop_loss_price: idea.stop_loss,
      target_price: idea.target,
      is_option: !!idea.is_option,
      product: idea.product ?? (idea.is_option ? "NRML" : "CNC"),
      order_type: "LIMIT",
      transaction_type: idea.transaction_type ?? "BUY",
      strategy_origin: "Trend Trade Ideas",
      available_margin: 1e7,
    });
  }

  if (isLoading) return <SkeletonGrid />;
  if (isError || !data) return <div className="glass-panel rounded-2xl p-8 text-center text-sm text-rose-300">Failed to load ideas. Is the backend on :8080 running?</div>;

  const bias = data.market_bias;
  const mh = data.market_health;
  const c = biasColor(bias.bias);

  return (
    <div className="space-y-5">
      {/* Bias banner */}
      <div
        className="relative overflow-hidden rounded-2xl border border-slate-800 p-6"
        style={{ background: `radial-gradient(120% 140% at 0% 0%, ${c}22, transparent 60%), rgb(15 23 42 / .7)` }}
      >
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-3xl font-black tracking-tight" style={{ color: c }}>{bias.bias}</span>
          <span className="font-mono text-sm text-slate-400">{bias.score} / 100</span>
          <span className="rounded-full px-2 py-0.5 text-[10px] font-bold"
            style={{ background: data.is_live ? "#22c55e22" : "#eab30822", color: data.is_live ? "#22c55e" : "#eab308" }}>
            {data.is_live ? "● LIVE" : "SIMULATED"}
          </span>
          <button onClick={() => refetch()} disabled={isFetching}
            className="ml-auto rounded-lg bg-slate-800 px-3 py-1.5 text-xs font-bold text-slate-200 hover:bg-slate-700 disabled:opacity-50">
            {isFetching ? "Refreshing…" : "↻ Refresh"}
          </button>
        </div>
        <p className="mt-2 text-sm text-slate-300">{data.headline}</p>
        {mh?.nifty_last != null && (
          <p className="mt-1 font-mono text-[11px] text-slate-400">
            Nifty {mh.nifty_last} · 50DMA {mh.nifty_50dma ?? "—"} · 200DMA {mh.nifty_200dma ?? "—"}
          </p>
        )}
        <div className="mt-3 flex flex-wrap gap-2">
          {bias.drivers.map((d, i) => (
            <span key={i} className="rounded-full bg-slate-800/80 px-2.5 py-1 text-[10px] text-slate-300">{d}</span>
          ))}
        </div>
        <div className="mt-2 text-[10px] text-slate-500">
          {data.data_source}{data.as_of ? ` · as of ${data.as_of}` : ""} · generated {data.generated_at}
        </div>
      </div>

      {/* Idea cards */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {data.ideas.map((idea) => {
          const dc = dirColor(idea.direction);
          const hasLevels = idea.entry_price != null && idea.stop_loss != null && idea.target != null;
          const qty = idea.qty ?? idea.suggested_qty;
          return (
            <div key={`${idea.type}-${idea.symbol}-${idea.rank}`}
              className="group rounded-2xl border border-slate-800 bg-slate-900/70 p-5 transition-all hover:-translate-y-0.5 hover:border-slate-700 hover:shadow-xl hover:shadow-black/30"
              style={{ borderLeft: `3px solid ${dc}` }}>
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-400">#{idea.rank}</span>
                    <span className="text-sm font-bold text-white">{idea.symbol}</span>
                    <span className="rounded px-1.5 py-0.5 text-[10px] font-semibold" style={{ background: `${dc}22`, color: dc }}>{idea.direction}</span>
                  </div>
                  <div className="mt-1 text-[11px] font-semibold text-slate-300">{idea.action}</div>
                </div>
                <div className="text-right">
                  <div className="text-[9px] text-slate-500">CONVICTION</div>
                  <div className="font-mono text-2xl font-black" style={{ color: convColor(idea.conviction) }}>{idea.conviction}</div>
                </div>
              </div>

              {hasLevels ? (
                <>
                  <div className="mt-3 grid grid-cols-3 gap-2 font-mono text-[11px]">
                    <Level label="ENTRY" value={idea.entry_price!} />
                    <Level label="STOP" value={idea.stop_loss!} />
                    <Level label="TARGET" value={idea.target!} />
                  </div>
                  {qty != null && (
                    <div className="mt-1 text-[10px] text-slate-500">Suggested qty: {qty}{idea.is_option ? " (1 lot)" : " shares"}</div>
                  )}
                  {idea.instrument && <div className="mt-1 text-[10px] text-slate-400">{idea.instrument}</div>}
                </>
              ) : (
                <div className="mt-3 text-[11px] text-slate-300">
                  <span className="text-slate-500">Instrument:</span> {idea.instrument}<br />
                  <span className="text-slate-500">Entry:</span> {idea.entry_zone}
                </div>
              )}

              <ul className="mt-3 list-inside list-disc space-y-1 text-[11px] text-slate-400">
                {idea.rationale.map((r, i) => <li key={i}>{r}</li>)}
              </ul>

              {idea.tradeable && hasLevels && (
                <div className="mt-3 flex items-center gap-2">
                  <button onClick={() => tradeNow(idea)} disabled={place.isPending}
                    className="flex-1 rounded-lg bg-gradient-to-b from-emerald-500 to-emerald-600 px-3 py-2 text-xs font-bold text-white shadow hover:from-emerald-400 disabled:opacity-50">
                    ⚡ Trade Now — BUY {qty} @ ₹{idea.entry_price}
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </div>
      <p className="text-[10px] italic text-slate-500">
        Ideas synthesized from market regime, FII/DII flows, breadth, and VCP setups. Educational research — not investment advice. Verify live prices before acting.
      </p>
    </div>
  );
}

function Level({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg bg-slate-800/60 p-2">
      <div className="text-[9px] text-slate-500">{label}</div>₹{value}
    </div>
  );
}

function SkeletonGrid() {
  return (
    <div className="space-y-5">
      <div className="h-32 animate-pulse rounded-2xl bg-slate-900/70" />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-52 animate-pulse rounded-2xl bg-slate-900/70" />
        ))}
      </div>
    </div>
  );
}
