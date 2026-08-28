import { useEffect, useMemo, useState } from "react";

/* =============================================================================
   Intraday Index-Options DISCIPLINE CONSOLE
   A deterministic rules-enforcement engine — NOT advice, NOT an LLM, no invented
   data. You supply timestamped market inputs; it enforces hard risk rules, the
   12 pre-trade gates, and transparent position sizing, then renders the A–F
   verdict. Defaults to NO TRADE whenever evidence is incomplete or conflicting.
   Educational conditional analysis only; you are not a SEBI-registered adviser.
============================================================================= */

const CAPITAL = 200_000;
const RISK_PER_TRADE = 1_000;   // 0.5% of capital
const DAILY_MAX_LOSS = 3_000;
const MAX_ENTRIES = 2;
const MAX_CONSEC_LOSS = 2;

type Gate = "PASS" | "FAIL" | "UNKNOWN";
type Verdict = "NO_TRADE" | "WAIT" | "CANDIDATE" | "STOP_DAY";

const SETUPS: Record<string, string> = {
  A: "ORB Breakout & Retest",
  B: "Trend Pullback to VWAP",
  C: "Range Reversal",
};

const GATE_LABELS = [
  "Market regime correctly identified",
  "Setup is one from the approved library",
  "5-min & 15-min structure supports the direction",
  "VWAP location supports the direction",
  "Relative volume confirms the trigger",
  "Key S/R leaves room for at least 2R",
  "Breadth / correlation does not materially conflict",
  "No restricted news / event window",
  "Underlying & option contract liquid; spread acceptable",
  "Lot size, premium, entry, stop & costs verified",
  "Risk ≤ ₹1,000 and daily rules permit a trade",
  "Documented historical sample for this setup + regime",
];

const inr = (n: number) => `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
const nowIST = () =>
  new Date().toLocaleString("en-IN", { timeZone: "Asia/Kolkata", hour12: false });

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

  // --- Setup & direction ---
  const [setup, setSetup] = useState<keyof typeof SETUPS>("A");
  const [underlying, setUnderlying] = useState("NIFTY");
  const [direction, setDirection] = useState<"LONG" | "SHORT">("LONG");
  const [dataStatus, setDataStatus] = useState<"live" | "delayed" | "user-supplied">("user-supplied");

  // --- Daily guardrail state (user-supplied) ---
  const [realisedPnl, setRealisedPnl] = useState("");   // today's realised P&L (₹, can be negative)
  const [entriesToday, setEntriesToday] = useState("0");
  const [consecLosses, setConsecLosses] = useState("0");

  // --- Position sizing inputs (verified) ---
  const [entry, setEntry] = useState("");
  const [stop, setStop] = useState("");
  const [perUnitCost, setPerUnitCost] = useState("");   // est. costs+slippage per unit (₹)
  const [lotSize, setLotSize] = useState("");           // MUST be user-verified; no default
  const [target, setTarget] = useState("");             // for R:R display

  // --- 12 gates (all default UNKNOWN — conscious assessment is the discipline) ---
  const [gates, setGates] = useState<Gate[]>(Array(12).fill("UNKNOWN"));
  const setGate = (i: number, g: Gate) =>
    setGates((prev) => prev.map((x, j) => (j === i ? g : x)));

  // ---------- Hard risk rules ----------
  const pnl = num(realisedPnl) ?? 0;
  const entriesN = num(entriesToday) ?? 0;
  const consecN = num(consecLosses) ?? 0;
  const dailyLossHit = pnl <= -DAILY_MAX_LOSS;
  const entriesHit = entriesN >= MAX_ENTRIES;
  const consecHit = consecN >= MAX_CONSEC_LOSS;
  const hardBlocks: string[] = [];
  if (dailyLossHit) hardBlocks.push(`Daily realised loss ${inr(pnl)} ≤ −${inr(DAILY_MAX_LOSS)} limit`);
  if (entriesHit) hardBlocks.push(`${entriesN} entries taken ≥ max ${MAX_ENTRIES}/day`);
  if (consecHit) hardBlocks.push(`${consecN} consecutive losses ≥ max ${MAX_CONSEC_LOSS}`);
  const dailyPermitted = hardBlocks.length === 0;

  // ---------- Position sizing (transparent) ----------
  const sizing = useMemo(() => {
    const e = num(entry), s = num(stop), c = num(perUnitCost) ?? 0, lot = num(lotSize);
    if (e === null || s === null || lot === null || lot <= 0) {
      return { ready: false as const };
    }
    const riskPerUnit = Math.abs(e - s) + c;
    if (riskPerUnit <= 0) return { ready: false as const };
    const maxUnits = Math.floor(RISK_PER_TRADE / riskPerUnit);
    const permittedLots = Math.floor(maxUnits / lot);
    const maxLoss = permittedLots * lot * riskPerUnit;
    const t = num(target);
    const rewardPerUnit = t !== null ? Math.abs(t - e) - c : null;
    const rr = rewardPerUnit !== null && riskPerUnit > 0 ? rewardPerUnit / riskPerUnit : null;
    return {
      ready: true as const, riskPerUnit, maxUnits, permittedLots, maxLoss,
      lot, rr, ok: permittedLots >= 1 && maxLoss <= RISK_PER_TRADE,
    };
  }, [entry, stop, perUnitCost, lotSize, target]);

  // ---------- Verdict ----------
  const anyFail = gates.some((g) => g === "FAIL");
  const anyUnknown = gates.some((g) => g === "UNKNOWN");
  const allPass = gates.every((g) => g === "PASS");

  const verdict: Verdict = useMemo(() => {
    if (dailyLossHit) return "STOP_DAY";
    if (!dailyPermitted) return "NO_TRADE";
    if (sizing.ready && !sizing.ok) return "NO_TRADE";
    if (anyFail) return "NO_TRADE";
    if (anyUnknown || !sizing.ready) return "WAIT";
    if (allPass) return "CANDIDATE";
    return "NO_TRADE";
  }, [dailyLossHit, dailyPermitted, sizing, anyFail, anyUnknown, allPass]);

  return (
    <div className="space-y-6">
      <Disclaimer />

      {/* A. DATA STATUS */}
      <Panel title="A · Data Status" tag="timestamped inputs only — never invented">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Timestamp (IST)"><span className="tnum text-cyan">{ist}</span></Field>
          <Select label="Data source" value={dataStatus} onChange={(v) => setDataStatus(v as any)}
            opts={[["live", "Live"], ["delayed", "Delayed"], ["user-supplied", "User-supplied"]]} />
          <Select label="Underlying" value={underlying} onChange={setUnderlying}
            opts={[["NIFTY", "NIFTY"], ["BANKNIFTY", "BANKNIFTY"]]} />
          <Field label="Trade permission">
            <span className="tnum font-bold" style={{ color: dailyPermitted ? "var(--green)" : "var(--red)" }}>
              {dailyPermitted ? "Permitted" : "Not permitted"}
            </span>
          </Field>
        </div>
      </Panel>

      {/* Daily guardrails */}
      <Panel title="Daily guardrails" tag={`hard rules on ${inr(CAPITAL)} capital — never overridden`}>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Input label="Realised P&L today (₹)" value={realisedPnl} onChange={setRealisedPnl} placeholder="e.g. -1200" />
          <Input label={`Entries today (max ${MAX_ENTRIES})`} value={entriesToday} onChange={setEntriesToday} />
          <Input label={`Consecutive losses (max ${MAX_CONSEC_LOSS})`} value={consecLosses} onChange={setConsecLosses} />
        </div>
        {hardBlocks.length > 0 && (
          <ul className="mt-3 space-y-1">
            {hardBlocks.map((b) => (
              <li key={b} className="font-mono text-[11px] text-signalred">✕ {b}</li>
            ))}
          </ul>
        )}
      </Panel>

      {/* Setup + direction */}
      <Panel title="B · Setup & Direction" tag="trade only an approved setup">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Select label="Approved setup" value={setup} onChange={(v) => setSetup(v as keyof typeof SETUPS)}
            opts={Object.entries(SETUPS).map(([k, v]) => [k, `${k} · ${v}`])} />
          <Select label="Direction" value={direction} onChange={(v) => setDirection(v as any)}
            opts={[["LONG", "Long / Call"], ["SHORT", "Short / Put"]]} />
          <Field label="Setup rule reminder">
            <span className="font-mono text-[10px] text-muted">{SETUP_HINT[setup]}</span>
          </Field>
        </div>
      </Panel>

      {/* Position sizing */}
      <Panel title="Position Sizing" tag={`max risk ${inr(RISK_PER_TRADE)}/trade — floor, never round up`}>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
          <Input label="Entry (option ₹)" value={entry} onChange={setEntry} placeholder="premium" />
          <Input label="Stop (option ₹)" value={stop} onChange={setStop} placeholder="premium" />
          <Input label="Est. cost+slip / unit (₹)" value={perUnitCost} onChange={setPerUnitCost} placeholder="e.g. 1.5" />
          <Input label="Verified lot size" value={lotSize} onChange={setLotSize} placeholder="VERIFY — no default" />
          <Input label="Target (option ₹, opt.)" value={target} onChange={setTarget} placeholder="for R:R" />
        </div>
        <SizingReadout sizing={sizing} />
      </Panel>

      {/* C. PRE-TRADE GATE TABLE */}
      <Panel title="C · Pre-Trade Gates" tag="all 12 must PASS — any FAIL/UNKNOWN ⇒ no trade">
        <div className="space-y-1.5">
          {GATE_LABELS.map((label, i) => (
            <div key={i} className="flex items-center gap-3 rounded-md border border-line bg-raised/30 px-3 py-2">
              <span className="w-5 shrink-0 font-mono text-[10px] text-muted">{i + 1}</span>
              <span className="min-w-0 flex-1 font-mono text-[11px] text-ink/90">{label}</span>
              <div className="flex shrink-0 gap-1">
                {(["PASS", "FAIL", "UNKNOWN"] as Gate[]).map((g) => (
                  <button key={g} onClick={() => setGate(i, g)}
                    className={`rounded px-2 py-0.5 font-mono text-[9px] font-bold uppercase transition-colors ${
                      gates[i] === g ? "text-bg" : "text-muted hover:text-ink"
                    }`}
                    style={{ background: gates[i] === g ? GATE_COLOR[g] : "var(--bg-3)" }}>
                    {g === "UNKNOWN" ? "?" : g}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
        <div className="mt-3 flex gap-4 font-mono text-[10px] text-muted">
          <span style={{ color: "var(--green)" }}>{gates.filter((g) => g === "PASS").length} pass</span>
          <span style={{ color: "var(--red)" }}>{gates.filter((g) => g === "FAIL").length} fail</span>
          <span style={{ color: "var(--gold)" }}>{gates.filter((g) => g === "UNKNOWN").length} unknown</span>
        </div>
      </Panel>

      {/* D. VERDICT */}
      <VerdictBox verdict={verdict} anyFail={anyFail} anyUnknown={anyUnknown}
        hardBlocks={hardBlocks} gates={gates} sizing={sizing} />

      {/* E. CONDITIONAL TRADE PLAN (only when CANDIDATE) */}
      {verdict === "CANDIDATE" && sizing.ready && (
        <Panel title="E · Conditional Trade Plan" tag="educational conditional plan — not advice">
          <div className="grid grid-cols-1 gap-3 font-mono text-[11px] sm:grid-cols-2">
            <Kv k="Approved setup" v={`${setup} · ${SETUPS[setup]}`} />
            <Kv k="Underlying / direction" v={`${underlying} · ${direction}`} />
            <Kv k="Entry (premium)" v={inr(num(entry)!)} />
            <Kv k="Structural stop" v={inr(num(stop)!)} />
            <Kv k="Target" v={target ? inr(num(target)!) : "define before entry"} />
            <Kv k="Verified lot size" v={String(sizing.lot)} />
            <Kv k="Max permitted lots" v={String(sizing.permittedLots)} />
            <Kv k="Risk / unit (incl. costs)" v={inr(sizing.riskPerUnit)} />
            <Kv k="Max ₹ loss at stop" v={inr(sizing.maxLoss)} accent={sizing.maxLoss <= RISK_PER_TRADE ? "green" : "red"} />
            <Kv k="Reward : risk (after costs)" v={sizing.rr !== null ? `${sizing.rr.toFixed(2)}R` : "add target"}
              accent={sizing.rr !== null && sizing.rr >= 2 ? "green" : "gold"} />
          </div>
          <p className="mt-3 font-mono text-[10px] text-muted">
            Reminder: educational conditional plan, not a guaranteed or personalised advisory recommendation.
            Flatten before your broker/NSE intraday cut-off. Verify every price and contract is current before acting.
          </p>
        </Panel>
      )}

      {/* F. JOURNAL RECORD */}
      <JournalRecord ist={ist} underlying={underlying} setup={setup} direction={direction}
        verdict={verdict} gates={gates} sizing={sizing} />
    </div>
  );
}

/* ------------------------------ sub-components ------------------------------ */

const GATE_COLOR: Record<Gate, string> = {
  PASS: "var(--green)", FAIL: "var(--red)", UNKNOWN: "var(--gold)",
};
const SETUP_HINT: Record<string, string> = {
  A: "5m close beyond range + rel-vol + VWAP align; prefer retest, don't chase.",
  B: "15m & 5m aligned; HH/HL (or LL/LH); pullback to VWAP; confirmation candle.",
  C: "Only when range-bound & VWAP flat; trade boundary rejection; abort if it trends.",
};

function Disclaimer() {
  return (
    <div className="rounded-md border border-gold/25 bg-gold/5 px-4 py-2.5 font-mono text-[10px] leading-relaxed text-muted">
      ⚖ Educational conditional analysis only — <span className="text-gold">not SEBI-registered advice</span>, not a
      signal service. No profit promises, no certainty. Enforces your hard risk rules and defaults to NO TRADE on
      incomplete or conflicting evidence. You verify all data and own the execution & compliance decision.
    </div>
  );
}

function Panel({ title, tag, children }: { title: string; tag?: string; children: React.ReactNode }) {
  return (
    <div className="panel space-y-3 rounded-lg p-5">
      <h2 className="flex flex-wrap items-baseline gap-2 font-display text-sm font-bold text-ink">
        {title}
        {tag && <span className="font-mono text-[10px] font-normal text-muted">— {tag}</span>}
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

function Input({ label, value, onChange, placeholder }:
  { label: string; value: string; onChange: (v: string) => void; placeholder?: string }) {
  return (
    <label className="block">
      <span className="font-mono text-[9px] uppercase tracking-wider text-muted">{label}</span>
      <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} inputMode="decimal"
        className="mt-1 w-full rounded-md border border-line bg-bg/60 px-2.5 py-1.5 font-mono text-xs text-ink outline-none focus:border-cyan/50" />
    </label>
  );
}

function Select({ label, value, onChange, opts }:
  { label: string; value: string; onChange: (v: string) => void; opts: [string, string][] }) {
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

type Sizing =
  | { ready: false }
  | { ready: true; riskPerUnit: number; maxUnits: number; permittedLots: number; maxLoss: number; lot: number; rr: number | null; ok: boolean };

function SizingReadout({ sizing }: { sizing: Sizing }) {
  if (!sizing.ready) {
    return <p className="mt-3 font-mono text-[11px] text-muted">Enter entry, stop & verified lot size to compute sizing.</p>;
  }
  const zeroLots = sizing.permittedLots < 1;
  return (
    <div className="mt-3 space-y-2">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat k="Risk / unit" v={inr(sizing.riskPerUnit)} />
        <Stat k="Max units (₹1,000 ÷ risk)" v={String(sizing.maxUnits)} />
        <Stat k="Permitted lots" v={String(sizing.permittedLots)} accent={zeroLots ? "red" : "green"} />
        <Stat k="Max ₹ loss at stop" v={inr(sizing.maxLoss)} accent={sizing.maxLoss <= RISK_PER_TRADE ? "green" : "red"} />
      </div>
      <p className="font-mono text-[10px] text-muted">
        maxUnits = floor(₹{RISK_PER_TRADE.toLocaleString("en-IN")} ÷ risk/unit) · lots = floor(maxUnits ÷ lot). Never rounded up.
      </p>
      {zeroLots && (
        <div className="rounded-md border border-signalred/30 bg-signalred/10 px-3 py-2 font-mono text-[11px]" style={{ color: "var(--red)" }}>
          NO TRADE — one lot exceeds the ₹{RISK_PER_TRADE.toLocaleString("en-IN")} risk limit at this stop.
        </div>
      )}
    </div>
  );
}

function Stat({ k, v, accent }: { k: string; v: string; accent?: "green" | "red" | "gold" }) {
  const color = accent ? `var(--${accent})` : "var(--ink)";
  return (
    <div className="rounded-md border border-line bg-raised/30 px-3 py-2">
      <div className="font-mono text-[9px] uppercase tracking-wider text-muted">{k}</div>
      <div className="tnum text-sm font-bold" style={{ color }}>{v}</div>
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
  STOP_DAY: { label: "STOP FOR THE DAY — daily loss limit reached", color: "var(--red)", bg: "rgba(255,93,93,0.12)" },
  NO_TRADE: { label: "NO TRADE", color: "var(--red)", bg: "rgba(255,93,93,0.10)" },
  WAIT: { label: "WAIT FOR CONFIRMATION", color: "var(--gold)", bg: "rgba(244,185,66,0.10)" },
  CANDIDATE: { label: "TRADE CANDIDATE — conditional only", color: "var(--green)", bg: "rgba(88,214,141,0.10)" },
};

function VerdictBox({ verdict, anyFail, anyUnknown, hardBlocks, gates, sizing }:
  { verdict: Verdict; anyFail: boolean; anyUnknown: boolean;
    hardBlocks: string[]; gates: Gate[]; sizing: Sizing }) {
  const m = VERDICT_META[verdict];
  const failedGates = GATE_LABELS.map((l, i) => ({ l, g: gates[i], i }))
    .filter((x) => x.g !== "PASS");

  return (
    <div className="rounded-lg border p-5" style={{ borderColor: m.color + "55", background: m.bg }}>
      <div className="font-display text-lg font-bold" style={{ color: m.color }}>D · {m.label}</div>

      {verdict === "STOP_DAY" ? (
        <p className="mt-2 font-mono text-[11px] text-muted">
          Daily realised loss limit hit. No further analysis — close the terminal for the day.
        </p>
      ) : (
        <div className="mt-2 space-y-2 font-mono text-[11px] text-muted">
          {hardBlocks.length > 0 && (
            <div>
              <span className="text-signalred">Hard-rule blocks:</span>
              <ul className="ml-3 list-disc">{hardBlocks.map((b) => <li key={b}>{b}</li>)}</ul>
            </div>
          )}
          {sizing.ready && !sizing.ok && (
            <div className="text-signalred">Sizing block: one lot exceeds the ₹1,000 risk cap at this stop.</div>
          )}
          {(anyFail || anyUnknown) && (
            <div>
              <span style={{ color: anyFail ? "var(--red)" : "var(--gold)" }}>
                {failedGates.length} gate(s) not passing — each must be resolved:
              </span>
              <ul className="ml-3 mt-1 space-y-0.5">
                {failedGates.map((x) => (
                  <li key={x.i}>
                    <span style={{ color: x.g === "FAIL" ? "var(--red)" : "var(--gold)" }}>[{x.g}]</span> {x.i + 1}. {x.l}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {verdict === "CANDIDATE" && (
            <p style={{ color: "var(--green)" }}>
              All 12 gates pass, sizing within the ₹1,000 cap, and daily rules permit. Proceed only after re-verifying
              live prices/liquidity and confirming the trigger. This is a conditional candidate, not a recommendation.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function JournalRecord({ ist, underlying, setup, direction, verdict, gates, sizing }:
  { ist: string; underlying: string; setup: keyof typeof SETUPS; direction: string;
    verdict: Verdict; gates: Gate[]; sizing: Sizing }) {
  const failed = GATE_LABELS.map((_l, i) => ({ n: i + 1, g: gates[i] })).filter((x) => x.g !== "PASS");
  const decision = verdict === "CANDIDATE" ? "trade (conditional)"
    : verdict === "WAIT" ? "wait" : verdict === "STOP_DAY" ? "stopped for day" : "no trade";
  const text = [
    `Date/time (IST): ${ist}`,
    `Market: ${underlying} · intraday index options`,
    `Setup considered: ${setup} — ${SETUPS[setup]} (${direction})`,
    `Decision: ${decision}`,
    `Gates failed/unknown: ${failed.length ? failed.map((f) => `${f.n}[${f.g}]`).join(", ") : "none"}`,
    `Planned risk: ${sizing.ready ? inr(sizing.maxLoss) : "—"} (cap ₹1,000)`,
    `Permitted lots: ${sizing.ready ? sizing.permittedLots : "—"}`,
    `Actual result: __________ (fill after close)`,
    `Classification: PAPER-TRADE RESULT`,
  ].join("\n");

  return (
    <Panel title="F · Journal Record" tag="copy into your log — result left blank until filled">
      <pre className="overflow-x-auto whitespace-pre-wrap rounded-md border border-line bg-bg/60 p-3 font-mono text-[11px] text-ink/90">{text}</pre>
      <button onClick={() => navigator.clipboard?.writeText(text)}
        className="rounded-md border border-cyan/40 bg-cyan/10 px-3 py-1.5 font-mono text-[11px] font-bold text-cyan hover:bg-cyan/20">
        ⧉ Copy journal record
      </button>
    </Panel>
  );
}
