/**
 * A one-slot bridge from the Ctrl+K palette (or any surface) to the Components
 * page: "select this part". The palette can fire on any route, so it queues the
 * requested id here and navigates to Components; the Components page subscribes on
 * mount and consumes it (clearing its filters so the requested part is guaranteed
 * to be in the list). The one-slot buffer covers the gap between the request
 * firing and the Components page mounting to subscribe. This mirrors
 * `ingestQueue.ts`, the same drop-to-page bridge the window-wide drop overlay uses.
 */
type Listener = (id: string) => void;

let listener: Listener | null = null;
let pending: string | null = null;

export function requestPart(id: string): void {
  if (listener) listener(id);
  else pending = id;
}

export function onRequestedPart(l: Listener): () => void {
  listener = l;
  if (pending !== null) {
    const buffered = pending;
    pending = null;
    l(buffered);
  }
  return () => {
    if (listener === l) listener = null;
  };
}
