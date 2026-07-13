/**
 * Quiet toasts. Background work and mutation results report here (per the design
 * spec: "background work reports through quiet toasts"), never through an OS
 * dialog. A toast auto-dismisses; clicking it dismisses early.
 */
import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from "react";
import { Dot } from "../components/primitives";

export type ToastTone = "ok" | "err" | "neutral";

interface ToastItem {
  id: number;
  message: string;
  tone: ToastTone;
}

interface ToastApi {
  toast: (message: string, tone?: ToastTone) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

const DISMISS_MS = 4000;
let seq = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const dismiss = useCallback((id: number) => {
    setItems((current) => current.filter((t) => t.id !== id));
  }, []);

  const toast = useCallback(
    (message: string, tone: ToastTone = "neutral") => {
      const id = (seq += 1);
      setItems((current) => [...current, { id, message, tone }]);
      setTimeout(() => dismiss(id), DISMISS_MS);
    },
    [dismiss],
  );

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[100] flex flex-col gap-2">
        {items.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => dismiss(t.id)}
            role="status"
            className="pointer-events-auto flex items-center gap-2.5 rounded-card border border-line bg-raise2 px-3.5 py-2.5 text-left text-sm text-t1 shadow-pop transition-colors hover:brightness-110"
          >
            <Dot tone={t.tone} />
            <span className="max-w-[320px]">{t.message}</span>
          </button>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within a ToastProvider");
  return ctx;
}
