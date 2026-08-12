/**
 * The app frame: the left rail plus the active page's content. Pages render only
 * their own body (header + panes); the shell owns the rail and the surface
 * background so every page reads consistent.
 */
import type { ReactNode } from "react";
import { Rail } from "./Rail";
import { AddPartModal } from "./AddPartModal";
import { Text, useCopyFormatter } from "../lib/copy";
import { useRouter } from "../lib/router";
import { useFacetsQuery, useOnboarding } from "../api/queries";
import { useUpdateStanding } from "../lib/useUpdateStanding";
import { useDevMode } from "../lib/devMode";
import { RunningVersionIndicator } from "./RunningVersionIndicator";
import { useScenarioUiState } from "../design-studio/scenarioState";
import { useEffect } from "react";
import { useTheme } from "../lib/theme";

export function AppShell({ children }: { children: ReactNode }) {
  const scenario = useScenarioUiState();
  const { setTheme } = useTheme();
  useEffect(() => {
    if (scenario.theme) setTheme(scenario.theme);
  }, [scenario.theme, setTheme]);
  return (
    // h-screen (not min-h-screen) so a tall page scrolls INSIDE its own pane and
    // the window never grows a body scrollbar that shifts the rail between pages.
    // A column: the rail + page row on top, a full-width Altium status bar pinned
    // across the very bottom (under everything, the way a docked app reads).
    <div data-dev-id="shell.root" data-source-promotion-state={scenario.sourcePromotion?.state} className="flex h-screen w-full flex-col overflow-hidden bg-surface text-t1">
      <div className="flex min-h-0 flex-1">
        <Rail />
        <div data-dev-id="shell.content" className="flex min-w-0 flex-1 flex-col">{children}</div>
      </div>
      <ShellStatusBar />
      <AddPartModal />
    </div>
  );
}

// The bottom status bar: an Altium signature, and honest about the app's real state. Left:
// the components load state (Title Case, no status dot) and the active section, named from
// the nav registry so "stm" reads "STM Viewer", never a capitalized route slug. Right: the
// working context that matters day to day - the exact running revision, its remotely proven
// standing, and the active library repository. All read from queries the app already caches.
function ShellStatusBar() {
  const { route } = useRouter();
  const facets = useFacetsQuery();
  const { view: updateView } = useUpdateStanding();
  // The library's SCALE, which is a fact worth a permanent slot. This segment used to read
  // "Components Loaded / Components": it said Components twice (the second was the section name,
  // already obvious from the rail's active item) and carried no information, since "loaded" is true
  // almost always. The section name is gone for the same reason - the rail already says where you are.
  // A commit hash is a build fact. The standing ("Update Available") is what a person can act
  // on and stays visible; the revision identities are drawn only in developer mode, and the
  // accessible name carries them either way.
  const { enabled: devMode } = useDevMode();
  const total = facets.data ? facets.data.complete + facets.data.incomplete : null;
  const incomplete = facets.data?.incomplete ?? 0;
  return (
    <footer
      data-dev-id="shell.statusbar"
      className="flex h-[24px] flex-none items-center gap-2.5 border-t border-line bg-band px-3 text-2xs text-t2"
    >
      {route !== "components" ? (
        <span className="text-t2">
          {route === "projects" ? (
            <Text id="shell.status.section-projects">Projects</Text>
          ) : route === "stm" ? (
            <Text id="shell.status.section-stm">STM Viewer</Text>
          ) : (
            <Text id="shell.status.section-settings">Settings</Text>
          )}
        </span>
      ) : facets.isError ? (
        <span className="text-err-text">
          <Text id="shell.status.load-failed">Could Not Load Components</Text>
        </span>
      ) : total == null ? (
        <span className="text-t3">
          <Text id="shell.status.loading">Loading Components</Text>
        </span>
      ) : (
        <>
          {/* The library SIZE is already the count beside the picker's own title, three inches to
              the left, so stating it again here said nothing twice. What survives is the number
              that is not on screen anywhere else and that someone can act on. */}
          <span className="text-t2">
            <Text id="shell.status.ready">Prepared</Text>
          </span>
          {incomplete > 0 ? (
            <>
              <span className="text-line2">|</span>
              {/* the number worth ACTING on, so it earns the warn tone rather than a quiet grey */}
              <span className="tnum text-warn">
                <Text id="shell.status.incomplete" values={{ count: incomplete }}>
                  {"{count} Missing Data"}
                </Text>
              </span>
            </>
          ) : null}
        </>
      )}
      <span className="ml-auto flex items-center gap-2.5 text-t2">
        {/* The running revision identity is a BUILD fact, and a permanent `r4f2a9c1` in the corner
            of a component library is developer output on a user's screen. It appears when the
            update standing is something other than settled - which is the only moment it explains
            anything - and otherwise lives in About and in developer mode. */}
        {updateView.standing !== "current" ? (
          <RunningVersionIndicator view={updateView} identity={devMode} />
        ) : null}
        <LibraryStatus />
      </span>
    </footer>
  );
}

/**
 * The active independent library repository. Repository switching lives in Settings where its
 * filesystem and Git consequences are explicit; the status bar is a quiet, permanent fact.
 */
function LibraryStatus() {
  const onboarding = useOnboarding();
  // The accessible name is a sentence with a slot, so it can be reworded without a call site
  // deciding where the library's name goes.
  const libraryLabel = useCopyFormatter("shell.status.library-label", "Catalog: {name}");
  const active = onboarding.data?.libraries.find((library) => library.active);
  if (!active) return null;
  return (
    <span
      data-dev-id="shell.library"
      aria-label={libraryLabel({ name: active.name })}
      className="inline-flex min-w-0 items-center gap-1 text-t2"
    >
      <span><Text id="shell.status.library">Catalog</Text>:</span>
      <span className="max-w-[220px] truncate font-semibold text-t1">{active.name}</span>
    </span>
  );
}
