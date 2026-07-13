/**
 * A tiny bridge from the window-wide drop overlay to the Ingest page. A drop can
 * land while the user is on any route, so the overlay queues the dropped native
 * paths here and navigates to Ingest; the Ingest page subscribes on mount and
 * consumes them. A one-slot buffer covers the gap between the drop firing and the
 * Ingest page mounting to subscribe.
 */
type Listener = (paths: string[]) => void;

let listener: Listener | null = null;
let pending: string[] | null = null;

export function queuePaths(paths: string[]): void {
  if (listener) listener(paths);
  else pending = paths;
}

export function onQueuedPaths(l: Listener): () => void {
  listener = l;
  if (pending) {
    const buffered = pending;
    pending = null;
    l(buffered);
  }
  return () => {
    if (listener === l) listener = null;
  };
}
