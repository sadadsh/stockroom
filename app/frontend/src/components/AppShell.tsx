/**
 * The app frame: the left rail plus the active page's content. Pages render only
 * their own body (header + panes); the shell owns the rail and the surface
 * background so every page reads consistent.
 */
import { useCallback, useEffect, type ReactNode } from "react";
import { Rail } from "./Rail";
import { DropOverlay } from "./DropOverlay";
import { AddPartModal } from "./AddPartModal";
import { useAddPart } from "../lib/addPart";
import { queuePaths } from "../lib/ingestQueue";

export function AppShell({ children }: { children: ReactNode }) {
  const { open: openAddPart } = useAddPart();
  // A file dropped anywhere in the window goes to Add A Part: queue the native
  // paths, then open the modal so its flow consumes them and inspects.
  const handleDrop = useCallback(
    (paths: string[]) => {
      queuePaths(paths);
      openAddPart();
    },
    [openAddPart],
  );
  // The real drop channel on Windows: WebView2 only exposes dropped-file paths to
  // the HOST (via pywebview's DOM API), which forwards them through this hook. The
  // in-window DropOverlay still provides the drag scrim and covers any backend that
  // does expose pywebviewFullPath to the DOM.
  useEffect(() => {
    window.__STOCKROOM_NATIVE_DROP__ = (paths) => {
      const clean = Array.isArray(paths)
        ? paths.filter((p): p is string => typeof p === "string" && p.length > 0)
        : [];
      if (clean.length > 0) handleDrop(clean);
    };
    return () => {
      delete window.__STOCKROOM_NATIVE_DROP__;
    };
  }, [handleDrop]);
  return (
    // h-screen (not min-h-screen) so a tall page scrolls INSIDE its own pane and
    // the window never grows a body scrollbar that shifts the rail between pages.
    <div data-dev-id="shell.root" className="flex h-screen w-full overflow-hidden bg-surface text-t1">
      <Rail />
      <div data-dev-id="shell.content" className="flex min-w-0 flex-1 flex-col">{children}</div>
      <DropOverlay onDrop={handleDrop} />
      <AddPartModal />
    </div>
  );
}
