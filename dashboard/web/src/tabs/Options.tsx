import { useEffect, useState } from "react";
import { api } from "../api";
import type { OptionsForm, OptionsResponse } from "../types";

const DEFAULT: OptionsForm = { spot: 24000, strike: 24200, days_to_expiry: 7, volatility: 0.15, option_type: "CALL" };

export function Options() {
  const [form, setForm] = useState<OptionsForm>(DEFAULT);
  const [res, setRes] = useState<OptionsResponse | null>(null);
  const set = <K extends keyof OptionsForm>(k: K, v: OptionsForm[K]) => setForm((f) => ({ ...f, [k]: v }));

  useEffect(() => {
    const id = setTimeout(() => { api.optionsPricing(form).then(setRes).catch(() => {}); }, 250);
    return () => clearTimeout(id);
  }, [form]);

  const g = res?.greeks;
  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      {/* Inputs + price */}
      <div className="panel space-y-5 rounded-lg p-6">
        <h2 className="font-display text-lg font-bold text-ink">Black-Scholes · Greeks</h2>
        <div className="grid grid-cols-2 gap-4 font-mono text-sm">
          <Num label="Spot (₹)" value={form.spot} onChange={(v) => set("spot", v)} />
          <Num label="Strike (₹)" value={form.strike} onChange={(v) => set("strike", v)} />
          <Num label="Days to expiry" value={form.days_to_expiry} onChange={(v) => set("days_to_expiry", v)} />
          <Num label="IV (%)" value={Math.round(form.volatility * 1000) / 10} step={0.5} onChange={(v) => set("volatility", v / 100)} />
          <div className="col-span-2">
            <label className="text-xs uppercase tracking-wider text-muted">Type</label>
            <div className="mt-1 flex gap-1 rounded-md border border-line bg-raised p-1">
              {(["CALL", "PUT"] as const).map((t) => (
                <button key={t} onClick={() => set("option_type", t)}
                  className={`flex-1 rounded px-3 py-1.5 text-xs font-bold uppercase tracking-wider transition ${form.option_type === t ? "bg-gold/20 text-gold" : "text-muted hover:text-ink"}`}>{t}</button>
              ))}
            </div>
          </div>
        </div>

        <div className="rounded-md border border-gold/30 bg-gold/5 p-4 text-center">
          <div className="font-mono text-[10px] uppercase tracking-widest text-muted">fair value</div>
          <div className="font-mono text-4xl font-bold text-gold tnum">{res?.calculated_price != null ? `₹${res.calculated_price}` : "—"}</div>
          <div className="font-mono text-[10px] text-muted">{res?.engine}</div>
        </div>

        <div className="grid grid-cols-5 gap-2">
          <Greek label="Δ delta" v={g?.delta} />
          <Greek label="Γ gamma" v={g?.gamma} />
          <Greek label="Θ theta" v={g?.theta} />
          <Greek label="ν vega" v={g?.vega} />
          <Greek label="ρ rho" v={g?.rho} />
        </div>
      </div>

      {/* Payoff */}
      <div className="panel space-y-3 rounded-lg p-6">
        <h2 className="font-display text-lg font-bold text-ink">Expiry Payoff</h2>
        <PayoffChart form={form} premium={res?.calculated_price ?? 0} />
        <p className="font-mono text-[10px] text-muted">Long {form.option_type.toLowerCase()} · premium ₹{res?.calculated_price ?? "—"} · breakeven at expiry shown dashed.</p>
      </div>
    </div>
  );
}

function PayoffChart({ form, premium }: { form: OptionsForm; premium: number }) {
  const W = 520, H = 300, pad = 34;
  const lo = form.strike * 0.9, hi = form.strike * 1.1;
  const N = 60;
  const pts: { s: number; pl: number }[] = [];
  for (let i = 0; i <= N; i++) {
    const s = lo + ((hi - lo) * i) / N;
    const intrinsic = form.option_type === "CALL" ? Math.max(0, s - form.strike) : Math.max(0, form.strike - s);
    pts.push({ s, pl: intrinsic - premium });
  }
  const plMin = Math.min(...pts.map((p) => p.pl), 0);
  const plMax = Math.max(...pts.map((p) => p.pl), 0);
  const x = (s: number) => pad + ((s - lo) / (hi - lo)) * (W - 2 * pad);
  const y = (pl: number) => H - pad - ((pl - plMin) / (plMax - plMin || 1)) * (H - 2 * pad);
  const line = pts.map((p, i) => `${i ? "L" : "M"}${x(p.s).toFixed(1)},${y(p.pl).toFixed(1)}`).join(" ");
  const breakeven = form.option_type === "CALL" ? form.strike + premium : form.strike - premium;
  const zeroY = y(0);
  // Split area into loss (below 0) and profit (above 0) via clip
  const area = `M${x(lo)},${zeroY} ` + pts.map((p) => `L${x(p.s).toFixed(1)},${y(p.pl).toFixed(1)}`).join(" ") + ` L${x(hi)},${zeroY} Z`;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
      <defs>
        <linearGradient id="plg" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--green)" stopOpacity="0.28" />
          <stop offset={`${((zeroY - pad) / (H - 2 * pad)) * 100}%`} stopColor="var(--green)" stopOpacity="0.05" />
          <stop offset={`${((zeroY - pad) / (H - 2 * pad)) * 100}%`} stopColor="var(--red)" stopOpacity="0.05" />
          <stop offset="100%" stopColor="var(--red)" stopOpacity="0.28" />
        </linearGradient>
      </defs>
      {/* grid */}
      {[0, 0.25, 0.5, 0.75, 1].map((t) => (
        <line key={t} x1={pad} x2={W - pad} y1={pad + t * (H - 2 * pad)} y2={pad + t * (H - 2 * pad)} stroke="var(--line)" />
      ))}
      <path d={area} fill="url(#plg)" />
      <line x1={pad} x2={W - pad} y1={zeroY} y2={zeroY} stroke="var(--muted)" strokeDasharray="2 3" />
      {/* strike + breakeven */}
      <line x1={x(form.strike)} x2={x(form.strike)} y1={pad} y2={H - pad} stroke="var(--gold)" strokeOpacity="0.5" strokeDasharray="4 3" />
      <line x1={x(breakeven)} x2={x(breakeven)} y1={pad} y2={H - pad} stroke="var(--cyan)" strokeOpacity="0.6" strokeDasharray="1 3" />
      <path d={line} fill="none" stroke="var(--gold)" strokeWidth="2.5" strokeLinejoin="round" />
      <text x={x(form.strike)} y={H - 8} fill="var(--gold)" fontSize="9" fontFamily="IBM Plex Mono" textAnchor="middle">K {form.strike}</text>
      <text x={x(breakeven)} y={pad - 6} fill="var(--cyan)" fontSize="9" fontFamily="IBM Plex Mono" textAnchor="middle">BE {breakeven.toFixed(0)}</text>
    </svg>
  );
}

function Num({ label, value, onChange, step }: { label: string; value: number; onChange: (n: number) => void; step?: number }) {
  return (
    <div>
      <label className="text-xs uppercase tracking-wider text-muted">{label}</label>
      <input type="number" step={step} value={value} onChange={(e) => onChange(parseFloat(e.target.value) || 0)}
        className="mt-1 w-full rounded-md border border-line bg-raised px-3 py-2 font-mono text-ink outline-none focus:border-gold" />
    </div>
  );
}

function Greek({ label, v }: { label: string; v: number | null | undefined }) {
  return (
    <div className="rounded-md border border-line bg-raised/50 p-2 text-center">
      <div className="font-mono text-[9px] uppercase text-muted">{label}</div>
      <div className="font-mono text-sm font-bold text-ink tnum">{v ?? "—"}</div>
    </div>
  );
}
