/**
 * The person's two answers about the provider page currently embedded in Stockroom.
 *
 * The page and these controls share one app window while the backend keeps ownership of the route,
 * persistent provider session, and task-bound downloads.
 *  - FINISH ROUTE means "no more files are coming from this page". It is not a discard: the route
 *    drains what is still landing and everything already adopted is attached exactly as it would
 *    have been.
 *  - SKIP THIS PART stops that component's remaining provider routes and moves on.
 *
 * NEITHER TOUCHES A PROVIDER PAGE. They describe the person's intent to Stockroom, which hands it
 * to the running capture through the same polled predicate a cancellation travels on.
 *
 * These render only while the one Get Files workflow is waiting for a person. Finish Route is
 * therefore answered only by a route that actually has an embedded provider page open.
 */
import { captureAwaitsPerson, useCapture } from "../lib/capture";
import { Button } from "./primitives";

export function CaptureRouteControls({ partId }: { partId: string }) {
  const cap = useCapture();
  const active = cap.active;
  // Only the capture actually in front of the person, and only in a lane that can open a page for
  // them. A surface showing a different component, or an automatic pass that opens nothing, must
  // never offer to finish a route.
  if (active.partId !== partId || !captureAwaitsPerson(active)) return null;
  const pending = active.intentPending;

  return (
    <div data-testid="capture-route-controls">
      <div className="flex flex-wrap items-center gap-2">
        <Button small disabled={pending !== null} onClick={() => void cap.finishRoute()}>
          {pending === "finish-route" ? "Finishing Route" : "Finish Route"}
        </Button>
        <Button
          small
          variant="ghost-danger"
          disabled={pending !== null}
          onClick={() => void cap.skipPart()}
        >
          {pending === "skip-part" ? "Skipping" : "Skip This Part"}
        </Button>
      </div>
      {/* Names the CONDITION, not just the actions. A run can reach both routes a person works and
          routes Stockroom drives itself, and only the first kind has a page to be finished with;
          claiming otherwise would be claiming the button does something it cannot. */}
      <p className="mt-1 text-2xs leading-snug text-t2">
        Use these when a provider page is open in Stockroom. Finish Route when you have
        downloaded everything it offers: Stockroom keeps what already landed and moves on. Skip
        This Part stops this component&apos;s remaining routes.
      </p>
      {active.intentNote ? (
        <p className="mt-1 text-2xs leading-snug text-t3" role="status">
          {active.intentNote}
        </p>
      ) : null}
    </div>
  );
}
