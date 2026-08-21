export type TabId = "ideas" | "plumbing" | "vcp" | "options" | "fno" | "backtest";

const TABS: { id: TabId; label: string; icon: string }[] = [
  { id: "ideas", label: "Trade Ideas", icon: "💡" },
  { id: "plumbing", label: "Plumbing & Orders", icon: "🔧" },
  { id: "vcp", label: "VCP Screener", icon: "🔍" },
  { id: "options", label: "Options & Greeks", icon: "🧮" },
  { id: "fno", label: "F&O Planner", icon: "📅" },
  { id: "backtest", label: "Backtest", icon: "📊" },
];

export function TabNav({ active, onChange }: { active: TabId; onChange: (t: TabId) => void }) {
  return (
    <div className="flex gap-1 overflow-x-auto rounded-2xl border border-slate-800 bg-slate-900/50 p-1">
      {TABS.map((t) => {
        const on = t.id === active;
        return (
          <button
            key={t.id}
            onClick={() => onChange(t.id)}
            className={`flex shrink-0 items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold transition-all ${
              on
                ? "bg-gradient-to-b from-indigo-500 to-indigo-600 text-white shadow-lg shadow-indigo-900/40"
                : "text-slate-400 hover:bg-slate-800/60 hover:text-slate-100"
            }`}
          >
            <span>{t.icon}</span>
            {t.label}
          </button>
        );
      })}
    </div>
  );
}
