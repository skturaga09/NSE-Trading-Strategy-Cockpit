// H — Phase 9 journal and feedback forms. Everything entered here is ACTUAL and is stored only: no weight, threshold or
// config changes anywhere (engine/ledger.py). Prices are typed in rupees; the backend stores paise.
import { useState, type FormEvent, type ReactNode } from "react";
import { post, useEnv, type View } from "../api";
import { Chip, LedgerBadge, Panel } from "../core";
import type { RadarRow } from "./Radar";

type Result = { ok: boolean; trade_id?: string; ledger: string } | { error: string } | null;
const field = "fo-h-control fo-rounded-md fo-border fo-border-line fo-bg-raised fo-px-4";

function Form({ title, onSubmit, children }: { title: string; onSubmit: (f: FormData) => Promise<unknown>; children: ReactNode }) {
  const [res, setRes] = useState<Result>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setBusy(true);
    try { setRes((await onSubmit(new FormData(e.currentTarget))) as Result); } catch (err) { setRes({ error: String((err as Error).message) }); }
    setBusy(false);
  };
  return (
    <form onSubmit={submit} aria-label={title} className="fo-grid fo-gap-3 fo-rounded-md fo-border fo-border-line fo-p-5">
      <div className="fo-flex fo-items-center fo-gap-3"><h4 className="fo-m-0 fo-text-sm fo-font-semibold">{title}</h4><LedgerBadge ledger="ACTUAL" /></div>
      {children}
      <div className="fo-flex fo-items-center fo-gap-4">
        <button type="submit" disabled={busy} className={`${field} fo-cursor-pointer fo-border-accent fo-text-accent`}>save</button>
        {res && ("error" in res ? <span role="alert" className="fo-text-xs fo-text-bearish">{res.error}</span>
          : <Chip tone="ok">saved{res.trade_id ? ` · ${res.trade_id}` : ""}</Chip>)}
      </div>
    </form>
  );
}

const L = ({ label, children }: { label: string; children: ReactNode }) => (
  <label className="fo-grid fo-gap-1 fo-text-xs"><span className="fo-text-muted">{label}</span>{children}</label>);
const n = (f: FormData, k: string) => (f.get(k) === "" || f.get(k) == null ? null : Number(f.get(k)));
const s = (f: FormData, k: string) => (f.get(k) === "" || f.get(k) == null ? null : String(f.get(k)));

export function Journal({ view }: { view: View }) {
  const radar = useEnv<{ rows: RadarRow[] }>("radar", view);
  const trades = useEnv<Record<"SIMULATED" | "ACTUAL", { id: string; underlying: string }[]>>("trades", view);
  const recs = radar.data?.data?.rows ?? [];
  const actual = trades.data?.data?.ACTUAL ?? [];
  const recSelect = (
    <select name="recommendation_id" required className={field}>
      <option value="">— recommendation —</option>
      {recs.map((r) => <option key={r.recommendation_id} value={r.recommendation_id}>{r.symbol} {r.direction} {r.status} · {r.recommendation_id}</option>)}
    </select>);
  return (
    <Panel title="Journal and feedback" env={radar.data} error={radar.error}>
      <p className="fo-m-0 fo-mb-5 fo-text-xs fo-text-muted">Record what you actually did. These forms write to the ACTUAL ledger and the feedback table only; they never change a threshold, weight or config.</p>
      <div className="fo-grid fo-gap-5 lg:fo-grid-cols-2">
        <Form title="I took this trade" onSubmit={(f) => post("/journal/take", { date: view.date, recommendation_id: s(f, "recommendation_id"),
          price_inr: n(f, "price"), qty: n(f, "qty"), time: s(f, "time") })}>
          <L label="recommendation">{recSelect}</L>
          <L label="fill price (₹)"><input name="price" type="number" step="0.05" min="0" required className={field} /></L>
          <L label="quantity (units)"><input name="qty" type="number" step="1" min="1" required className={field} /></L>
          <L label="fill time (IST)"><input name="time" type="datetime-local" step="1" required className={field} /></L>
        </Form>
        <Form title="I skipped it" onSubmit={(f) => post("/journal/skip", { recommendation_id: s(f, "recommendation_id"), reason: s(f, "reason") })}>
          <L label="recommendation">{recSelect}</L>
          <L label="reason"><input name="reason" required maxLength={500} className={field} /></L>
        </Form>
        <Form title="I exited" onSubmit={(f) => post("/journal/exit", { trade_id: s(f, "trade_id"), price_inr: n(f, "price"), qty: n(f, "qty"), time: s(f, "time") })}>
          <L label="ACTUAL trade"><select name="trade_id" required className={field}><option value="">— trade —</option>
            {actual.map((t) => <option key={t.id} value={t.id}>{t.underlying} · {t.id}</option>)}</select></L>
          <L label="exit price (₹)"><input name="price" type="number" step="0.05" min="0" required className={field} /></L>
          <L label="quantity (units)"><input name="qty" type="number" step="1" min="1" required className={field} /></L>
          <L label="exit time (IST)"><input name="time" type="datetime-local" step="1" required className={field} /></L>
        </Form>
        <Form title="Feedback" onSubmit={(f) => post("/feedback", { ledger: "ACTUAL", recommendation_id: s(f, "recommendation_id"),
          trade_id: s(f, "trade_id"), taken: f.get("taken") === "yes", skip_reason: s(f, "skip_reason"),
          actual_entry_inr: n(f, "entry"), actual_exit_inr: n(f, "exit"), slippage_inr_per_unit: n(f, "slippage"),
          execution_quality: s(f, "quality"), behaved_as_expected: s(f, "behaved"), notes: s(f, "notes") ?? "" })}>
          <L label="recommendation">{recSelect}</L>
          <L label="ACTUAL trade (if taken)"><select name="trade_id" className={field}><option value="">—</option>
            {actual.map((t) => <option key={t.id} value={t.id}>{t.underlying} · {t.id}</option>)}</select></L>
          <L label="taken?"><select name="taken" className={field}><option>yes</option><option>no</option></select></L>
          <L label="skip reason"><input name="skip_reason" maxLength={500} className={field} /></L>
          <div className="fo-grid fo-grid-cols-3 fo-gap-3">
            <L label="actual entry (₹)"><input name="entry" type="number" step="0.05" min="0" className={field} /></L>
            <L label="actual exit (₹)"><input name="exit" type="number" step="0.05" min="0" className={field} /></L>
            <L label="slippage (₹/unit)"><input name="slippage" type="number" step="0.05" className={field} /></L>
          </div>
          <L label="execution quality"><input name="quality" maxLength={100} className={field} /></L>
          <L label="setup behaved as expected"><select name="behaved" className={field}><option value="">—</option><option>yes</option><option>no</option><option>partly</option></select></L>
          <L label="notes"><textarea name="notes" maxLength={2000} rows={3} className="fo-rounded-md fo-border fo-border-line fo-bg-raised fo-p-4" /></L>
        </Form>
      </div>
    </Panel>
  );
}
