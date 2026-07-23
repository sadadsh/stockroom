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
import { useRouter } from "../lib/router";
import { useFacetsQuery } from "../api/queries";

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
    // A column: the rail + page row on top, a full-width Altium status bar pinned
    // across the very bottom (under everything, the way a docked app reads).
    <div data-dev-id="shell.root" className="flex h-screen w-full flex-col overflow-hidden bg-surface text-t1">
      <div className="flex min-h-0 flex-1">
        <Rail />
        <div data-dev-id="shell.content" className="flex min-w-0 flex-1 flex-col">{children}</div>
      </div>
      <ShellStatusBar />
      <DropOverlay onDrop={handleDrop} />
      <AddPartModal />
    </div>
  );
}

// The bottom status bar: an Altium signature, and honest about the library. The dot + label
// reflect the real facets query state (ready / loading / error); the right slot carries the
// live library part count and the active section. Reads global server state already cached by
// the pages, so it costs no extra request.
function ShellStatusBar() {
  const { route } = useRouter();
  const facets = useFacetsQuery();
  const total = facets.data
    ? Object.values(facets.data.by_category).reduce((sum, n) => sum + n, 0)
    : null;
  const section = route.charAt(0).toUpperCase() + route.slice(1);
  // State labels reuse the app's own noun for the collection ("components", as in the
  // rail, the list title, and the parts count) - no new vocabulary, and no y-words.
  const state = facets.isError
    ? { dot: "bg-err", label: "Component load failed" }
    : facets.isLoading
      ? { dot: "bg-t3", label: "Loading components" }
      : { dot: "bg-ok", label: "Components loaded" };
  return (
    <footer
      data-dev-id="shell.statusbar"
      className="flex h-[24px] flex-none items-center gap-2.5 border-t border-line bg-band px-3 text-2xs text-t2"
    >
      <span className="flex items-center gap-1.5">
        <span className={"inline-block h-[6px] w-[6px] flex-none rounded-full " + state.dot} />
        {state.label}
      </span>
      <span className="text-t3">/</span>
      <span className="text-t3">{section}</span>
      {total != null ? (
        <span className="ml-auto tabular-nums text-t3">{total.toLocaleString()} parts</span>
      ) : null}
    </footer>
  );
}
