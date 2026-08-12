/**
 * The persistent guided-capture status pill. When a capture is sent to the background ("Keep
 * Working"), this stays pinned bottom-right so the user can keep moving while the files land: it
 * shows the part, a live segment meter, and the current status, and clicking it reopens that
 * part's Complete-Part window. On a terminal state (done / needs attention) it can be dismissed.
 * Reads the single active capture from the global store; renders nothing when none is backgrounded.
 */
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { useCapture } from "../lib/capture";
import { useCopyFormatter, useText } from "../lib/copy";
import { useRouter } from "../lib/router";
import type { GuidedStatus } from "../lib/captureRequirements";

const STATUS_LABEL: Record<GuidedStatus, string> = {
  idle: "",
  resolving: "Looking up",
  "window-open": "Needs your input",
  receiving: "Capturing",
  attaching: "Attaching",
  done: "Complete",
  "timed-out": "Needs attention",
  unavailable: "No source",
  error: "Needs attention",
};

export function CaptureStatusPill() {
  const cap = useCapture();
  const { navigate } = useRouter();
  const dismissLabel = useText("capture.dismiss", "Dismiss");
  // The part name is data; this stands in for it before the capture reports one, so it is copy and
  // is resolved as a string because it shares a slot with that data.
  const unnamedCapture = useText("capture.unnamed-part", "Guided Capture");
  // The pill's whole accessible name: what it reopens, and for which part.
  const thisPart = useText("capture.this-part", "this part");
  const reopenName = useCopyFormatter(
    "capture.reopen-aria",
    "Reopen the guided capture for {part}",
  );
  const a = cap.active;
  const visible = !!a.partId && a.backgrounded && a.status !== "idle";
  const received = a.needs.filter((n) => a.received[n]).length;
  const total = a.needs.length;
  const isDone = a.status === "done";
  const isAttention = a.status === "timed-out" || a.status === "error" || a.status === "unavailable";
  const terminal = isDone || isAttention;

  function reopen() {
    cap.requestReopen();
    navigate("components");
  }

  return (
    <AnimatePresence>
      {visible ? (
        <m.div
          className="fixed bottom-4 right-4 z-[90] flex items-center gap-1"
          initial={{ opacity: 0, y: 14, scale: 0.96 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 14, scale: 0.96 }}
          transition={{ duration: 0.22, ease: "easeOut" }}
        >
          <button
            data-dev-role="capture.status"
            type="button"
            onClick={reopen}
            aria-label={reopenName({ part: a.partName ?? thisPart })}
            className="flex w-[248px] items-center gap-3 rounded-card border border-line2 bg-popover px-3.5 py-2.5 text-left shadow-pop transition-colors hover:brightness-110"
          >
            <span
              className={
                "grid h-7 w-7 flex-none place-items-center rounded-control " +
                (isDone ? "bg-ok/20 text-ok-text" : isAttention ? "bg-warn/20 text-warn" : "bg-raise2 text-t1")
              }
            >
              {isDone ? (
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={3} strokeLinecap="round" strokeLinejoin="round" className="h-3 w-3">
                  <path d="M20 6 9 17l-5-5" />
                </svg>
              ) : isAttention ? (
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5">
                  <path d="M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" />
                </svg>
              ) : (
                <m.span
                  className="h-2.5 w-2.5 rounded-full bg-t1"
                  animate={{ opacity: [1, 0.35, 1] }}
                  transition={{ duration: 1.4, repeat: Infinity, ease: "easeInOut" }}
                />
              )}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium text-t1">
                {a.partName ?? unnamedCapture}
              </span>
              <span className="mt-0.5 flex items-center gap-2">
                <span className={"text-2xs " + (isDone ? "text-ok-text" : isAttention ? "text-warn" : "text-t3")}>
                  {STATUS_LABEL[a.status]}
                </span>
                {total > 0 && !isAttention ? (
                  <span className="flex items-center gap-1.5">
                    <span className="flex gap-0.5">
                      {a.needs.map((n) => (
                        <span
                          key={n}
                          className={"h-1.5 w-2.5 rounded-full " + (a.received[n] ? "bg-ok" : "bg-raise2")}
                        />
                      ))}
                    </span>
                    <span className="tnum font-mono text-2xs text-t3">
                      {received}/{total}
                    </span>
                  </span>
                ) : null}
              </span>
            </span>
          </button>
          {terminal ? (
            <button
              type="button"
              onClick={() => cap.reset()}
              aria-label={dismissLabel}
              className="grid h-7 w-7 flex-none place-items-center rounded-control border border-line2 bg-popover text-t3 shadow-pop hover:text-t1"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" className="h-3.5 w-3.5">
                <path d="M18 6 6 18M6 6l12 12" />
              </svg>
            </button>
          ) : null}
        </m.div>
      ) : null}
    </AnimatePresence>
  );
}
