/**
 * The app frame: the left rail plus the active page's content. Pages render only
 * their own body (header + panes); the shell owns the rail and the surface
 * background so every page reads consistent.
 */
import { useCallback, type ReactNode } from "react";
import { Rail } from "./Rail";
import { DropOverlay } from "./DropOverlay";
import { useRouter } from "../lib/router";
import { queuePaths } from "../lib/ingestQueue";

export function AppShell({ children }: { children: ReactNode }) {
  const { navigate } = useRouter();
  // A file dropped anywhere in the window goes to Ingest: queue the native paths,
  // then navigate there so the Ingest page consumes them and inspects.
  const handleDrop = useCallback(
    (paths: string[]) => {
      queuePaths(paths);
      navigate("ingest");
    },
    [navigate],
  );
  return (
    <div className="flex min-h-screen w-full bg-surface text-t1">
      <Rail />
      <div className="flex min-w-0 flex-1 flex-col">{children}</div>
      <DropOverlay onDrop={handleDrop} />
    </div>
  );
}
