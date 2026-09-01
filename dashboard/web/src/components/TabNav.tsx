export type TabId = "ideas" | "plumbing" | "journal" | "intraday" | "swing" | "exits" | "vcp" | "options" | "fno" | "backtest";

// Ordered by the daily workflow: take trades → manage → review → find → tools.
const TABS: { id: TabId; label: string; no: string; hint: string }[] = [
  { id: "intraday", label: "Today", no: "01", hint: "trade now" },
  { id: "swing", label: "Swing", no: "02", hint: "hold overnight" },
  { id: "exits", label: "Exits", no: "03", hint: "manage / exit" },
  { id: "journal", label: "Journal", no: "04", hint: "review + costs" },
  { id: "ideas", label: "Ideas", no: "05", hint: "trade ideas" },
  { id: "vcp", label: "Screener", no: "06", hint: "VCP setups" },
  { id: "options", label: "Greeks", no: "07", hint: "option pricing" },
  { id: "fno", label: "F&O Plan", no: "08", hint: "weekly plan" },
  { id: "backtest", label: "Backtest", no: "09", hint: "grade a system" },
  { id: "plumbing", label: "Plumbing", no: "10", hint: "orders / diag" },
];

export function TabNav({ active, onChange }: { active: TabId; onChange: (t: TabId) => void }) {
  return (
    <div className="flex gap-1 overflow-x-auto border-b border-line font-mono">
      {TABS.map((t) => {
        const on = t.id === active;
        return (
          <button
            key={t.id}
            onClick={() => onChange(t.id)}
            className={`group relative flex shrink-0 flex-col items-start px-4 py-2.5 transition-colors ${
              on ? "text-gold" : "text-muted hover:text-ink"
            }`}
          >
            <span className="flex items-baseline gap-2 text-sm font-semibold">
              <span className="text-[10px] tabular-nums opacity-60">{t.no}</span>
              <span className="tracking-wide">{t.label}</span>
            </span>
            <span className={`mt-0.5 text-[9px] font-normal lowercase tracking-wide ${on ? "text-gold/70" : "text-muted/60"}`}>
              ({t.hint})
            </span>
            <span
              className={`absolute inset-x-2 bottom-0 h-[2px] rounded-full bg-gold transition-transform duration-300 ${
                on ? "scale-x-100" : "scale-x-0 group-hover:scale-x-50"
              }`}
              style={{ boxShadow: on ? "0 0 12px var(--gold)" : "none" }}
            />
          </button>
        );
      })}
    </div>
  );
}
