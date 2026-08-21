import { useMutation } from "@tanstack/react-query";
import { motion } from "motion/react";
import { api } from "../api";
import { useRecommendations, biasColor } from "../hooks";
import { useMode } from "../App";
import { useToast } from "../components/Toast";
import type { TradeIdea } from "../types";

function convColor(c: number): string {
  if (c >= 85) return "var(--green)";
  if (c >= 70) return "var(--cyan)";
  if (c >= 55) return "var(--gold)";
  return "var(--red)";
}
function dirColor(dir: string): string {
  if (dir === "LONG" || dir === "BULLISH") return "var(--green)";
  if (dir === "BEARISH") return "var(--red)";
  return "var(--gold)";
}

const container = {
  hidden: {},
  show: { transition: { staggerChildren: 0.05, delayChildren: 0.1 } },
};
const item = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.4, ease: [0.22, 1, 0.36, 1] as const } },
};

export function TradeIdeas() {
  const { data, isLoading, isError, refetch, isFetching } = useRecommendations();
  const { mode } = useMode();
  const toast = useToast();

  const place = useMutation({
    mutationFn: api.placeTrade,
    onSuccess: (res, req) => {
      if (res.success)
        toast.push(`▲ ${mode.toUpperCase()} ORDER FILLED\nBUY ${req.quantity} ${req.symbol} @ ₹${req.price}\n${res.order_id ?? ""}`, "success");
      else
        toast.push(`✕ REJECTED: ${res.message ?? "validation failed"}${res.errors?.length ? "\n• " + res.errors.join("\n• ") : ""}`, "error");
    },
    onError: () => toast.push("✕ Network error placing order.", "error"),
  });

  function tradeNow(idea: TradeIdea) {
    const qty = idea.qty ?? idea.suggested_qty ?? 1;
    if (mode === "live" && !confirm(`LIVE ORDER\n\nBUY ${qty} ${idea.symbol} @ ₹${idea.entry_price}\nSL ₹${idea.stop_loss} · Target ₹${idea.target}\n\nPlace now?`)) return;
    place.mutate({
      mode, symbol: idea.symbol, quantity: qty, price: idea.entry_price!,
      stop_loss_price: idea.stop_loss, target_price: idea.target,
      is_option: !!idea.is_option, product: idea.product ?? (idea.is_option ? "NRML" : "CNC"),
      order_type: "LIMIT", transaction_type: idea.transaction_type ?? "BUY",
      strategy_origin: "Trend Trade Ideas", available_margin: 1e7,
    });
  }

  if (isLoading) return <SkeletonGrid />;
  if (isError || !data) return <div className="panel rounded-lg p-8 text-center font-mono text-sm text-signalred">✕ Feed down. Is the backend on :8080 up?</div>;

  const bias = data.market_bias;
  const mh = data.market_health;
  const c = biasColor(bias.bias);

  return (
    <div className="space-y-5">
      {/* Bias banner */}
      <motion.div
        initial={{ opacity: 0, y: -12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, ease: "easeOut" }}
        className="panel relative overflow-hidden rounded-lg p-6"
      >
        <div className="pointer-events-none absolute inset-0 opacity-70"
          style={{ background: `radial-gradient(120% 160% at 0% 0%, color-mix(in srgb, ${c} 16%, transparent), transparent 55%)` }} />
        <div className="relative">
          <div className="flex flex-wrap items-baseline gap-3">
            <span className="font-display text-4xl font-extrabold leading-none tracking-tight" style={{ color: c }}>{bias.bias}</span>
            <span className="font-mono text-sm text-muted tnum">{bias.score}<span className="text-muted/60">/100</span></span>
            <span className="flex items-center gap-1.5 font-mono text-[10px] font-bold uppercase tracking-widest" style={{ color: data.is_live ? "var(--green)" : "var(--gold)" }}>
              <span className="pip h-1.5 w-1.5 rounded-full" style={{ background: "currentColor" }} />{data.is_live ? "live feed" : "simulated"}
            </span>
            <button onClick={() => refetch()} disabled={isFetching}
              className="ml-auto rounded-md border border-line px-3 py-1.5 font-mono text-xs text-muted transition hover:border-gold/40 hover:text-gold disabled:opacity-50">
              {isFetching ? "↻ syncing" : "↻ refresh"}
            </button>
          </div>
          <p className="mt-2 max-w-3xl text-sm text-ink/80">{data.headline}</p>
          {mh?.nifty_last != null && (
            <p className="mt-2 font-mono text-[11px] text-muted">
              NIFTY <span className="text-ink tnum">{mh.nifty_last}</span>
              <span className="mx-2 text-line">│</span>50DMA <span className="tnum">{mh.nifty_50dma ?? "—"}</span>
              <span className="mx-2 text-line">│</span>200DMA <span className="tnum">{mh.nifty_200dma ?? "—"}</span>
            </p>
          )}
          <div className="mt-3 flex flex-wrap gap-1.5">
            {bias.drivers.map((d, i) => (
              <span key={i} className="rounded border border-line bg-raised/60 px-2 py-1 font-mono text-[10px] text-muted">{d}</span>
            ))}
          </div>
          {data.top_themes && data.top_themes.length > 0 && (
            <div className="mt-3 flex flex-wrap items-center gap-1.5">
              <span className="font-mono text-[9px] uppercase tracking-widest text-muted">
                leadership {data.themes_live ? "· live" : "· est"}
              </span>
              {data.top_themes.map((t, i) => (
                <span key={i} title={t.driver}
                  className="rounded border border-gold/25 bg-gold/5 px-2 py-1 font-mono text-[10px] text-gold">
                  {t.theme} <span className="text-gold-dim">{t.conviction}</span>
                </span>
              ))}
            </div>
          )}
          <div className="mt-2 font-mono text-[10px] text-muted/70">
            {data.data_source}{data.as_of ? ` · ${data.as_of}` : ""}
            {data.ideas_source ? ` · setups: ${data.ideas_source}` : ""}
          </div>
        </div>
      </motion.div>

      {/* Idea cards */}
      <motion.div variants={container} initial="hidden" animate="show" className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {data.ideas.map((idea) => {
          const dc = dirColor(idea.direction);
          const hasLevels = idea.entry_price != null && idea.stop_loss != null && idea.target != null;
          const qty = idea.qty ?? idea.suggested_qty;
          return (
            <motion.div key={`${idea.type}-${idea.symbol}-${idea.rank}`} variants={item}
              className="group relative overflow-hidden rounded-lg border border-line bg-panel p-5 transition-colors hover:border-[color:var(--gold)]/30"
              style={{ borderLeft: `2px solid ${dc}` }}>
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-[10px] text-muted">#{idea.rank}</span>
                    <span className="font-display text-base font-bold text-ink">{idea.symbol}</span>
                    <span className="rounded px-1.5 py-0.5 font-mono text-[10px] font-bold uppercase" style={{ background: `color-mix(in srgb, ${dc} 15%, transparent)`, color: dc }}>{idea.direction}</span>
                  </div>
                  <div className="mt-1 font-mono text-[11px] uppercase tracking-wide text-muted">{idea.action}</div>
                </div>
                <div className="text-right">
                  <div className="font-mono text-[9px] uppercase tracking-widest text-muted">conviction</div>
                  <div className="font-mono text-3xl font-bold tnum leading-none" style={{ color: convColor(idea.conviction) }}>{idea.conviction}</div>
                </div>
              </div>

              {hasLevels ? (
                <>
                  <div className="mt-4 grid grid-cols-3 gap-px overflow-hidden rounded-md border border-line font-mono">
                    <Level label="ENTRY" value={idea.entry_price!} tone="ink" />
                    <Level label="STOP" value={idea.stop_loss!} tone="red" />
                    <Level label="TARGET" value={idea.target!} tone="green" />
                  </div>
                  {qty != null && <div className="mt-1.5 font-mono text-[10px] text-muted">qty {qty}{idea.is_option ? " · 1 lot" : " sh"}{idea.instrument ? ` · ${idea.instrument}` : ""}</div>}
                </>
              ) : (
                <div className="mt-3 font-mono text-[11px] text-ink/70">{idea.instrument}<br /><span className="text-muted">{idea.entry_zone}</span></div>
              )}

              <ul className="mt-3 space-y-1 text-[11px] leading-relaxed text-muted">
                {idea.rationale.map((r, i) => <li key={i} className="flex gap-1.5"><span className="text-gold-dim">›</span>{r}</li>)}
              </ul>

              {idea.tradeable && hasLevels && (
                <button onClick={() => tradeNow(idea)} disabled={place.isPending}
                  className="mt-4 w-full rounded-md border border-gold/40 bg-gold/10 py-2 font-mono text-xs font-bold uppercase tracking-wider text-gold transition hover:bg-gold/20 disabled:opacity-50">
                  ⚡ Trade Now · BUY {qty} @ ₹{idea.entry_price}
                </button>
              )}
            </motion.div>
          );
        })}
      </motion.div>
      <p className="font-mono text-[10px] text-muted/70">
        Synthesized from regime · FII/DII flows · breadth · VCP setups. Research, not advice — verify live prices.
      </p>
    </div>
  );
}

function Level({ label, value, tone }: { label: string; value: number; tone: "ink" | "red" | "green" }) {
  const color = tone === "red" ? "var(--red)" : tone === "green" ? "var(--green)" : "var(--ink)";
  return (
    <div className="bg-raised/50 p-2.5">
      <div className="text-[9px] uppercase tracking-widest text-muted">{label}</div>
      <div className="tnum text-sm font-semibold" style={{ color }}>₹{value}</div>
    </div>
  );
}

function SkeletonGrid() {
  return (
    <div className="space-y-5">
      <div className="h-32 animate-pulse rounded-lg bg-panel" />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {Array.from({ length: 4 }).map((_, i) => <div key={i} className="h-52 animate-pulse rounded-lg bg-panel" />)}
      </div>
    </div>
  );
}
