import type { IvRank } from "../types";

// IV vs the name's own history: HIGH = options expensive to BUY, LOW = cheap. Context, not a signal.
export function IvRankBadge({ r }: { r: IvRank | null | undefined }) {
  if (!r) return null;
  const color = r.label === "HIGH" ? "var(--red)" : r.label === "LOW" ? "var(--green)" : r.label === "MID" ? "var(--gold)" : "var(--muted)";
  const hv = r.iv_hv != null ? ` · IV/HV20 ${r.iv_hv} (HV ${r.hv20}%)` : "";
  const range = r.iv_rank != null ? ` · rank ${r.iv_rank} · pct ${r.iv_pct} · ${r.iv_lo}–${r.iv_hi}% over ${r.days}d since ${r.since}` : "";
  return (
    <span
      className="font-mono text-[10px]"
      style={{ color }}
      title="IV rank: where today's ATM IV sits in this name's own range (0 = cheapest, 100 = richest). HIGH → buying options is expensive and IV tends to fall back; LOW → options are cheap. IV/HV > 1 → options price in more movement than the stock is delivering."
    >
      IV {r.iv ?? "—"}% · {r.label}{range}{hv}
    </span>
  );
}
