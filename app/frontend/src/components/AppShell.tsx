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
import { NAV } from "../lib/nav";
import { Text } from "../lib/copy";
import {
  useFacetsQuery,
  useProfiles,
  useUpdateCheck,
} from "../api/queries";

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

// The bottom status bar: an Altium signature, and honest about the app's real state. Left:
// the components load state (Title Case, no status dot) and the active section, named from
// the nav registry so "stm" reads "STM Viewer", never a capitalized route slug. Right: the
// working context that matters day to day - the active profile and an update notice when one
// exists. All read from queries the app already caches, so the bar costs nothing extra.
function ShellStatusBar() {
  const { route } = useRouter();
  const facets = useFacetsQuery();
  const profiles = useProfiles();
  const update = useUpdateCheck();
  const section = NAV.find((entry) => entry.route === route)?.title ?? route;
  return (
    <footer
      data-dev-id="shell.statusbar"
      className="flex h-[24px] flex-none items-center gap-2.5 border-t border-line bg-band px-3 text-2xs text-t2"
    >
      <span className={facets.isError ? "text-err" : undefined}>
        {facets.isError ? (
          <Text id="shell.status.load-failed">Component Load Failed</Text>
        ) : facets.isLoading ? (
          <Text id="shell.status.loading">Loading Components</Text>
        ) : (
          <Text id="shell.status.loaded">Components Loaded</Text>
        )}
      </span>
      <span className="text-t3">/</span>
      <span className="text-t3">{section}</span>
      <span className="ml-auto flex items-center gap-2.5 text-t3">
        {profiles.data?.active ? (
          <span>
            <Text id="shell.status.profile">Profile</Text> {profiles.data.active}
          </span>
        ) : null}
        {update.data?.update_available ? (
          <>
            <span className="text-line2">|</span>
            <span className="text-t2">
              <Text id="shell.status.update">Update Available</Text>
            </span>
          </>
        ) : null}
      </span>
    </footer>
  );
}
