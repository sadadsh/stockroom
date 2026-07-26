/**
 * The in-app board / schematic viewer (M7 #11). Embeds the vendored kicanvas WebGL viewer
 * (MIT, self-hosted from /vendor, no CDN) and feeds it the selected project file as INLINE
 * <kicanvas-source> text fetched WITH the bearer, so kicanvas never issues its own
 * unauthenticated fetch and nothing weakens the per-launch token guard. The heavy kicanvas.js
 * bundle is injected lazily, once, only when a project is actually viewed (the ModelViewer
 * idiom). Every non-happy path is honest: loading, a 404 / fetch failure, or a browser that
 * cannot load the viewer degrades to a message instead of a blank canvas.
 *
 * kicanvas auto-detects board vs schematic from the inlined content (it dispatches on
 * "(kicad_pcb" / "(kicad_sch"), so no type attribute is needed; a key on the embed forces a
 * fresh parse when the selected file changes.
 */
import { useEffect, useState } from "react";
import type React from "react";
import { ApiError } from "../api/client";
import { useProjectFile } from "../api/queries";

// The vendored bundle self-registers <kicanvas-embed> / <kicanvas-source>; they are not known
// to JSX, so declare them (children carry the inlined file text).
declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace JSX {
    interface IntrinsicElements {
      "kicanvas-embed": React.DetailedHTMLProps<
        React.HTMLAttributes<HTMLElement> & { controls?: string; theme?: string },
        HTMLElement
      >;
      "kicanvas-source": React.DetailedHTMLProps<
        React.HTMLAttributes<HTMLElement>,
        HTMLElement
      >;
    }
  }
}

export interface ViewFile {
  path: string;
  label: string;
  kind: "Board" | "Schematic";
}

// Inject kicanvas.js once (a module-level singleton) from the SPA's OWN origin (not the API
// origin), served self-hosted from public/vendor. Resolves when the custom element is defined;
// rejects if the script fails to load (an offline dev server, a missing vendor asset).
let kicanvasLoad: Promise<void> | null = null;
function loadKicanvas(): Promise<void> {
  if (kicanvasLoad) return kicanvasLoad;
  kicanvasLoad = new Promise<void>((resolve, reject) => {
    if (typeof customElements !== "undefined" && customElements.get("kicanvas-embed")) {
      resolve();
      return;
    }
    const s = document.createElement("script");
    s.type = "module";
    s.src = `${import.meta.env.BASE_URL}vendor/kicanvas.js`;
    s.onload = () => {
      customElements.whenDefined("kicanvas-embed").then(() => resolve(), reject);
    };
    s.onerror = () => reject(new Error("could not load the viewer"));
    document.head.appendChild(s);
  });
  return kicanvasLoad;
}

function Centered({ children, testId }: { children: React.ReactNode; testId?: string }) {
  return (
    <div
      className="flex h-full min-h-[280px] w-full items-center justify-center px-6 text-center text-sm text-t3"
      data-testid={testId}
    >
      {children}
    </div>
  );
}

export function ProjectViewer({ projectId, files }: { projectId: string; files: ViewFile[] }) {
  const [active, setActive] = useState(files[0]?.path ?? "");
  const [scriptReady, setScriptReady] = useState(false);
  const [scriptError, setScriptError] = useState(false);
  const query = useProjectFile(projectId, active || null);

  useEffect(() => {
    let cancelled = false;
    loadKicanvas().then(
      () => !cancelled && setScriptReady(true),
      () => !cancelled && setScriptError(true),
    );
    return () => {
      cancelled = true;
    };
  }, []);

  // Re-sync the selected file when `files` changes: if the current selection is not among them
  // (the first render had none because the detail query was still loading / had errored, then a
  // refetch populated them), point at the first file. Without this a single-file project, which
  // shows no tab bar to click, would stay stuck on "Loading viewer..." forever.
  useEffect(() => {
    if (files.length > 0 && !files.some((f) => f.path === active)) {
      setActive(files[0].path);
    }
  }, [files, active]);

  if (files.length === 0) {
    return (
      <Centered>
        This project has no board or schematic to view. Register a project with a .kicad_pcb or
        .kicad_sch to see it here.
      </Centered>
    );
  }

  return (
    <div data-testid="project-viewer">
      {files.length > 1 ? (
        <div
          role="tablist"
          className="mb-3 inline-flex flex-wrap gap-1 rounded-control bg-raise p-1"
          data-testid="viewer-tabs"
        >
          {files.map((f) => {
            const on = f.path === active;
            return (
              <button
                key={f.path}
                type="button"
                role="tab"
                aria-selected={on}
                onClick={() => setActive(f.path)}
                data-testid={`viewer-tab-${f.path}`}
                className={
                  "rounded-control px-2.5 py-1 text-xs font-medium transition-colors " +
                  (on ? "bg-raise2 text-t1" : "text-t2 hover:text-t1")
                }
              >
                {f.label}
              </button>
            );
          })}
        </div>
      ) : null}

      <div className="overflow-hidden rounded-card border border-line bg-field">
        {scriptError ? (
          <Centered>
            The board viewer could not load on this machine. The rest of the project is
            unaffected.
          </Centered>
        ) : query.isError ? (
          <Centered testId="viewer-error">
            {query.error instanceof ApiError ? query.error.message : "Could not load this file."}
          </Centered>
        ) : query.isLoading || !scriptReady || !query.data ? (
          <Centered>Loading viewer...</Centered>
        ) : (
          <kicanvas-embed
            key={active}
            controls="basic"
            className="block h-[440px] w-full"
            data-testid="kicanvas-embed"
          >
            <kicanvas-source>{query.data}</kicanvas-source>
          </kicanvas-embed>
        )}
      </div>
    </div>
  );
}
