/**
 * The person's own two answers about the provider page in front of them.
 *
 * De-automation put the provider page in the PERSON'S OWN browser, which is the whole point - an
 * automation-controlled session is exactly what a bot check was catching while a person did the
 * clicking. The cost was the HUD: Stockroom cannot draw an overlay inside a window it does not own,
 * so the Finish and Try Another buttons that used to sit on the provider page went away and nothing
 * replaced them. A person-driven route then ended only on Stockroom's global Cancel, on roughly 25
 * seconds of quiet after at least one file had landed, or on the 600 second timeout - five times
 * over for DigiKey's five author routes.
 *
 * These are the replacements, and they live where Stockroom can actually draw them: its own window.
 *  - FINISH ROUTE means "no more files are coming from this page". It is not a discard: the route
 *    drains what is still landing and everything already adopted is attached exactly as it would
 *    have been.
 *  - SKIP THIS PART stops that component's remaining provider routes and moves on.
 *
 * NEITHER TOUCHES A PROVIDER PAGE. They describe the person's intent to Stockroom, which hands it
 * to the running capture through the same polled predicate a cancellation travels on.
 *
 * WHY THE GATE IS THE LANE, NOT THE ROUTE. These render for any capture in a person-driven lane
 * (assisted or Collect All Sources), not for one exact route, because a single Collect All run
 * interleaves routes a person works with routes Stockroom drives itself and the frontend has no
 * live per-route signal to switch on. Finish Route is therefore answered only by a route that is
 * actually waiting on a person; the copy below names that condition rather than implying the
 * button applies to every second of the run.
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
        Use these when a provider page is open in your own browser. Finish Route when you have
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
