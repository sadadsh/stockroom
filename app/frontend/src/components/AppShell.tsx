/**
 * The app frame: the left rail plus the active page's content. Pages render only
 * their own body (header + panes); the shell owns the rail and the surface
 * background so every page reads consistent.
 */
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Rail } from "./Rail";
import { AddPartModal } from "./AddPartModal";
import { Text } from "../lib/copy";
import { plural } from "../lib/plural";
import { useRouter } from "../lib/router";
import {
  useActivateProfile,
  useFacetsQuery,
  useProfiles,
  useUpdateCheck,
} from "../api/queries";
import { RunningVersionIndicator } from "./RunningVersionIndicator";

export function AppShell({ children }: { children: ReactNode }) {
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
      <AddPartModal />
    </div>
  );
}

// The bottom status bar: an Altium signature, and honest about the app's real state. Left:
// the components load state (Title Case, no status dot) and the active section, named from
// the nav registry so "stm" reads "STM Viewer", never a capitalized route slug. Right: the
// working context that matters day to day - the exact running revision, its remotely proven
// standing, and the active profile. All read from queries the app already caches.
function ShellStatusBar() {
  const { route } = useRouter();
  const facets = useFacetsQuery();
  const update = useUpdateCheck();
  // The library's SCALE, which is a fact worth a permanent slot. This segment used to read
  // "Components Loaded / Components": it said Components twice (the second was the section name,
  // already obvious from the rail's active item) and carried no information, since "loaded" is true
  // almost always. The section name is gone for the same reason - the rail already says where you are.
  const total = facets.data ? facets.data.complete + facets.data.incomplete : null;
  const incomplete = facets.data?.incomplete ?? 0;
  return (
    <footer
      data-dev-id="shell.statusbar"
      className="flex h-[24px] flex-none items-center gap-2.5 border-t border-line bg-band px-3 text-2xs text-t2"
    >
      {route !== "components" ? (
        <span className="text-t2">
          {route === "projects"
            ? "Projects"
            : route === "stm"
              ? "STM Viewer"
              : "Settings"}
        </span>
      ) : facets.isError ? (
        <span className="text-err">
          <Text id="shell.status.load-failed">Could Not Load Components</Text>
        </span>
      ) : total == null ? (
        <span className="text-t3">
          <Text id="shell.status.loading">Loading Components</Text>
        </span>
      ) : (
        <>
          {/* Agrees with its number: this read "1 Components" on 10 of the 12 captured screens.
              The NUMBER stays outside <Text>, whose id maps to one overridable string - folding a
              count into it would mint a different copy key for every library size. */}
          <span className="tnum font-medium text-t1">
            {total.toLocaleString()}{" "}
            <Text id="shell.status.count">{plural(total, "Component")}</Text>
          </span>
          {incomplete > 0 ? (
            <>
              <span className="text-line2">|</span>
              {/* the number worth ACTING on, so it earns the warn tone rather than a quiet grey */}
              <span className="tnum text-warn">
                {incomplete} <Text id="shell.status.incomplete">Missing Data</Text>
              </span>
            </>
          ) : null}
        </>
      )}
      <span className="ml-auto flex items-center gap-2.5 text-t2">
        <RunningVersionIndicator
          data={update.data}
          checking={update.isPending || update.isFetching}
          failed={update.isError}
        />
        <ProfileSwitch />
      </span>
    </footer>
  );
}

/**
 * The active profile, and a way to CHANGE it (punch 13b).
 *
 * The bar already called `useProfiles()` and rendered the name as dead text - it had zero
 * interactive elements in it. Switching a profile repoints the whole library, so the one place the
 * active profile is always visible is the right place to switch it from.
 */
function ProfileSwitch() {
  const profiles = useProfiles();
  const activate = useActivateProfile();
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const active = profiles.data?.active ?? "";
  const others = (profiles.data?.profiles ?? []).filter((name) => name !== active);

  // Escape and an outside pointer both close it. A popover that can only be dismissed by clicking
  // its own trigger again is a trap, and the Filters popover next door already has that flaw.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    const onDown = (e: PointerEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onDown);
    };
  }, [open]);

  if (!active) return null;
  return (
    <div ref={wrapRef} className="relative">
      <button
        type="button"
        data-dev-id="shell.profile-switch"
        aria-expanded={open}
        disabled={activate.isPending || others.length === 0}
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1 rounded-control px-1 py-0.5 text-2xs text-t2 transition-colors hover:text-t1 disabled:pointer-events-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-acc"
      >
        <span className="text-t2">
          <Text id="shell.status.profile">Profile</Text>:
        </span>
        <span className="font-semibold text-t1">{active}</span>
        {others.length > 0 ? (
          <span aria-hidden className="text-t3">
            {open ? "▾" : "▴"}
          </span>
        ) : null}
      </button>
      {open ? (
        // opens UPWARD: the bar is the last row on screen, so a downward menu would be clipped by
        // the window edge (the same mistake the CAD readiness popover shipped with)
        <div
          data-dev-id="shell.profile-menu"
          className="absolute bottom-[calc(100%+6px)] right-0 z-[80] min-w-[160px] rounded-card border border-line2 bg-popover p-1 shadow-pop"
        >
          {others.map((name) => (
            <button
              key={name}
              type="button"
              onClick={() => {
                setOpen(false);
                activate.mutate(name);
              }}
              className="block w-full truncate rounded-control px-2 py-1 text-left text-2xs text-t2 transition-colors hover:bg-[var(--c-hover)] hover:text-t1"
            >
              {name}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
