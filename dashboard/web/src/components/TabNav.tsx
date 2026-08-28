export type TabId = "ideas" | "plumbing" | "journal" | "intraday" | "vcp" | "options" | "fno" | "backtest";

const TABS: { id: TabId; label: string; no: string }[] = [
  { id: "ideas", label: "Ideas", no: "01" },
  { id: "plumbing", label: "Plumbing", no: "02" },
  { id: "journal", label: "Journal", no: "03" },
  { id: "intraday", label: "Intraday", no: "04" },
  { id: "vcp", label: "Screener", no: "05" },
  { id: "options", label: "Greeks", no: "06" },
  { id: "fno", label: "F&O Plan", no: "07" },
  { id: "backtest", label: "Backtest", no: "08" },
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
            className={`group relative flex shrink-0 items-baseline gap-2 px-4 py-3 text-sm font-semibold transition-colors ${
              on ? "text-gold" : "text-muted hover:text-ink"
            }`}
          >
            <span className="text-[10px] tabular-nums opacity-60">{t.no}</span>
            <span className="tracking-wide">{t.label}</span>
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
