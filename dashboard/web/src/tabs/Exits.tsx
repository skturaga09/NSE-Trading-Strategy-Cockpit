import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import type { ExitConfig, ExitPosition, ThesisPosition } from "../types";

/* =============================================================================
   EXIT MONITOR — rule-based exit signals on your LIVE Kite positions + phone
   alerts. NOT discretionary advice: YOU set the thresholds, the monitor fires a
   mechanical signal when one is hit. A background job pushes new signals to your
   phone so you can act even when you're away from the screen.
============================================================================= */

const inr = (n: number) => `${n >= 0 ? "+" : "−"}₹${Math.abs(Math.round(n)).toLocaleString("en-IN")}`;
const SIG_COLOR: Record<string, string> = {
  STOP: "var(--red)", TIME: "var(--red)", TARGET: "var(--green)", TRAIL: "var(--gold)",
  PULLBACK: "var(--gold)", HOLD: "var(--muted)",
};
const SIG_EMOJI: Record<string, string> = { STOP: "🛑", TARGET: "🎯", TRAIL: "📉", TIME: "⏰", PULLBACK: "👀", HOLD: "·" };

export function Exits() {
  const { data } = useQuery({ queryKey: ["exits"], queryFn: api.getExitsStatus, refetchInterval: 3000 });
  const positions = data?.positions ?? [];
  const actionable = data?.actionable ?? [];

  return (
    <div className="space-y-6">
      <PnlDashboard positions={positions} ts={data?.timestamp} />

      <div className="rounded-md border border-gold/25 bg-gold/5 px-4 py-2.5 font-mono text-[10px] leading-relaxed text-muted">
        ⚖ Rule-based exit signals on your live positions — <span className="text-gold">not discretionary advice</span>. YOU set the
        thresholds below; the monitor fires a mechanical signal when one is hit (stop / target / trailing / time), and you decide.
        A background job pushes new signals to your phone. Educational only, not SEBI-registered advice.
      </div>

      {actionable.length > 0 && (
        <div className="rounded-lg border border-signalred/40 bg-signalred/[0.08] p-4">
          <div className="font-display text-sm font-bold text-signalred">⚠ {actionable.length} position(s) hit an exit rule</div>
          <div className="mt-2 space-y-1 font-mono text-[11px]">
            {actionable.map((p) => (
              <div key={p.symbol} style={{ color: SIG_COLOR[p.signal] }}>
                {SIG_EMOJI[p.signal]} <b>{p.signal}</b> · {p.symbol} · {p.pnl_pct >= 0 ? "+" : ""}{p.pnl_pct}% ({inr(p.pnl)}) — {p.reason}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="panel space-y-3 rounded-lg p-5">
        <h2 className="font-display text-base font-bold text-ink">
          🚪 Open positions <span className="font-mono text-[11px] font-normal text-muted">— {data?.timestamp ?? "loading…"} · live, polling 3s</span>
        </h2>
        {positions.length === 0 ? (
          <p className="font-mono text-[11px] text-muted">No open positions (or Kite not connected — check System Check).</p>
        ) : (
          <div className="overflow-x-auto rounded-md border border-line">
            <table className="w-full text-left text-xs">
              <thead className="bg-raised/50 font-mono text-[10px] uppercase tracking-wider text-muted">
                <tr>{["Symbol", "Qty", "Entry", "LTP", "P&L", "P&L %", "Peak %", "Signal"].map((h) => <th key={h} className="px-3 py-2">{h}</th>)}</tr>
              </thead>
              <tbody className="divide-y divide-line font-mono">
                {positions.map((p) => <PosRow key={p.symbol} p={p} />)}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <ThesisMonitor />

      <RulesConfig />
    </div>
  );
}

const TH_COLOR: Record<string, string> = {
  ALIGNED: "var(--green)", MIXED: "var(--gold)", DRIFT: "var(--red)", UNKNOWN: "var(--muted)",
};
const TH_EMOJI: Record<string, string> = { ALIGNED: "🟢", MIXED: "🟠", DRIFT: "🔴", UNKNOWN: "·" };

function ThesisMonitor() {
  const { data } = useQuery({ queryKey: ["thesis"], queryFn: api.getThesis, refetchInterval: 30000 });
  const rows = data?.positions ?? [];
  const drift = rows.filter((r) => r.status === "DRIFT");
  return (
    <div className="panel space-y-3 rounded-lg p-5">
      <h2 className="flex flex-wrap items-center gap-2 font-display text-base font-bold text-ink">
        🧭 Thesis-Drift Monitor <span className="font-mono text-[11px] font-normal text-muted">— does the underlying still agree with your bet? (30s · a nudge, not advice)</span>
      </h2>
      {rows.length === 0 ? (
        <p className="font-mono text-[11px] text-muted">{data && !data.is_live ? `Unavailable — ${data.source}` : "No open option positions to check."}</p>
      ) : (
        <>
          {drift.length > 0 && (
            <div className="rounded-md border border-signalred/30 bg-signalred/[0.06] px-3 py-2 font-mono text-[11px] text-signalred">
              ⚠ {drift.length} position(s) drifting — the underlying has turned against the bet: {drift.map((d) => d.symbol).join(", ")}
            </div>
          )}
          <div className="overflow-x-auto rounded-md border border-line">
            <table className="w-full text-left text-xs">
              <thead className="bg-raised/50 font-mono text-[10px] uppercase tracking-wider text-muted">
                <tr>{["Position", "Bet", "Underlying", "Day %", "vs VWAP", "OI buildup", "Agreement"].map((h) => <th key={h} className="px-3 py-2">{h}</th>)}</tr>
              </thead>
              <tbody className="divide-y divide-line font-mono">
                {rows.map((p) => <ThesisRow key={p.symbol} p={p} />)}
              </tbody>
            </table>
          </div>
          <p className="font-mono text-[9px] leading-relaxed text-muted">
            Agreement = how many of 3 objective signals (today's move, position vs day VWAP, futures OI buildup) still back your direction.
            🟢 aligned · 🟠 mixed · 🔴 drift (reason to hold has weakened). This flags where your entry thesis broke — it does <span className="text-gold">not</span> predict
            or say sell; you decide. DRIFT also pushes a phone nudge once (with the exit monitor armed).
          </p>
        </>
      )}
    </div>
  );
}

function ThesisRow({ p }: { p: ThesisPosition }) {
  const c = TH_COLOR[p.status];
  return (
    <tr style={{ background: p.status === "DRIFT" ? "color-mix(in srgb, var(--red) 7%, transparent)" : undefined }}>
      <td className="px-3 py-2 text-ink/90">{p.symbol}</td>
      <td className="px-3 py-2 text-muted">{p.direction}</td>
      <td className="px-3 py-2 text-ink/80">{p.underlying ?? "—"}</td>
      <td className="px-3 py-2 tnum" style={{ color: (p.day_pct ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>{p.day_pct === null ? "—" : `${p.day_pct >= 0 ? "+" : ""}${p.day_pct}%`}</td>
      <td className="px-3 py-2 tnum" style={{ color: (p.vs_vwap_pct ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>{p.vs_vwap_pct === null ? "—" : `${p.vs_vwap_pct >= 0 ? "+" : ""}${p.vs_vwap_pct}%`}</td>
      <td className="px-3 py-2 text-[10px]" style={{ color: p.lean === "bullish" ? "var(--green)" : p.lean === "bearish" ? "var(--red)" : "var(--muted)" }}>{p.buildup ?? "—"}</td>
      <td className="px-3 py-2">
        <span className="rounded px-2 py-0.5 font-bold uppercase text-[10px]" style={{ background: `color-mix(in srgb, ${c} 15%, transparent)`, color: c }}>
          {TH_EMOJI[p.status]} {p.status} {p.total > 0 ? `${p.agree}/${p.total}` : ""}
        </span>
      </td>
    </tr>
  );
}

function PnlDashboard({ positions, ts }: { positions: ExitPosition[]; ts?: string }) {
  const total = positions.reduce((s, p) => s + p.pnl, 0);
  const opts = positions.filter((p) => p.is_option);
  const optTotal = opts.reduce((s, p) => s + p.pnl, 0);
  const eqTotal = total - optTotal;
  const winners = positions.filter((p) => p.pnl > 0);
  const losers = positions.filter((p) => p.pnl < 0);
  const best = positions.reduce<ExitPosition | null>((b, p) => (!b || p.pnl > b.pnl ? p : b), null);
  const worst = positions.reduce<ExitPosition | null>((w, p) => (!w || p.pnl < w.pnl ? p : w), null);
  const grossWin = winners.reduce((s, p) => s + p.pnl, 0);
  const grossLoss = losers.reduce((s, p) => s + p.pnl, 0);

  const tile = (label: string, value: React.ReactNode, sub?: React.ReactNode, big?: boolean) => (
    <div className="rounded-md border border-line bg-raised/40 px-3 py-2.5">
      <div className="font-mono text-[9px] uppercase tracking-wider text-muted">{label}</div>
      <div className={`tnum font-bold ${big ? "text-2xl" : "text-base"}`}>{value}</div>
      {sub && <div className="mt-0.5 font-mono text-[10px] text-muted">{sub}</div>}
    </div>
  );

  return (
    <div className="panel space-y-3 rounded-lg p-5" style={{ borderColor: total >= 0 ? "color-mix(in srgb, var(--green) 30%, transparent)" : "color-mix(in srgb, var(--red) 30%, transparent)" }}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-display text-base font-bold text-ink">💰 P&amp;L Dashboard <span className="font-mono text-[11px] font-normal text-muted">— live across all open positions</span></h2>
        <span className="font-mono text-[10px] text-muted">{ts ?? "loading…"} · 3s</span>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {tile("Total open P&L", <span style={{ color: total >= 0 ? "var(--green)" : "var(--red)" }}>{inr(total)}</span>, `${positions.length} positions`, true)}
        {tile("Options P&L", <span style={{ color: optTotal >= 0 ? "var(--green)" : "var(--red)" }}>{inr(optTotal)}</span>, `${opts.length} F&O`)}
        {tile("Equity P&L", <span style={{ color: eqTotal >= 0 ? "var(--green)" : "var(--red)" }}>{inr(eqTotal)}</span>, `${positions.length - opts.length} cash`)}
        {tile("Winners / Losers", <span><span style={{ color: "var(--green)" }}>{winners.length}</span> / <span style={{ color: "var(--red)" }}>{losers.length}</span></span>,
          <span><span style={{ color: "var(--green)" }}>{inr(grossWin)}</span> / <span style={{ color: "var(--red)" }}>{inr(grossLoss)}</span></span>)}
        {tile("Best", best ? <span style={{ color: "var(--green)" }}>{inr(best.pnl)}</span> : "—", best?.symbol)}
        {tile("Worst", worst ? <span style={{ color: worst.pnl < 0 ? "var(--red)" : "var(--green)" }}>{inr(worst.pnl)}</span> : "—", worst?.symbol)}
      </div>
    </div>
  );
}

function PosRow({ p }: { p: ExitPosition }) {
  const on = p.signal !== "HOLD";
  return (
    <tr style={{ background: on ? `color-mix(in srgb, ${SIG_COLOR[p.signal]} 8%, transparent)` : undefined }}>
      <td className="px-3 py-2 text-ink/90">{p.symbol}</td>
      <td className="px-3 py-2 tnum text-muted">{p.qty}</td>
      <td className="px-3 py-2 tnum text-muted">{p.entry}</td>
      <td className="px-3 py-2 tnum text-ink">{p.ltp}</td>
      <td className="px-3 py-2 tnum font-bold" style={{ color: p.pnl >= 0 ? "var(--green)" : "var(--red)" }}>{inr(p.pnl)}</td>
      <td className="px-3 py-2 tnum" style={{ color: p.pnl_pct >= 0 ? "var(--green)" : "var(--red)" }}>{p.pnl_pct >= 0 ? "+" : ""}{p.pnl_pct}%</td>
      <td className="px-3 py-2 tnum text-muted">{p.peak_pct >= 0 ? "+" : ""}{p.peak_pct}%</td>
      <td className="px-3 py-2">
        <span className="rounded px-2 py-0.5 font-bold uppercase text-[10px]" style={{ background: `color-mix(in srgb, ${SIG_COLOR[p.signal]} 15%, transparent)`, color: SIG_COLOR[p.signal] }} title={p.reason}>
          {SIG_EMOJI[p.signal]} {p.signal}
        </span>
      </td>
    </tr>
  );
}

function RulesConfig() {
  const [cfg, setCfg] = useState<ExitConfig | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => { api.getExitConfig().then(setCfg).catch(() => {}); }, []);
  if (!cfg) return null;

  const num = (k: keyof ExitConfig) => (
    <label className="block">
      <span className="font-mono text-[9px] uppercase tracking-wider text-muted">{LABEL[k]}</span>
      <input value={String(cfg[k] as number)} onChange={(e) => setCfg({ ...cfg, [k]: Number(e.target.value) || 0 })} inputMode="decimal"
        className="mt-1 w-full rounded-md border border-line bg-bg/60 px-2.5 py-1.5 font-mono text-xs text-ink outline-none focus:border-cyan/50" />
    </label>
  );

  const save = async () => {
    setSaving(true); setMsg(null);
    try { setCfg(await api.setExitConfig(cfg)); setMsg("✅ Saved."); }
    catch (e) { setMsg("⚠ " + (e instanceof Error ? e.message : "save failed")); }
    finally { setSaving(false); }
  };
  const test = async () => {
    setMsg("Sending test alert…");
    const r = await api.testExitAlert();
    setMsg(r.success ? `✅ Test sent via ${r.channel}. Check your phone.` : `⚠ ${r.message ?? "not configured"}`);
  };
  const summary = async () => {
    setMsg("Sending portfolio summary…");
    const r = await api.sendExitSummary();
    setMsg(r.success ? `✅ Summary sent via ${r.channel}. Check your phone.` : `⚠ ${r.message ?? "no positions / not configured"}`);
  };

  return (
    <div className="panel space-y-4 rounded-lg p-5">
      <h2 className="font-display text-base font-bold text-ink">⚙ Exit rules &amp; phone alerts</h2>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        {num("target_pct")}{num("stop_pct")}{num("trail_pct")}{num("trail_arm_pct")}
        <label className="block">
          <span className="font-mono text-[9px] uppercase tracking-wider text-muted">Time exit (HH:MM, blank=off)</span>
          <input value={cfg.time_exit} onChange={(e) => setCfg({ ...cfg, time_exit: e.target.value })} placeholder="15:15"
            className="mt-1 w-full rounded-md border border-line bg-bg/60 px-2.5 py-1.5 font-mono text-xs text-ink outline-none focus:border-cyan/50" />
        </label>
        <label className="block">
          <span className="font-mono text-[9px] uppercase tracking-wider text-muted">Portfolio summary every (min, 0=off)</span>
          <input value={String(cfg.summary_every_min)} onChange={(e) => setCfg({ ...cfg, summary_every_min: Number(e.target.value) || 0 })} inputMode="numeric"
            className="mt-1 w-full rounded-md border border-line bg-bg/60 px-2.5 py-1.5 font-mono text-xs text-ink outline-none focus:border-cyan/50" />
        </label>
      </div>

      {/* Profit ratchet + peak-pullback heads-up */}
      <div className="rounded-md border border-line bg-raised/30 p-3">
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={cfg.ratchet_enabled} onChange={(e) => setCfg({ ...cfg, ratchet_enabled: e.target.checked })} className="accent-cyan" />
          <span className="font-mono text-[11px] font-bold text-ink">📈 Profit ratchet — tighten the trail as profit grows</span>
        </label>
        {cfg.ratchet_enabled ? (
          <>
            <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-3">
              {cfg.ratchet_tiers.map((t, i) => (
                <div key={i} className="flex items-center gap-1.5 rounded border border-line bg-bg/40 px-2 py-1.5 font-mono text-[10px]">
                  <span className="text-muted">above</span>
                  <input value={String(t.above)} onChange={(e) => { const tiers = [...cfg.ratchet_tiers]; tiers[i] = { ...t, above: Number(e.target.value) || 0 }; setCfg({ ...cfg, ratchet_tiers: tiers }); }}
                    className="w-12 rounded border border-line bg-bg/60 px-1 py-0.5 tnum text-ink outline-none focus:border-cyan/50" />
                  <span className="text-muted">% → trail</span>
                  <input value={String(t.trail)} onChange={(e) => { const tiers = [...cfg.ratchet_tiers]; tiers[i] = { ...t, trail: Number(e.target.value) || 0 }; setCfg({ ...cfg, ratchet_tiers: tiers }); }}
                    className="w-12 rounded border border-line bg-bg/60 px-1 py-0.5 tnum text-gold outline-none focus:border-cyan/50" />
                  <span className="text-muted">%</span>
                </div>
              ))}
            </div>
            <p className="mt-1.5 font-mono text-[9px] leading-relaxed text-muted">
              Once profit clears a tier's "above" level, the trail exits on that "trail" give-back from the peak. Bigger runners get room
              early, then are protected hard near the top. E.g. a +35% peak (in the +25% tier, 8% trail) exits near +27% instead of round-tripping.
            </p>
          </>
        ) : (
          <p className="mt-1.5 font-mono text-[9px] text-muted">Ratchet off — the flat Trail % / arms-after fields above are used instead.</p>
        )}
        <label className="mt-2 block sm:w-1/2">
          <span className="font-mono text-[9px] uppercase tracking-wider text-muted">Peak-pullback heads-up % (0=off)</span>
          <input value={String(cfg.pullback_alert_pct)} onChange={(e) => setCfg({ ...cfg, pullback_alert_pct: Number(e.target.value) || 0 })} inputMode="decimal"
            className="mt-1 w-full rounded-md border border-line bg-bg/60 px-2.5 py-1.5 font-mono text-xs text-ink outline-none focus:border-cyan/50" />
          <span className="mt-1 block font-mono text-[9px] text-muted">👀 A nudge when a winner first gives back this much from its peak — the early warning before the full trail exit.</span>
        </label>
      </div>

      <div className="rounded-md border border-line bg-raised/30 p-3">
        <div className="font-mono text-[11px] font-bold text-ink">📱 Mobile alerts</div>
        <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-3">
          <label className="block">
            <span className="font-mono text-[9px] uppercase tracking-wider text-muted">Channel</span>
            <select value={cfg.notify.channel} onChange={(e) => setCfg({ ...cfg, notify: { ...cfg.notify, channel: e.target.value as ExitConfig["notify"]["channel"] } })}
              className="mt-1 w-full rounded-md border border-line bg-bg/60 px-2.5 py-1.5 font-mono text-xs text-ink outline-none focus:border-cyan/50">
              <option value="none">None</option>
              <option value="ntfy">ntfy.sh (simplest)</option>
              <option value="telegram">Telegram bot</option>
            </select>
          </label>
          {cfg.notify.channel === "ntfy" && (
            <label className="block sm:col-span-2">
              <span className="font-mono text-[9px] uppercase tracking-wider text-muted">ntfy topic (a secret word)</span>
              <input value={cfg.notify.ntfy_topic} onChange={(e) => setCfg({ ...cfg, notify: { ...cfg.notify, ntfy_topic: e.target.value } })} placeholder="e.g. nse-exits-8f3k2"
                className="mt-1 w-full rounded-md border border-line bg-bg/60 px-2.5 py-1.5 font-mono text-xs text-ink outline-none focus:border-cyan/50" />
            </label>
          )}
          {cfg.notify.channel === "telegram" && (
            <>
              <label className="block"><span className="font-mono text-[9px] uppercase tracking-wider text-muted">Bot token</span>
                <input value={cfg.notify.telegram_token} onChange={(e) => setCfg({ ...cfg, notify: { ...cfg.notify, telegram_token: e.target.value } })}
                  className="mt-1 w-full rounded-md border border-line bg-bg/60 px-2.5 py-1.5 font-mono text-xs text-ink outline-none focus:border-cyan/50" /></label>
              <label className="block"><span className="font-mono text-[9px] uppercase tracking-wider text-muted">Chat id</span>
                <input value={cfg.notify.telegram_chat_id} onChange={(e) => setCfg({ ...cfg, notify: { ...cfg.notify, telegram_chat_id: e.target.value } })}
                  className="mt-1 w-full rounded-md border border-line bg-bg/60 px-2.5 py-1.5 font-mono text-xs text-ink outline-none focus:border-cyan/50" /></label>
            </>
          )}
        </div>
        <p className="mt-2 font-mono text-[9px] leading-relaxed text-muted">
          {cfg.notify.channel === "ntfy"
            ? "Install the ntfy app (iOS/Android), open it, and subscribe to your topic (any hard-to-guess word). Alerts posted to ntfy.sh/<topic> land on your phone. Anyone who knows the topic can post to it — keep it secret."
            : cfg.notify.channel === "telegram"
            ? "In Telegram: message @BotFather → /newbot → copy the token. Then message your bot once and get your chat id from @userinfobot. Both are needed."
            : "Pick a channel to get exit signals pushed to your phone when you're away from the screen."}
          {"  "}Your trade data is sent to the chosen service — keep credentials private.
        </p>
        <label className="mt-2 block">
          <span className="font-mono text-[9px] uppercase tracking-wider text-muted">“Open Kite” link (tap target)</span>
          <input value={cfg.kite_link} onChange={(e) => setCfg({ ...cfg, kite_link: e.target.value })} placeholder="https://kite.zerodha.com/positions"
            className="mt-1 w-full rounded-md border border-line bg-bg/60 px-2.5 py-1.5 font-mono text-xs text-ink outline-none focus:border-cyan/50" />
          <span className="mt-1 block font-mono text-[9px] leading-relaxed text-muted">
            On iPhone with the Kite app installed, this Universal Link should open the app (iOS routes kite.zerodha.com to it). If it opens Safari
            instead, that's Zerodha's Universal-Links setup — paste a scheme here if you find one that opens the app.
          </span>
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <button onClick={save} disabled={saving} className="rounded-md border border-cyan/50 bg-cyan/15 px-4 py-2 font-mono text-xs font-bold text-cyan hover:bg-cyan/25 disabled:opacity-50">{saving ? "Saving…" : "Save rules"}</button>
        <button onClick={test} className="rounded-md border border-gold/50 bg-gold/15 px-4 py-2 font-mono text-xs font-bold text-gold hover:bg-gold/25">Send test alert</button>
        <button onClick={summary} className="rounded-md border border-gold/50 bg-gold/15 px-4 py-2 font-mono text-xs font-bold text-gold hover:bg-gold/25">Send summary now</button>
        {msg && <span className="font-mono text-[11px] text-muted">{msg}</span>}
      </div>
      <p className="font-mono text-[9px] text-muted">Background pushes need the exit-monitor job installed (dashboard/scripts). Signals are mechanical rule triggers you set — the decision to exit stays yours.</p>
    </div>
  );
}

const LABEL: Record<string, string> = {
  target_pct: "Target % (take profit)",
  stop_pct: "Stop % (cut loss)",
  trail_pct: "Trail % (give-back from peak)",
  trail_arm_pct: "Trail arms after +%",
};
