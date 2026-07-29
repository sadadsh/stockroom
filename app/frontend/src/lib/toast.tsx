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
import { motion } from "motion/react";
import { Dot } from "../components/primitives";

export type ToastTone = "ok" | "err" | "neutral";

export interface ToastAction {
  label: string;
  onClick: () => void;
}

interface ToastItem {
  id: number;
  message: string;
  tone: ToastTone;
  action?: ToastAction;
}

interface ToastApi {
  toast: (message: string, tone?: ToastTone, action?: ToastAction) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

const DISMISS_MS = 4000;
const ACTION_DISMISS_MS = 8000;
let seq = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const dismiss = useCallback((id: number) => {
    setItems((current) => current.filter((t) => t.id !== id));
  }, []);

  const toast = useCallback(
    (message: string, tone: ToastTone = "neutral", action?: ToastAction) => {
      const id = (seq += 1);
      setItems((current) => [...current, { id, message, tone, action }]);
      setTimeout(() => dismiss(id), action ? ACTION_DISMISS_MS : DISMISS_MS);
    },
    [dismiss],
  );

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[100] flex flex-col gap-2">
        {items.map((t) => (
          <motion.div
            key={t.id}
            onClick={() => dismiss(t.id)}
            role="status"
            layout
            initial={{ opacity: 0, y: 8, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            transition={{ duration: 0.2, ease: "easeOut" }}
            className="pointer-events-auto flex items-center gap-2.5 rounded-card border border-line bg-raise2 px-3.5 py-2.5 text-left text-sm text-t1 shadow-pop"
          >
            <Dot tone={t.tone} />
            <span className="max-w-[320px]">{t.message}</span>
            {t.action ? (
              <button
                type="button"
                onClick={(event) => {
                  event.stopPropagation();
                  dismiss(t.id);
                  t.action?.onClick();
                }}
                className="ml-1 rounded-control px-2 py-1 text-xs font-semibold text-acc transition-colors hover:bg-acc/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc"
              >
                {t.action.label}
              </button>
            ) : null}
            <button
              type="button"
              aria-label={`Dismiss ${t.message}`}
              onClick={(event) => {
                event.stopPropagation();
                dismiss(t.id);
              }}
              className="ml-0.5 rounded-control px-1 text-t3 transition-colors hover:bg-raise hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc"
            >
              ×
            </button>
          </motion.div>
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
