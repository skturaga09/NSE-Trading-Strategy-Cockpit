import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import type { ExitConfig, ExitPosition } from "../types";

/* =============================================================================
   EXIT MONITOR — rule-based exit signals on your LIVE Kite positions + phone
   alerts. NOT discretionary advice: YOU set the thresholds, the monitor fires a
   mechanical signal when one is hit. A background job pushes new signals to your
   phone so you can act even when you're away from the screen.
============================================================================= */

const inr = (n: number) => `${n >= 0 ? "+" : "−"}₹${Math.abs(Math.round(n)).toLocaleString("en-IN")}`;
const SIG_COLOR: Record<string, string> = {
  STOP: "var(--red)", TIME: "var(--red)", TARGET: "var(--green)", TRAIL: "var(--gold)", HOLD: "var(--muted)",
};
const SIG_EMOJI: Record<string, string> = { STOP: "🛑", TARGET: "🎯", TRAIL: "📉", TIME: "⏰", HOLD: "·" };

export function Exits() {
  const { data } = useQuery({ queryKey: ["exits"], queryFn: api.getExitsStatus, refetchInterval: 3000 });
  const positions = data?.positions ?? [];
  const actionable = data?.actionable ?? [];

  return (
    <div className="space-y-6">
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

      <RulesConfig />
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
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <button onClick={save} disabled={saving} className="rounded-md border border-cyan/50 bg-cyan/15 px-4 py-2 font-mono text-xs font-bold text-cyan hover:bg-cyan/25 disabled:opacity-50">{saving ? "Saving…" : "Save rules"}</button>
        <button onClick={test} className="rounded-md border border-gold/50 bg-gold/15 px-4 py-2 font-mono text-xs font-bold text-gold hover:bg-gold/25">Send test alert</button>
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
