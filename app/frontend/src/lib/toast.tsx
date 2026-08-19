/**
 * Quiet toasts. Background work and mutation results report here (per the design
 * spec: "background work reports through quiet toasts"), never through an OS
 * dialog. A toast auto-dismisses; clicking it dismisses early.
 */
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import * as m from "motion/react-m";
import { Icon } from "../components/Icon";
import { Dot } from "../components/primitives";
import { useCopyFormatter } from "./copy";

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
  toast: (
    message: string,
    tone?: ToastTone,
    action?: ToastAction,
    lifetimeMs?: number | null,
  ) => () => void;
}

const ToastContext = createContext<ToastApi | null>(null);

const DISMISS_MS = 4000;
const ACTION_DISMISS_MS = 8000;
let seq = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  // The dismiss control is a glyph, so its accessible name is the only text it has. The message in
  // the hole is whatever the toast is carrying; the verb around it is ours.
  const dismissName = useCopyFormatter("toast.dismiss-aria", "Dismiss {message}");

  const dismiss = useCallback((id: number) => {
    setItems((current) => current.filter((t) => t.id !== id));
  }, []);

  const toast = useCallback(
    (message: string, tone: ToastTone = "neutral", action?: ToastAction, lifetimeMs?: number | null) => {
      const id = (seq += 1);
      setItems((current) => [...current, { id, message, tone, action }]);
      const timeoutMs = lifetimeMs === undefined ? (action ? ACTION_DISMISS_MS : DISMISS_MS) : lifetimeMs;
      if (timeoutMs !== null) setTimeout(() => dismiss(id), timeoutMs);
      return () => dismiss(id);
    },
    [dismiss],
  );

  // `toast` is already stable, but the object around it was not: this provider re-renders on every
  // toast raised and every toast dismissed, and a fresh `{ toast }` each time re-rendered EVERY
  // `useToast` consumer in the application - which is most of the surfaces, none of which have
  // anything to redraw because a toast appeared somewhere else.
  const api = useMemo(() => ({ toast }), [toast]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[100] flex flex-col gap-2">
        {items.map((t) => (
          <m.div
            key={t.id}
            onClick={() => dismiss(t.id)}
            role="status"
            data-dev-id="toast.status"
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
                className="ml-1 rounded-control px-2 py-1 text-xs font-semibold text-acc transition-colors hover:bg-acc/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
              >
                {t.action.label}
              </button>
            ) : null}
            <button
              type="button"
              aria-label={dismissName({ message: t.message })}
              onClick={(event) => {
                event.stopPropagation();
                dismiss(t.id);
              }}
              className="ml-0.5 rounded-control px-1 text-t3 transition-colors hover:bg-raise hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
            >
              <Icon id="action.close" className="h-3.5 w-3.5" />
            </button>
          </m.div>
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
