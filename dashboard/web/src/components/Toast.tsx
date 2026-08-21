import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

type ToastKind = "success" | "error" | "info";
interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
}

interface ToastCtx {
  push: (message: string, kind?: ToastKind) => void;
}

const Ctx = createContext<ToastCtx>({ push: () => {} });
export const useToast = () => useContext(Ctx);

const STYLES: Record<ToastKind, string> = {
  success: "border-emerald-500 bg-emerald-950/90 text-emerald-100",
  error: "border-rose-500 bg-rose-950/90 text-rose-100",
  info: "border-sky-500 bg-sky-950/90 text-sky-100",
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const push = useCallback((message: string, kind: ToastKind = "success") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, kind, message }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4800);
  }, []);

  return (
    <Ctx.Provider value={{ push }}>
      {children}
      <div className="fixed bottom-5 right-5 z-50 flex flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`max-w-sm whitespace-pre-line rounded-xl border px-4 py-3 text-xs font-semibold shadow-2xl backdrop-blur animate-[fadeIn_.2s_ease] ${STYLES[t.kind]}`}
          >
            {t.message}
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}
