// Core building blocks of the F&O Engine module. Every value shown comes from a backend field; an UNAVAILABLE field
// renders "—" with its reason. Formatting (paise → ₹, ns → IST clock) is display only: no trading logic here.
import { createContext, useContext, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import type { Envelope, Maybe, Unavail } from "./api";

export const isU = (v: unknown): v is Unavail => typeof v === "object" && v !== null && "UNAVAILABLE" in v;

// ---------------------------------------------------------------- root: scoping + theme + portal container
const PortalCtx = createContext<HTMLElement | null>(null);

function appTheme(): "light" | "dark" {
  return document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
}

export function FoRoot({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState(appTheme);
  const [portal, setPortal] = useState<HTMLElement | null>(null);
  useEffect(() => {
    // mirror the app's theme switch (read-only observation of its attribute; nothing is written outside the root)
    const o = new MutationObserver(() => setTheme(appTheme()));
    o.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => o.disconnect();
  }, []);
  return (
    <div data-fo-engine="" data-fo-theme={theme}>
      <PortalCtx.Provider value={portal}>{children}</PortalCtx.Provider>
      <div data-fo-portal="" ref={setPortal} />
    </div>
  );
}

// ---------------------------------------------------------------- tooltip (rendered into the scoped portal)
export function Tip({ text, children }: { text: string; children: ReactNode }) {
  const portal = useContext(PortalCtx);
  const ref = useRef<HTMLSpanElement>(null);
  const id = useId();
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  const show = () => {
    const el = ref.current, root = portal?.parentElement;
    if (!el || !root) return;
    const a = el.getBoundingClientRect(), r = root.getBoundingClientRect();
    setPos({ x: a.left - r.left, y: a.bottom - r.top + 4 });
  };
  return (
    <span ref={ref} tabIndex={0} aria-describedby={id} onMouseEnter={show} onMouseLeave={() => setPos(null)}
      onFocus={show} onBlur={() => setPos(null)} className="fo-cursor-help">
      {children}
      {portal && createPortal(
        <span id={id} role="tooltip" hidden={!pos}
          style={pos ? { left: pos.x, top: pos.y } : undefined}
          className="fo-absolute fo-max-w-tip fo-whitespace-pre-line fo-rounded-md fo-border fo-border-line fo-bg-raised fo-px-4 fo-py-3 fo-text-xs fo-text-ink fo-shadow-pop">
          {text}
        </span>, portal)}
    </span>
  );
}

// ---------------------------------------------------------------- values
export const inr = (paise: number) => `₹${(paise / 100).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
export const rupees = (v: number) => `₹${v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
export const pct = (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
export const num = (d = 2) => (v: number) => v.toLocaleString("en-IN", { maximumFractionDigits: d });
export const ist = (ns: number) =>
  new Date(ns / 1e6).toLocaleTimeString("en-GB", { timeZone: "Asia/Kolkata", hour12: false });
export const istFull = (ns: number) =>
  new Date(ns / 1e6).toLocaleString("en-GB", { timeZone: "Asia/Kolkata", hour12: false }) + " IST";

/** A backend value: the formatted number, or "—" with the UNAVAILABLE reason in a tooltip. */
export function V<T>({ v, f, className = "" }: { v: Maybe<T> | null | undefined; f?: (x: T) => string; className?: string }) {
  if (v === null || v === undefined) return <Tip text="no value from the backend"><span aria-label="unavailable" className="fo-text-unavailable">—</span></Tip>;
  if (isU(v)) return (
    <Tip text={v.UNAVAILABLE}><span aria-label={`unavailable: ${v.UNAVAILABLE}`} className="fo-text-unavailable">—</span></Tip>);
  return <span className={`fo-num ${className}`}>{f ? f(v as T) : String(v)}</span>;
}

export function Dir({ d }: { d: string }) {
  const up = d === "LONG" || d === "PRICE_UP";
  return <span className={up ? "fo-text-bullish" : "fo-text-bearish"}>{up ? "▲" : "▼"} {d}</span>;
}

export function LedgerBadge({ ledger }: { ledger: "SIMULATED" | "ACTUAL" }) {
  return ledger === "SIMULATED"
    ? <span data-ledger="SIMULATED" className="fo-sim-chip fo-rounded-sm fo-px-3 fo-text-2xs fo-font-semibold fo-tracking-wide">◇ SIMULATED</span>
    : <span data-ledger="ACTUAL" className="fo-act-chip fo-rounded-sm fo-px-3 fo-text-2xs fo-font-semibold fo-tracking-wide">◆ ACTUAL</span>;
}

export function Chip({ tone, children }: { tone: "ok" | "stale" | "unavailable" | "warning" | "accent"; children: ReactNode }) {
  const c = { ok: "fo-border-bullish fo-text-bullish", stale: "fo-border-stale fo-text-stale", unavailable: "fo-border-unavailable fo-text-unavailable",
    warning: "fo-border-warning fo-text-warning", accent: "fo-border-accent fo-text-accent" }[tone];
  return <span className={`fo-rounded-sm fo-border fo-px-3 fo-text-2xs fo-font-semibold fo-uppercase fo-tracking-wide ${c}`}>{children}</span>;
}

// ---------------------------------------------------------------- panel frame: data age + stale marking on every panel
export function Panel<T>({ title, env, error, children, right }: {
  title: string; env?: Envelope<T> | null; error?: unknown; children?: ReactNode; right?: ReactNode;
}) {
  const stale = env?.status === "STALE";
  return (
    <section aria-label={title} data-status={env?.status ?? (error ? "ERROR" : env === null ? "EMPTY" : "LOADING")}
      className={`fo-rounded-lg fo-border fo-bg-surface fo-shadow-panel ${stale ? "fo-border-stale fo-stale-hatch" : "fo-border-line"}`}>
      <header className="fo-flex fo-flex-wrap fo-items-center fo-gap-4 fo-border-b fo-border-line fo-px-5 fo-py-3">
        <h3 className="fo-m-0 fo-text-sm fo-font-semibold fo-uppercase fo-tracking-wider fo-text-ink">{title}</h3>
        {env && <AgeTag env={env} />}
        <div className="fo-ml-auto fo-flex fo-items-center fo-gap-4">{right}</div>
      </header>
      <div className="fo-p-5">
        {error ? <p role="alert" className="fo-m-0 fo-text-bearish">Backend error: {String((error as Error).message ?? error)}</p>
          : env === undefined ? <p className="fo-m-0 fo-text-muted">Loading…</p>
          : env === null ? children                                       // null = this panel needs no data (e.g. no row picked)
          : env.status === "UNAVAILABLE" && env.data == null
            ? <p className="fo-m-0 fo-text-unavailable">— {env.reason}</p> : children}
      </div>
    </section>
  );
}

export function AgeTag({ env }: { env: Envelope<unknown> }) {
  const p = env.provenance;
  const tip = [`source: ${p.source}`, p.observed_ns ? `observed: ${istFull(p.observed_ns)}` : "observed: —",
    p.received_ns ? `received: ${istFull(p.received_ns)}` : "received: —", p.processed_ns ? `processed: ${istFull(p.processed_ns)}` : "processed: —",
    `view time: ${istFull(env.now_ns)} (${env.mode})`, `stale after: ${env.stale_after_s ?? "—"} s`, `config ${env.config_version}`].join("\n");
  return (
    <Tip text={tip}>
      <span className="fo-flex fo-items-center fo-gap-3 fo-text-2xs fo-text-muted">
        <Chip tone={env.status === "OK" ? "ok" : env.status === "STALE" ? "stale" : "unavailable"}>{env.status}</Chip>
        <span data-testid="age" className="fo-num">age {env.age_s == null ? "—" : fmtAge(env.age_s)}</span>
        {env.mode === "REPLAY" && <Chip tone="accent">replay</Chip>}
      </span>
    </Tip>
  );
}

export function fmtAge(s: number) {
  if (s < 90) return `${s.toFixed(0)} s`;
  if (s < 5400) return `${(s / 60).toFixed(0)} min`;
  return `${(s / 3600).toFixed(1)} h`;
}
