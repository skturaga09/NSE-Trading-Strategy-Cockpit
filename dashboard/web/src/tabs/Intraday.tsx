import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { IntradayContext, OptionChain, OptionLeg } from "../types";

/* =============================================================================
   Intraday Index-Options DISCIPLINE CONSOLE  (NIFTY / BANKNIFTY, intraday only)
   A deterministic rules-enforcement engine — NOT an LLM, no invented data,
   educational conditional analysis only. You supply timestamped market inputs;
   it enforces the hard risk rules, the 14 pre-trade gates, market-regime
   classification, and transparent position sizing, then renders the A–G output.
   Highest priority: disciplined rejection of low-quality trades. A missed
   opportunity is acceptable; a rule violation is not. Defaults to NO TRADE.
   You are not a SEBI-registered adviser; you verify data and own execution.
============================================================================= */

const CAPITAL = 200_000;
const RISK_PER_TRADE = 1_000;   // 0.5% of capital
const DAILY_MAX_LOSS = 3_000;
const MAX_ENTRIES = 2;
const MAX_CONSEC_LOSS = 2;

type Gate = "PASS" | "FAIL" | "UNKNOWN";
type Verdict = "STOP_DAY" | "INSUFFICIENT_DATA" | "NO_TRADE" | "WAIT" | "CANDIDATE";

const SETUPS: Record<string, string> = {
  A: "Opening-Range Breakout & Retest",
  B: "Trend Pullback to VWAP",
  C: "Range-Bound Reversal",
};
const SETUP_HINT: Record<string, string> = {
  A: "5m close beyond OR high/low + rel-vol confirm + VWAP align; prefer retest, don't chase. Invalid on 5m close back inside range.",
  B: "15m & 5m aligned; HH/HL (long) or LL/LH (short); controlled pullback to VWAP; require confirmation candle. Reject if < 2R after costs.",
  C: "Only when range-bound & VWAP flat/crossed; define high/low/mid; trade boundary rejection; avoid midpoint; abort if rel-vol expands toward breakout.",
};

const REGIMES: [string, string][] = [
  ["trend", "1 · Trend day"],
  ["range", "2 · Range day"],
  ["orb", "3 · Opening-range breakout attempt"],
  ["event", "4 · High-volatility event day"],
  ["choppy", "5 · Low-volatility / choppy day"],
  ["unclear", "6 · Unclear / mixed regime"],
];

const GATE_LABELS = [
  "Market regime is clearly identified",
  "Candidate exactly matches one approved setup",
  "15-min & 5-min price structure supports the direction",
  "VWAP location and slope support the direction",
  "Relative volume confirms the trigger",
  "Defined S/R leaves distance for at least 2R after costs",
  "NIFTY/BANKNIFTY alignment or breadth does not materially conflict",
  "No high-impact scheduled event in the restricted window",
  "Option contract is liquid with acceptable bid-ask spread",
  "Underlying, premium, expiry, lot size, entry, stop & costs verified",
  "Max loss ≤ ₹1,000 including costs & slippage",
  "Daily P&L, entries & consecutive-loss count permit a new trade",
  "Documented backtest / paper sample in the SAME regime",
  "Defined entry trigger, invalidation, time stop, target & cancellation",
];
// Gates the engine derives (0-indexed): regime, sizing, daily-rules. Others = user judgment.
const AUTO = { REGIME: 0, SIZING: 10, DAILY: 11 };

const inr = (n: number) => `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
const nowIST = () => new Date().toLocaleString("en-IN", { timeZone: "Asia/Kolkata", hour12: false });
const num = (s: string): number | null => {
  if (s.trim() === "") return null;
  const v = Number(s);
  return Number.isFinite(v) ? v : null;
};

export function Intraday() {
  const [ist, setIst] = useState(nowIST());
  useEffect(() => {
    const id = setInterval(() => setIst(nowIST()), 1000);
    return () => clearInterval(id);
  }, []);

  // A · data / contract
  const [dataStatus, setDataStatus] = useState("user-supplied");
  const [underlying, setUnderlying] = useState("NIFTY");
  const [expiry, setExpiry] = useState("");
  const [spot, setSpot] = useState("");
  const [futures, setFutures] = useState("");
  const [cutoff, setCutoff] = useState("");     // broker/NSE square-off — never assumed
  // daily guardrails
  const [realisedPnl, setRealisedPnl] = useState("");
  const [entriesToday, setEntriesToday] = useState("0");
  const [consecLosses, setConsecLosses] = useState("0");
  const [openPos, setOpenPos] = useState("");

  // B · regime
  const [regime, setRegime] = useState("");
  const [struct15, setStruct15] = useState("");
  const [struct5, setStruct5] = useState("");
  const [vwap, setVwap] = useState("");
  const [orRange, setOrRange] = useState("");
  const [relVol, setRelVol] = useState("");
  const [gap, setGap] = useState("");
  const [support, setSupport] = useState("");
  const [resistance, setResistance] = useState("");
  const [breadth, setBreadth] = useState("");
  const [eventRisk, setEventRisk] = useState("unknown");   // clear | restricted | unknown

  // setup + direction
  const [setup, setSetup] = useState<keyof typeof SETUPS>("A");
  const [direction, setDirection] = useState<"LONG" | "SHORT">("LONG");

  // sizing
  const [entry, setEntry] = useState("");
  const [stop, setStop] = useState("");
  const [perUnitCost, setPerUnitCost] = useState("");
  const [lotSize, setLotSize] = useState("");
  const [target, setTarget] = useState("");

  // F · alternative-if-no-trade notes
  const [reassess, setReassess] = useState("");
  const [confirmReq, setConfirmReq] = useState("");
  const [invalidation, setInvalidation] = useState("");
  const [nextReview, setNextReview] = useState("");

  // evidence gate
  const [hasSample, setHasSample] = useState(false);

  // manual gates (auto ones overwritten below)
  const [mGates, setMGates] = useState<Gate[]>(Array(14).fill("UNKNOWN"));
  const setGate = (i: number, g: Gate) => setMGates((p) => p.map((x, j) => (j === i ? g : x)));

  const [logMsg, setLogMsg] = useState<string | null>(null);
  const [logging, setLogging] = useState(false);

  const [ctx, setCtx] = useState<IntradayContext | null>(null);
  const [loadingCtx, setLoadingCtx] = useState(false);
  const autofill = async () => {
    setLoadingCtx(true);
    try {
      const c = await api.getIntradayContext(underlying);
      setCtx(c);
      if (c.is_live) {
        setDataStatus("live");
        if (c.spot !== null) setSpot(String(c.spot));
        if (c.gap !== null) setGap(`open ${c.open} vs prev close ${c.prev_close} = ${c.gap >= 0 ? "+" : ""}${c.gap}`);
      }
    } catch {
      setCtx({ timestamp_ist: nowIST(), underlying, is_live: false, source: "request failed", spot: null, open: null, high: null, low: null, prev_close: null, vix: null, gap: null });
    } finally {
      setLoadingCtx(false);
    }
  };

  const [chain, setChain] = useState<OptionChain | null>(null);
  const [loadingChain, setLoadingChain] = useState(false);
  const fetchChain = async () => {
    setLoadingChain(true);
    try {
      const c = await api.getOptionChain(underlying);
      setChain(c);
      if (c.is_live) {
        if (c.lot_size !== null) setLotSize(String(c.lot_size));
        if (c.expiry) setExpiry(c.expiry);
        if (c.spot !== null) setSpot(String(c.spot));
        setDataStatus("live");
      }
    } catch {
      setChain({ underlying, timestamp: nowIST(), is_live: false, source: "request failed", spot: null, atm: null, expiry: null, lot_size: null, rows: [] });
    } finally {
      setLoadingChain(false);
    }
  };
  // Clicking an option premium seeds the sizing inputs.
  const pickLeg = (leg: OptionLeg | null, dir: "LONG" | "SHORT") => {
    if (!leg || leg.ltp === null) return;
    setEntry(String(leg.ltp));
    setDirection(dir);
  };

  // ---- hard rules ----
  const pnl = num(realisedPnl) ?? 0;
  const entriesN = num(entriesToday) ?? 0;
  const consecN = num(consecLosses) ?? 0;
  const dailyLossHit = pnl <= -DAILY_MAX_LOSS;
  const entriesHit = entriesN >= MAX_ENTRIES;
  const consecHit = consecN >= MAX_CONSEC_LOSS;
  const stopDayReasons: string[] = [];
  if (dailyLossHit) stopDayReasons.push(`Daily realised loss ${inr(pnl)} ≤ −${inr(DAILY_MAX_LOSS)} limit`);
  if (entriesHit) stopDayReasons.push(`${entriesN} entries ≥ max ${MAX_ENTRIES}/day`);
  if (consecHit) stopDayReasons.push(`${consecN} consecutive losses ≥ max ${MAX_CONSEC_LOSS}`);
  const dailyPermitted = stopDayReasons.length === 0;

  // ---- sizing ----
  const sizing = useMemo((): Sizing => {
    const e = num(entry), s = num(stop), c = num(perUnitCost) ?? 0, lot = num(lotSize);
    if (e === null || s === null || lot === null || lot <= 0) return { ready: false };
    const riskPerUnit = Math.abs(e - s) + c;
    if (riskPerUnit <= 0) return { ready: false };
    const maxUnits = Math.floor(RISK_PER_TRADE / riskPerUnit);
    const permittedLots = Math.floor(maxUnits / lot);
    const maxLoss = permittedLots * lot * riskPerUnit;
    const t = num(target);
    const reward = t !== null ? Math.abs(t - e) - c : null;
    const rr = reward !== null && riskPerUnit > 0 ? reward / riskPerUnit : null;
    return { ready: true, riskPerUnit, maxUnits, permittedLots, maxLoss, lot, rr, ok: permittedLots >= 1 && maxLoss <= RISK_PER_TRADE };
  }, [entry, stop, perUnitCost, lotSize, target]);

  // ---- critical data completeness (rule 10) ----
  const missing: string[] = [];
  if (!spot.trim()) missing.push("spot");
  if (!expiry.trim()) missing.push("expiry");
  if (!lotSize.trim()) missing.push("lot size");
  if (!entry.trim()) missing.push("entry premium");
  if (!stop.trim()) missing.push("stop");
  if (!cutoff.trim()) missing.push("square-off/cut-off time");
  const dataComplete = missing.length === 0;

  // ---- effective gates (auto-derived where computable) ----
  const gates: Gate[] = mGates.map((g, i) => {
    if (i === AUTO.REGIME) return regime === "" ? "UNKNOWN" : regime === "unclear" ? "FAIL" : "PASS";
    if (i === AUTO.SIZING) return sizing.ready ? (sizing.ok ? "PASS" : "FAIL") : "UNKNOWN";
    if (i === AUTO.DAILY) return dailyPermitted ? "PASS" : "FAIL";
    if (i === 12) return hasSample ? g : "UNKNOWN"; // evidence gate needs the sample flag
    return g;
  });
  const anyFail = gates.some((g) => g === "FAIL");
  const anyUnknown = gates.some((g) => g === "UNKNOWN");
  const allPass = gates.every((g) => g === "PASS");

  // ---- verdict (precedence) ----
  const verdict: Verdict = useMemo(() => {
    if (!dailyPermitted) return "STOP_DAY";
    if (!dataComplete) return "INSUFFICIENT_DATA";
    if (regime === "unclear") return "NO_TRADE";
    if (sizing.ready && !sizing.ok) return "NO_TRADE";
    if (anyFail) return "NO_TRADE";
    if (anyUnknown) return "WAIT";
    if (allPass) return "CANDIDATE";
    return "NO_TRADE";
  }, [dailyPermitted, dataComplete, regime, sizing, anyFail, anyUnknown, allPass]);

  const logDecision = async () => {
    setLogging(true);
    setLogMsg(null);
    const notPass = GATE_LABELS.map((_l, i) => ({ n: i + 1, g: gates[i] })).filter((x) => x.g !== "PASS");
    const decisionLabel = verdict === "CANDIDATE" ? "Trade (conditional)" : verdict === "WAIT" ? "Wait"
      : verdict === "STOP_DAY" ? "Stop for the day" : "No trade";
    try {
      await api.logDecision({
        underlying, expiry, regime, setup, direction, verdict, decision: decisionLabel,
        gates_failed: notPass.length ? notPass.map((x) => `${x.n}[${x.g}]`).join(", ") : "none",
        planned_entry: num(entry), planned_stop: num(stop), planned_target: num(target),
        planned_risk: sizing.ready ? Math.round(sizing.maxLoss) : null,
        permitted_lots: sizing.ready ? sizing.permittedLots : null,
      });
      setLogMsg(`✅ ${decisionLabel} logged to Journal (decision log).`);
    } catch (e) {
      setLogMsg("⚠ " + (e instanceof Error ? e.message : "log failed"));
    } finally {
      setLogging(false);
    }
  };

  return (
    <div className="space-y-6">
      <Disclaimer />

      {/* Auto-fill live data */}
      <div className="flex flex-wrap items-center gap-3">
        <button onClick={autofill} disabled={loadingCtx}
          className="rounded-md border border-cyan/50 bg-cyan/15 px-4 py-2 font-mono text-xs font-bold text-cyan hover:bg-cyan/25 disabled:opacity-50">
          {loadingCtx ? "⏳ Fetching…" : `⟳ Auto-fill live ${underlying} data`}
        </button>
        <button onClick={fetchChain} disabled={loadingChain}
          className="rounded-md border border-cyan/50 bg-cyan/15 px-4 py-2 font-mono text-xs font-bold text-cyan hover:bg-cyan/25 disabled:opacity-50">
          {loadingChain ? "⏳ Loading chain…" : "⟳ Auto-fill ATM option chain"}
        </button>
        <span className="font-mono text-[10px] text-muted">
          Spot / VIX / day levels + the ATM ±3 chain (LTP, spread, OI, IV) & verified lot size — from Kite, not typed.
        </span>
      </div>
      {ctx && <LiveContextStrip ctx={ctx} />}
      {chain && <OptionChainPanel chain={chain} onPick={pickLeg} />}

      {/* A · DATA STATUS */}
      <Panel title="A · Data Status" tag="mark every input; never invented">
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
          <Field label="Timestamp (IST)"><span className="tnum text-cyan">{ist}</span></Field>
          <Select label="Data source" value={dataStatus} onChange={setDataStatus}
            opts={[["live", "Live"], ["delayed", "Delayed"], ["user-supplied", "User-supplied"], ["estimated", "Estimated"], ["missing", "Missing"]]} />
          <UnderlyingField value={underlying} onChange={setUnderlying} />
          <Input label="Expiry" value={expiry} onChange={setExpiry} placeholder="e.g. 04-Sep" />
          <Input label="Spot" value={spot} onChange={setSpot} />
          <Input label="Futures" value={futures} onChange={setFutures} />
          <Input label="Cut-off (confirm — never assumed)" value={cutoff} onChange={setCutoff} placeholder="e.g. 15:20" />
          <Field label="Trade permission">
            <span className="tnum font-bold" style={{ color: dailyPermitted ? "var(--green)" : "var(--red)" }}>
              {dailyPermitted ? "Permitted" : "Not permitted"}
            </span>
          </Field>
        </div>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Input label="Realised P&L today (₹)" value={realisedPnl} onChange={setRealisedPnl} placeholder="e.g. -1200" />
          <Input label={`Entries today (max ${MAX_ENTRIES})`} value={entriesToday} onChange={setEntriesToday} />
          <Input label={`Consecutive losses (max ${MAX_CONSEC_LOSS})`} value={consecLosses} onChange={setConsecLosses} />
          <Input label="Open positions" value={openPos} onChange={setOpenPos} placeholder="none / describe" />
        </div>
        {stopDayReasons.map((b) => <div key={b} className="font-mono text-[11px] text-signalred">✕ {b}</div>)}
        {!dataComplete && (
          <div className="font-mono text-[11px] text-gold">⚠ Missing verified inputs: {missing.join(", ")} → NO TRADE — insufficient verified data.</div>
        )}
      </Panel>

      {/* B · MARKET REGIME */}
      <Panel title="B · Market Regime" tag="classify before any trade — unclear ⇒ NO TRADE">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Select label="Regime classification" value={regime} onChange={setRegime}
            opts={[["", "— select —"], ...REGIMES]} />
          <Select label="Event-risk status" value={eventRisk} onChange={setEventRisk}
            opts={[["clear", "Clear — no event window"], ["restricted", "In restricted event window"], ["unknown", "Unknown / unverified"]]} />
          <Input label="Relative volume" value={relVol} onChange={setRelVol} placeholder="vs comparable candles" />
          <Input label="15-min structure" value={struct15} onChange={setStruct15} placeholder="HH/HL, LL/LH…" />
          <Input label="5-min structure" value={struct5} onChange={setStruct5} />
          <Input label="VWAP condition & slope" value={vwap} onChange={setVwap} placeholder="above/below, slope, crosses" />
          <Input label="Opening-range condition" value={orRange} onChange={setOrRange} placeholder="09:15–09:30 hi/lo" />
          <Input label="Gap context" value={gap} onChange={setGap} />
          <Input label="Breadth / index alignment" value={breadth} onChange={setBreadth} />
          <Input label="Nearest support" value={support} onChange={setSupport} />
          <Input label="Nearest resistance" value={resistance} onChange={setResistance} />
        </div>
        {eventRisk === "restricted" && (
          <div className="font-mono text-[11px] text-signalred">✕ Inside a high-impact event window — no fresh position (unless a separately tested event rule exists).</div>
        )}
      </Panel>

      {/* Setup + direction */}
      <Panel title="Setup & Direction" tag="trade only an approved setup">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Select label="Approved setup" value={setup} onChange={(v) => setSetup(v as keyof typeof SETUPS)}
            opts={Object.entries(SETUPS).map(([k, v]) => [k, `${k} · ${v}`])} />
          <Select label="Direction" value={direction} onChange={(v) => setDirection(v as "LONG" | "SHORT")}
            opts={[["LONG", "Long / Call"], ["SHORT", "Short / Put"]]} />
          <Field label="Setup rule reminder"><span className="font-mono text-[10px] leading-relaxed text-muted">{SETUP_HINT[setup]}</span></Field>
        </div>
      </Panel>

      {/* Position sizing */}
      <Panel title="Position Sizing" tag={`max risk ${inr(RISK_PER_TRADE)} on ${inr(CAPITAL)} — floor, never up`}>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
          <Input label="Entry (option ₹)" value={entry} onChange={setEntry} placeholder="premium" />
          <Input label="Stop (option ₹)" value={stop} onChange={setStop} placeholder="premium" />
          <Input label="Cost+slip / unit (₹)" value={perUnitCost} onChange={setPerUnitCost} placeholder="e.g. 1.5" />
          <Input label="Verified lot size" value={lotSize} onChange={setLotSize} placeholder="VERIFY — no default" />
          <Input label="Target (₹, optional)" value={target} onChange={setTarget} placeholder="for R:R" />
        </div>
        <SizingReadout sizing={sizing} />
      </Panel>

      {/* Backtest evidence gate 13 */}
      <Panel title="Evidence Gate" tag="gate 13 — no edge claim without your documented sample">
        <label className="flex items-start gap-2">
          <input type="checkbox" checked={hasSample} onChange={(e) => setHasSample(e.target.checked)} className="mt-0.5 accent-cyan" />
          <span className="font-mono text-[11px] text-ink/90">
            I have a documented BACKTEST / PAPER-TRADE sample for this exact setup, timeframe, option-selection, stop/exit rules,
            costs & slippage, in the <span className="text-gold">same market regime</span>. (Unchecked ⇒ gate 13 UNKNOWN ⇒ no trade.)
          </span>
        </label>
      </Panel>

      {/* C · GATE TABLE */}
      <Panel title="C · Pre-Trade Gates" tag="all 14 must PASS — any FAIL/UNKNOWN ⇒ no trade">
        <div className="space-y-1.5">
          {GATE_LABELS.map((label, i) => {
            const isAuto = i === AUTO.REGIME || i === AUTO.SIZING || i === AUTO.DAILY;
            return (
              <div key={i} className="flex items-center gap-3 rounded-md border border-line bg-raised/30 px-3 py-2">
                <span className="w-5 shrink-0 font-mono text-[10px] text-muted">{i + 1}</span>
                <span className="min-w-0 flex-1 font-mono text-[11px] text-ink/90">
                  {label}{isAuto && <span className="ml-1 text-[9px] text-cyan/70">auto</span>}
                </span>
                {isAuto ? (
                  <span className="rounded px-2 py-0.5 font-mono text-[9px] font-bold uppercase text-bg"
                    style={{ background: GATE_COLOR[gates[i]] }}>{gates[i] === "UNKNOWN" ? "?" : gates[i]}</span>
                ) : (
                  <div className="flex shrink-0 gap-1">
                    {(["PASS", "FAIL", "UNKNOWN"] as Gate[]).map((g) => (
                      <button key={g} onClick={() => setGate(i, g)}
                        className="rounded px-2 py-0.5 font-mono text-[9px] font-bold uppercase transition-colors"
                        style={{ background: gates[i] === g ? GATE_COLOR[g] : "var(--bg-3)", color: gates[i] === g ? "var(--bg)" : "var(--muted)" }}>
                        {g === "UNKNOWN" ? "?" : g}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
        <div className="mt-3 flex gap-4 font-mono text-[10px]">
          <span style={{ color: "var(--green)" }}>{gates.filter((g) => g === "PASS").length} pass</span>
          <span style={{ color: "var(--red)" }}>{gates.filter((g) => g === "FAIL").length} fail</span>
          <span style={{ color: "var(--gold)" }}>{gates.filter((g) => g === "UNKNOWN").length} unknown</span>
        </div>
      </Panel>

      {/* D · VERDICT */}
      <VerdictBox verdict={verdict} stopDayReasons={stopDayReasons} missing={missing} regime={regime}
        anyFail={anyFail} anyUnknown={anyUnknown} gates={gates} sizing={sizing} />

      {/* E · CONDITIONAL TRADE PLAN */}
      {verdict === "CANDIDATE" && sizing.ready && (
        <Panel title="E · Conditional Trade Plan" tag="educational conditional plan — not advice">
          <div className="grid grid-cols-1 gap-3 font-mono text-[11px] sm:grid-cols-2">
            <Kv k="Approved setup" v={`${setup} · ${SETUPS[setup]}`} />
            <Kv k="Underlying / expiry" v={`${underlying} · ${expiry || "—"}`} />
            <Kv k="Direction" v={direction} />
            <Kv k="Market regime" v={REGIMES.find((r) => r[0] === regime)?.[1] ?? "—"} />
            <Kv k="Entry (premium)" v={inr(num(entry)!)} />
            <Kv k="Structural stop / invalidation" v={inr(num(stop)!)} />
            <Kv k="Target" v={target ? inr(num(target)!) : "define before entry"} />
            <Kv k="Support / resistance" v={`${support || "—"} / ${resistance || "—"}`} />
            <Kv k="Verified lot size" v={String(sizing.lot)} />
            <Kv k="Risk / unit (incl. costs)" v={inr(sizing.riskPerUnit)} />
            <Kv k="Max permitted lots" v={String(sizing.permittedLots)} />
            <Kv k="Max ₹ loss at stop" v={inr(sizing.maxLoss)} accent={sizing.maxLoss <= RISK_PER_TRADE ? "green" : "red"} />
            <Kv k="Reward : risk (after costs)" v={sizing.rr !== null ? `${sizing.rr.toFixed(2)}R` : "add target"} accent={sizing.rr !== null && sizing.rr >= 2 ? "green" : "gold"} />
            <Kv k="Cut-off (flatten before)" v={cutoff || "confirm!"} />
          </div>
          <p className="mt-3 font-mono text-[10px] text-muted">
            Entry is CONDITIONAL — wait for the exact trigger; prefer limit orders (flag market-order slippage). Flatten before
            the cut-off. Educational conditional analysis, not guaranteed, personalised, or regulated advice.
          </p>
        </Panel>
      )}

      {/* F · ALTERNATIVE IF NO TRADE / WAIT */}
      {verdict !== "CANDIDATE" && verdict !== "STOP_DAY" && (
        <Panel title="F · Alternative if NO TRADE / WAIT" tag="what would change the decision">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Input label="Level/behavior that justifies reassessment" value={reassess} onChange={setReassess} />
            <Input label="Exact confirmation required" value={confirmReq} onChange={setConfirmReq} />
            <Input label="What fully invalidates the idea" value={invalidation} onChange={setInvalidation} />
            <Input label="Next review time / trigger" value={nextReview} onChange={setNextReview} />
          </div>
        </Panel>
      )}

      {/* G · JOURNAL RECORD */}
      <JournalRecord ist={ist} underlying={underlying} expiry={expiry} regime={regime} setup={setup}
        direction={direction} verdict={verdict} gates={gates} sizing={sizing} entry={entry} stop={stop} target={target}
        onLog={logDecision} logging={logging} logMsg={logMsg} />
    </div>
  );
}

/* ------------------------------ types & helpers ---------------------------- */

type Sizing =
  | { ready: false }
  | { ready: true; riskPerUnit: number; maxUnits: number; permittedLots: number; maxLoss: number; lot: number; rr: number | null; ok: boolean };

const GATE_COLOR: Record<Gate, string> = { PASS: "var(--green)", FAIL: "var(--red)", UNKNOWN: "var(--gold)" };

function OptionChainPanel({ chain, onPick }: { chain: OptionChain; onPick: (leg: OptionLeg | null, dir: "LONG" | "SHORT") => void }) {
  if (!chain.is_live) {
    return (
      <div className="rounded-md border border-gold/30 bg-gold/10 px-4 py-2 font-mono text-[11px] text-gold">
        ⚠ Option chain unavailable — {chain.source}. Connect Kite (System Check), then retry.
      </div>
    );
  }
  const fmt = (n: number | null, unit = "") => (n === null || n === undefined ? "—" : `${n}${unit}`);
  const oiK = (n: number | null) => (n === null ? "—" : n >= 1000 ? `${(n / 1000).toFixed(0)}k` : String(n));
  // liquidity flag by spread as % of LTP
  const spreadColor = (leg: OptionLeg | null) => {
    if (!leg || leg.spread === null || !leg.ltp) return "var(--muted)";
    const pct = (leg.spread / leg.ltp) * 100;
    return pct <= 1 ? "var(--green)" : pct <= 3 ? "var(--gold)" : "var(--red)";
  };
  return (
    <div className="space-y-2 rounded-lg border border-cyan/20 bg-cyan/[0.04] p-3">
      <div className="flex flex-wrap items-center justify-between gap-2 font-mono text-[10px]">
        <span className="text-cyan">● LIVE CHAIN · {chain.underlying} · exp {chain.expiry} · lot {chain.lot_size} · ATM {chain.atm} · spot {chain.spot} · {chain.timestamp}</span>
        <span className="text-muted">click a premium ▸ sets entry & direction. IV computed; change-in-OI not in Kite quote.</span>
      </div>
      <div className="overflow-x-auto rounded-md border border-line">
        <table className="w-full text-center text-[11px]">
          <thead className="bg-raised/50 font-mono text-[9px] uppercase tracking-wider text-muted">
            <tr>
              <th className="px-2 py-1.5 text-cyan" colSpan={4}>CALLS (buy = LONG)</th>
              <th className="px-2 py-1.5">Strike</th>
              <th className="px-2 py-1.5 text-cyan" colSpan={4}>PUTS (buy = SHORT)</th>
            </tr>
            <tr>
              {["OI", "IV", "Spread", "LTP"].map((h) => <th key={"c" + h} className="px-2 py-1">{h}</th>)}
              <th className="px-2 py-1"></th>
              {["LTP", "Spread", "IV", "OI"].map((h) => <th key={"p" + h} className="px-2 py-1">{h}</th>)}
            </tr>
          </thead>
          <tbody className="divide-y divide-line font-mono">
            {chain.rows.map((r) => (
              <tr key={r.strike} className={r.atm ? "bg-gold/10" : "hover:bg-raised/40"}>
                <td className="px-2 py-1.5 tnum text-muted">{oiK(r.call?.oi ?? null)}</td>
                <td className="px-2 py-1.5 tnum text-muted">{fmt(r.call?.iv ?? null, "%")}</td>
                <td className="px-2 py-1.5 tnum" style={{ color: spreadColor(r.call) }}>{fmt(r.call?.spread ?? null)}</td>
                <td className="cursor-pointer px-2 py-1.5 tnum font-bold text-ink hover:text-cyan" onClick={() => onPick(r.call, "LONG")}>{fmt(r.call?.ltp ?? null)}</td>
                <td className="px-2 py-1.5 tnum font-bold" style={{ color: r.atm ? "var(--gold)" : "var(--ink)" }}>{r.strike}{r.atm ? " ·ATM" : ""}</td>
                <td className="cursor-pointer px-2 py-1.5 tnum font-bold text-ink hover:text-cyan" onClick={() => onPick(r.put, "SHORT")}>{fmt(r.put?.ltp ?? null)}</td>
                <td className="px-2 py-1.5 tnum" style={{ color: spreadColor(r.put) }}>{fmt(r.put?.spread ?? null)}</td>
                <td className="px-2 py-1.5 tnum text-muted">{fmt(r.put?.iv ?? null, "%")}</td>
                <td className="px-2 py-1.5 tnum text-muted">{oiK(r.put?.oi ?? null)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="font-mono text-[9px] text-muted">Spread colour: green ≤1% of LTP · gold ≤3% · red &gt;3% (liquidity/gate-9 hint). Lot size &amp; expiry auto-filled below.</div>
    </div>
  );
}

function LiveContextStrip({ ctx }: { ctx: IntradayContext }) {
  if (!ctx.is_live) {
    return (
      <div className="rounded-md border border-gold/30 bg-gold/10 px-4 py-2 font-mono text-[11px] text-gold">
        ⚠ Live data unavailable — {ctx.source}. Connect Kite (System Check), then retry. Fields stay manual.
      </div>
    );
  }
  const cell = (k: string, v: number | null, unit = "") => (
    <div className="rounded-md border border-line bg-raised/40 px-3 py-2">
      <div className="font-mono text-[9px] uppercase tracking-wider text-muted">{k}</div>
      <div className="tnum text-sm font-bold text-ink">{v === null ? "—" : `${v}${unit}`}</div>
    </div>
  );
  return (
    <div className="space-y-2 rounded-lg border border-cyan/20 bg-cyan/[0.04] p-3">
      <div className="font-mono text-[10px] text-cyan">● LIVE · {ctx.underlying} · {ctx.source} · {ctx.timestamp_ist}</div>
      <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
        {cell("Spot", ctx.spot)}
        {cell("Open", ctx.open)}
        {cell("Day High", ctx.high)}
        {cell("Day Low", ctx.low)}
        {cell("Prev Close", ctx.prev_close)}
        {cell("India VIX", ctx.vix)}
      </div>
      {ctx.gap !== null && (
        <div className="font-mono text-[10px] text-muted">
          Gap: open {ctx.open} vs prev close {ctx.prev_close} = <span style={{ color: ctx.gap >= 0 ? "var(--green)" : "var(--red)" }}>{ctx.gap >= 0 ? "+" : ""}{ctx.gap}</span> pts
        </div>
      )}
    </div>
  );
}

function Disclaimer() {
  return (
    <div className="rounded-md border border-gold/25 bg-gold/5 px-4 py-2.5 font-mono text-[10px] leading-relaxed text-muted">
      ⚖ Educational conditional analysis only — <span className="text-gold">not SEBI-registered advice</span>, not a signal
      service. No profit promises, no certainty. Enforces your hard risk rules; defaults to NO TRADE on incomplete or
      conflicting evidence. A missed opportunity is acceptable — a rule violation is not. You verify all data and own the
      execution & compliance decision.
    </div>
  );
}

function Panel({ title, tag, children }: { title: string; tag?: string; children: React.ReactNode }) {
  return (
    <div className="panel space-y-3 rounded-lg p-5">
      <h2 className="flex flex-wrap items-baseline gap-2 font-display text-sm font-bold text-ink">
        {title}{tag && <span className="font-mono text-[10px] font-normal text-muted">— {tag}</span>}
      </h2>
      {children}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-line bg-raised/30 px-3 py-2">
      <div className="font-mono text-[9px] uppercase tracking-wider text-muted">{label}</div>
      <div className="mt-0.5 text-sm">{children}</div>
    </div>
  );
}

function Input({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (v: string) => void; placeholder?: string }) {
  return (
    <label className="block">
      <span className="font-mono text-[9px] uppercase tracking-wider text-muted">{label}</span>
      <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder}
        className="mt-1 w-full rounded-md border border-line bg-bg/60 px-2.5 py-1.5 font-mono text-xs text-ink outline-none focus:border-cyan/50" />
    </label>
  );
}

const FNO_NAMES = [
  "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY",
  "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "SBIN", "AXISBANK", "KOTAKBANK",
  "TATAMOTORS", "TATASTEEL", "HINDALCO", "MARUTI", "BAJFINANCE", "ADANIENT", "ITC",
  "LT", "HCLTECH", "WIPRO", "SUNPHARMA", "TITAN", "ULTRACEMCO", "DIVISLAB", "BAJAJ-AUTO",
];

function UnderlyingField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <label className="block">
      <span className="font-mono text-[9px] uppercase tracking-wider text-muted">Underlying (index or F&amp;O stock)</span>
      <input list="fno-names" value={value} onChange={(e) => onChange(e.target.value.toUpperCase())}
        placeholder="e.g. RELIANCE"
        className="mt-1 w-full rounded-md border border-line bg-bg/60 px-2.5 py-1.5 font-mono text-xs uppercase text-ink outline-none focus:border-cyan/50" />
      <datalist id="fno-names">{FNO_NAMES.map((n) => <option key={n} value={n} />)}</datalist>
    </label>
  );
}

function Select({ label, value, onChange, opts }: { label: string; value: string; onChange: (v: string) => void; opts: [string, string][] }) {
  return (
    <label className="block">
      <span className="font-mono text-[9px] uppercase tracking-wider text-muted">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full rounded-md border border-line bg-bg/60 px-2.5 py-1.5 font-mono text-xs text-ink outline-none focus:border-cyan/50">
        {opts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  );
}

function SizingReadout({ sizing }: { sizing: Sizing }) {
  if (!sizing.ready) return <p className="mt-3 font-mono text-[11px] text-muted">Enter entry, stop & verified lot size to compute sizing.</p>;
  const zero = sizing.permittedLots < 1;
  return (
    <div className="mt-3 space-y-2">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat k="Risk / unit" v={inr(sizing.riskPerUnit)} />
        <Stat k="Max units (₹1,000 ÷ risk)" v={String(sizing.maxUnits)} />
        <Stat k="Permitted lots" v={String(sizing.permittedLots)} accent={zero ? "red" : "green"} />
        <Stat k="Max ₹ loss at stop" v={inr(sizing.maxLoss)} accent={sizing.maxLoss <= RISK_PER_TRADE ? "green" : "red"} />
      </div>
      <p className="font-mono text-[10px] text-muted">
        risk/unit = |entry−stop| + costs+slippage · maxUnits = floor(₹{RISK_PER_TRADE.toLocaleString("en-IN")} ÷ risk/unit) · lots = floor(maxUnits ÷ lot). Never rounded up.
      </p>
      {zero && (
        <div className="rounded-md border border-signalred/30 bg-signalred/10 px-3 py-2 font-mono text-[11px]" style={{ color: "var(--red)" }}>
          NO TRADE — one permitted lot exceeds the ₹{RISK_PER_TRADE.toLocaleString("en-IN")} risk limit at this stop.
        </div>
      )}
    </div>
  );
}

function Stat({ k, v, accent }: { k: string; v: string; accent?: "green" | "red" | "gold" }) {
  return (
    <div className="rounded-md border border-line bg-raised/30 px-3 py-2">
      <div className="font-mono text-[9px] uppercase tracking-wider text-muted">{k}</div>
      <div className="tnum text-sm font-bold" style={{ color: accent ? `var(--${accent})` : "var(--ink)" }}>{v}</div>
    </div>
  );
}

function Kv({ k, v, accent }: { k: string; v: string; accent?: "green" | "red" | "gold" }) {
  return (
    <div className="flex justify-between gap-3 border-b border-line py-1">
      <span className="text-muted">{k}</span>
      <span className="tnum font-bold" style={{ color: accent ? `var(--${accent})` : "var(--ink)" }}>{v}</span>
    </div>
  );
}

const VERDICT_META: Record<Verdict, { label: string; color: string; bg: string }> = {
  STOP_DAY: { label: "STOP FOR THE DAY", color: "var(--red)", bg: "rgba(255,93,93,0.10)" },
  INSUFFICIENT_DATA: { label: "NO TRADE — insufficient verified data", color: "var(--red)", bg: "rgba(255,93,93,0.10)" },
  NO_TRADE: { label: "NO TRADE", color: "var(--red)", bg: "rgba(255,93,93,0.10)" },
  WAIT: { label: "WAIT FOR CONFIRMATION", color: "var(--gold)", bg: "rgba(244,185,66,0.10)" },
  CANDIDATE: { label: "TRADE CANDIDATE — conditional only", color: "var(--green)", bg: "rgba(88,214,141,0.10)" },
};

function VerdictBox({ verdict, stopDayReasons, missing, regime, anyFail, anyUnknown, gates, sizing }: {
  verdict: Verdict; stopDayReasons: string[]; missing: string[]; regime: string;
  anyFail: boolean; anyUnknown: boolean; gates: Gate[]; sizing: Sizing;
}) {
  const m = VERDICT_META[verdict];
  const notPass = GATE_LABELS.map((l, i) => ({ l, g: gates[i], i })).filter((x) => x.g !== "PASS");
  return (
    <div className="rounded-lg border p-5" style={{ borderColor: m.color + "55", background: m.bg }}>
      <div className="font-display text-lg font-bold" style={{ color: m.color }}>D · {m.label}</div>
      <div className="mt-2 space-y-2 font-mono text-[11px] text-muted">
        {verdict === "STOP_DAY" && (
          <div>
            <span className="text-signalred">Daily lockout — close the terminal for the day:</span>
            <ul className="ml-3 list-disc">{stopDayReasons.map((b) => <li key={b}>{b}</li>)}</ul>
          </div>
        )}
        {verdict === "INSUFFICIENT_DATA" && <div className="text-signalred">Verify and supply: {missing.join(", ")}. No executable instrument or quantity until data is current.</div>}
        {verdict === "NO_TRADE" && regime === "unclear" && <div className="text-signalred">Regime is unclear/mixed — do not force a trade.</div>}
        {verdict === "NO_TRADE" && sizing.ready && !sizing.ok && <div className="text-signalred">One permitted lot exceeds the ₹1,000 risk cap at this stop.</div>}
        {(verdict === "NO_TRADE" || verdict === "WAIT") && (anyFail || anyUnknown) && (
          <div>
            <span style={{ color: anyFail ? "var(--red)" : "var(--gold)" }}>{notPass.length} gate(s) not passing:</span>
            <ul className="ml-3 mt-1 space-y-0.5">
              {notPass.map((x) => (
                <li key={x.i}><span style={{ color: x.g === "FAIL" ? "var(--red)" : "var(--gold)" }}>[{x.g}]</span> {x.i + 1}. {x.l}</li>
              ))}
            </ul>
          </div>
        )}
        {verdict === "CANDIDATE" && <p style={{ color: "var(--green)" }}>All 14 gates pass, sizing within the ₹1,000 cap, data verified, and daily rules permit. Re-verify live prices/liquidity and confirm the trigger before acting. Conditional candidate, not a recommendation.</p>}
      </div>
    </div>
  );
}

function JournalRecord({ ist, underlying, expiry, regime, setup, direction, verdict, gates, sizing, entry, stop, target, onLog, logging, logMsg }: {
  ist: string; underlying: string; expiry: string; regime: string; setup: keyof typeof SETUPS; direction: string;
  verdict: Verdict; gates: Gate[]; sizing: Sizing; entry: string; stop: string; target: string;
  onLog: () => void; logging: boolean; logMsg: string | null;
}) {
  const notPass = GATE_LABELS.map((_l, i) => ({ n: i + 1, g: gates[i] })).filter((x) => x.g !== "PASS");
  const decision = verdict === "CANDIDATE" ? "Trade (conditional)" : verdict === "WAIT" ? "Wait"
    : verdict === "STOP_DAY" ? "Stop for the day" : "No trade";
  const text = [
    `Date/Time (IST): ${ist}`,
    `Underlying: ${underlying}  Expiry: ${expiry || "—"}`,
    `Market regime: ${REGIMES.find((r) => r[0] === regime)?.[1] ?? "—"}`,
    `Setup evaluated: ${setup} — ${SETUPS[setup]} (${direction})`,
    `Decision: ${decision}`,
    `Gate failures/unknown: ${notPass.length ? notPass.map((x) => `${x.n}[${x.g}]`).join(", ") : "none"}`,
    `Planned entry: ${entry || "—"}   Planned stop: ${stop || "—"}   Planned target: ${target || "—"}`,
    `Planned risk (₹): ${sizing.ready ? Math.round(sizing.maxLoss) : "—"} (cap 1000)   Planned risk (R): 1.0`,
    `Permitted lots: ${sizing.ready ? sizing.permittedLots : "—"}`,
    `Actual fill price: ______   Actual exit price: ______`,
    `Gross P&L: ______   Costs & slippage: ______   Net P&L: ______   Actual result (R): ______`,
    `Rule adherence: ______`,
    `Classification: PAPER-TRADE RESULT`,
    `Review note: ______`,
  ].join("\n");
  return (
    <Panel title="G · Journal Record" tag="copy into your log — result fields blank until filled">
      <pre className="overflow-x-auto whitespace-pre-wrap rounded-md border border-line bg-bg/60 p-3 font-mono text-[11px] text-ink/90">{text}</pre>
      <div className="flex flex-wrap items-center gap-2">
        <button onClick={onLog} disabled={logging}
          className="rounded-md border border-gold/50 bg-gold/15 px-3 py-1.5 font-mono text-[11px] font-bold text-gold hover:bg-gold/25 disabled:opacity-50">
          {logging ? "⏳ Logging…" : "▸ Log decision to Journal"}
        </button>
        <button onClick={() => navigator.clipboard?.writeText(text)}
          className="rounded-md border border-cyan/40 bg-cyan/10 px-3 py-1.5 font-mono text-[11px] font-bold text-cyan hover:bg-cyan/20">⧉ Copy journal record</button>
        {logMsg && <span className="font-mono text-[11px] text-muted">{logMsg}</span>}
      </div>
    </Panel>
  );
}
