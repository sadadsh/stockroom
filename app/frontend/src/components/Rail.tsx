/**
 * The left navigation rail (north-star .nav): a wordmark card at the top, the primary
 * destinations, and a footer pinned to the bottom that carries Settings and a single
 * utility controls. Every row shares one icon column and one label column, so pinning
 * and auto-collapsing never move a glyph.
 */
import { useEffect, useRef, useState, type ReactNode } from "react";
import { railNav, railRouteFor, type NavEntry } from "../lib/nav";
import { useRouter, type Route } from "../lib/router";
import { useTheme } from "../lib/theme";
import { useUpdateCheck } from "../api/queries";
import { Text, useText } from "../lib/copy";
import { Icon } from "./Icon";
import { readPref, writePref } from "../lib/uiPrefs";
import { useModalDismiss } from "../lib/useModalDismiss";
import { aboutVersion, deriveUpdateStanding } from "../lib/updateStanding";

// Collapsed labels stay in the accessibility tree but never grow an overlay over the workspace.
// The old hover peek expanded from 52px to 190px and then sustained its own :hover state. After a
// user chose a destination, the pointer had to cross that overlay to reach controls near the left
// edge, so it could intercept the next click (the STM Explorer / Bench tabs exposed this exactly).
// Native title tooltips identify the icons at rest; the explicit header control pins the rail open
// when persistent labels are wanted.
const COLLAPSED_LABEL = "w-0 overflow-hidden opacity-0";

/** One geometry for every rail control in every state.
 *
 * The 52px rail spends 16px on panel padding and 1px on its right border, leaving exactly 35px.
 * That is the icon column. The pinned 190px rail keeps the same 8px inset and adds only a label
 * column. Real WebView2 measurement before this structure found six different centers:
 * collapsed nav/about 25.5px, update 16px, theme 20.5px; pinned nav/about 30.5px, update 31px.
 * A grid makes those impossible: every left-column glyph now has the same 25.5px centerline. */
const RAIL_ROW =
  "grid h-[34px] w-full grid-cols-[35px_minmax(0,1fr)] items-center gap-2.5 " +
  "rounded-control px-0 text-left";
const RAIL_GLYPH = "flex h-[17px] w-[35px] items-center justify-center";

// The primary nav destinations. Each glyph was a sizeless `.ico` svg taking its 17px box from the
// parent span; <Icon>'s primary branch would inject its default h-3.5 box, so we pass h-full w-full
// to fill the identical 17px container (appearance preserved; the parent span stays).
const NAV_ICONS: Partial<Record<Route, ReactNode>> = {
  components: <Icon id="nav.components" className="h-full w-full" />,
  projects: <Icon id="nav.board" className="h-full w-full" />,
  stm: <Icon id="nav.stm" className="h-full w-full" />,
  settings: <Icon id="nav.settings" className="h-full w-full" />,
};

// Whether the rail is collapsed to icons. A WORKSPACE preference, so it persists the same
// best-effort way the theme does (punch 13a) - a rail that reopened on every launch would be a
// setting you re-apply forever. Read lazily so the first paint is already correct.
const RAIL_STORAGE_KEY = "stockroom.rail.collapsed";

// Below this WINDOW width an expanded rail costs the detail sheet its third column, so a rail
// nobody has touched starts collapsed instead.
//
// DERIVED, not picked: DetailPanel's grid needs a container of >=896px for three columns (its own
// comment states the breakpoint). Measured on the owner's real window at 1384px with the rail
// expanded, that container was 815px - so the chrome outside it costs window-189-815 = 380px (the
// part picker plus padding). Expanded, three columns therefore need 896+189+380 = 1465.
//
// One threshold, not two. Below ~1328 collapsing cannot buy the third column back either, and a
// narrow window is exactly where the extra 137px is worth most anyway, so there is no width at
// which an untouched rail is better off expanded.
const RAIL_NEEDS_COLLAPSE_BELOW = 1465;

/** The stored preference, or `undefined` when the user has never chosen one. */
function storedCollapsed(): boolean | undefined {
  // Host-injected preference first, localStorage only as the dev-server fallback. The host binds an
  // ephemeral port, so localStorage is empty on every launch and the collapsed rail always came
  // back expanded. See lib/uiPrefs.ts.
  //
  // `undefined` is the whole point of this signature: "collapsed=false" and "never chosen" are
  // different facts, and the old boolean-with-a-default could not tell them apart.
  return readPref<boolean | undefined>(
    "rail_collapsed",
    RAIL_STORAGE_KEY,
    (raw) => (raw === "1" ? true : raw === "0" ? false : undefined),
    undefined,
  );
}

function readCollapsed(): boolean {
  const chosen = storedCollapsed();
  if (chosen !== undefined) return chosen; // an explicit choice always wins, at any width
  try {
    return window.innerWidth < RAIL_NEEDS_COLLAPSE_BELOW;
  } catch {
    return false; // no window to measure (SSR / a test env): the old default
  }
}

export function Rail() {
  const { route, navigate } = useRouter();
  const [collapsed, setCollapsed] = useState(readCollapsed);
  // Persist only what the USER chose. This effect used to run on mount, which wrote the derived
  // value straight into the preference store - and after that first launch "never chosen" could
  // never occur again, on any machine, so the width would never be consulted a second time. A
  // default that records itself as a decision is not a default.
  const chosenByUser = useRef(storedCollapsed() !== undefined);
  useEffect(() => {
    if (chosenByUser.current) writePref("rail_collapsed", collapsed, RAIL_STORAGE_KEY);
  }, [collapsed]);
  const setCollapsedByUser = (next: boolean | ((v: boolean) => boolean)) => {
    chosenByUser.current = true;
    setCollapsed(next);
  };
  // Follow the window while it is still a default. Once chosen, this stops watching entirely.
  useEffect(() => {
    if (chosenByUser.current) return;
    const onResize = () => {
      if (!chosenByUser.current) setCollapsed(window.innerWidth < RAIL_NEEDS_COLLAPSE_BELOW);
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  const { toggle } = useTheme();
  const items = railNav();
  const primary = items.filter((item) => item.group === "primary");
  const footItems = items.filter((item) => item.group === "foot");
  const active = railRouteFor(route);

  const update = useUpdateCheck();
  const updateView = deriveUpdateStanding({
    data: update.data,
    checking: !!(update.isPending || update.isFetching),
    failed: !!update.isError,
  });
  const [aboutOpen, setAboutOpen] = useState(false);

  return (
    // COLLAPSED, the outer shell holds a fixed 52px of layout. Pinned open, the content reflows
    // exactly once. The collapsed rail never grows over the workspace, so left-edge controls remain
    // reachable immediately after navigation.
    <div className={collapsed ? "relative z-[60] w-[52px] flex-none" : "flex-none"}>
    <nav
      aria-label="Primary"
      data-dev-id="rail.root"
      className={
        // NOTE: no `bg-*` here. Two background utilities in one class list are resolved by STYLESHEET
        // order, not by the order they appear in the attribute - so a `bg-canvas` added alongside the
        // old `bg-rail` silently lost, and the overlay stayed see-through. Each branch owns its own.
        "group/rail flex flex-col border-r border-line py-4 " +
        "transition-[width,padding] duration-150 motion-reduce:transition-none " +
        (collapsed
          // A compact, opaque icon rail. Labels are available through the accessible name and
          // native title; the header toggle is the only operation that changes rail width.
          ? "absolute inset-y-0 left-0 h-full w-[52px] overflow-hidden px-2 " +
            // --c-rail is a translucent tint. Composite it over an opaque canvas base so content
            // never reads through the compact rail. Padding stays identical to the pinned rail,
            // keeping every glyph on one centerline.
            "bg-canvas [background-image:linear-gradient(var(--c-rail),var(--c-rail))]"
          : "bg-rail h-full w-[190px] px-2")
      }
    >
      {/* wordmark (north-star .wm): the rail's panel-title bar - same band + bottom hairline as every
          other docked panel header (Components list, the opened component), so the three panes read
          as one Altium workspace. Full-bleed to the rail edges via negative margins. */}
      <div
        data-dev-id="rail.wordmark"
        className="-mx-2 -mt-4 mb-3 flex h-[34px] flex-none items-center gap-2.5 border-b border-line bg-band px-2"
      >
        {!collapsed ? (
          <>
            {/* brand category, so <Icon> does NOT auto-add .ico; the original className (with the
                literal ico token) is passed through so --icon-stroke keeps retuning it. */}
            <span className={RAIL_GLYPH}>
              <Icon id="brand.wordmark" className="ico h-5 w-5 flex-none text-t1" />
            </span>
            <span className="whitespace-nowrap text-base font-semibold tracking-[-0.01em] text-t1">
              <Text id="nav.brand">Stockroom</Text>
            </span>
          </>
        ) : null}
        {/* The rail's collapse control lives HERE, in its panel-title bar, because that is where a
            docked panel's own controls belong - the same place Altium puts them. It used to sit at
            the foot as 10px t3 text beside a raw mono guillemet, which made the one control that
            reshapes the workspace the faintest thing in the rail.

            COLLAPSED, this button REPLACES the wordmark rather than crowding it: 52px of rail holds
            exactly one 17px control, and the brand is already stated by the OS title bar, while the
            toggle is the only thing here anyone can act on.

            One glyph serves both directions, mirrored on the x axis, so "collapse" and "expand" can
            never drift out of sync. */}
        <span className={collapsed ? RAIL_GLYPH : "contents"}>
          <button
            type="button"
            data-dev-id="rail.collapse"
            aria-label={collapsed ? "Expand Rail" : "Collapse Rail"}
            title={collapsed ? "Expand Rail" : "Collapse Rail"}
            aria-expanded={!collapsed}
            onClick={() => setCollapsedByUser((v) => !v)}
            className={
              "flex h-[24px] w-[24px] flex-none items-center justify-center rounded-control " +
              "text-t2 transition hover:bg-[var(--c-hover)] hover:text-t1 " +
              "focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 " +
              "focus-visible:outline-acc " +
              (collapsed ? "" : "ml-auto -mr-1")
            }
          >
            <span aria-hidden className="flex h-[17px] w-[17px] items-center justify-center">
              <Icon
                id="nav.collapse-rail"
                className={"h-full w-full" + (collapsed ? " -scale-x-100" : "")}
              />
            </span>
          </button>
        </span>
        {collapsed ? (
          <span
            className={
            COLLAPSED_LABEL +
              " whitespace-nowrap text-base font-semibold tracking-[-0.01em] text-t1"
            }
          >
            <Text id="nav.brand">Stockroom</Text>
          </span>
        ) : null}
      </div>

      <div data-dev-id="rail.nav" className="flex flex-col gap-0.5">
        {primary.map((item) => (
          <RailItem
            key={item.route}
            item={item}
            selected={active === item.route}
            collapsed={collapsed}
            onSelect={() => navigate(item.route)}
          />
        ))}
      </div>

      {/* Footer uses the exact same row geometry as primary navigation. */}
      <div
        data-dev-id="rail.footer"
        className="mt-auto flex flex-col gap-0.5 border-t border-line pt-2"
      >
        {footItems.map((item) => (
          <RailItem
            key={item.route}
            item={item}
            selected={active === item.route}
            collapsed={collapsed}
            onSelect={() => navigate(item.route)}
          />
        ))}
        <button
          type="button"
          data-dev-id="rail.about"
          aria-label={collapsed ? "About" : undefined}
          title={collapsed ? "About" : undefined}
          onClick={() => setAboutOpen(true)}
          className={
            RAIL_ROW +
            " text-sm font-medium text-t2 transition hover:bg-[var(--c-hover)] hover:text-t1"
          }
        >
          <span aria-hidden className={RAIL_GLYPH}>
            <Icon id="nav.about" className="h-full w-full" />
          </span>
          <span className={collapsed ? COLLAPSED_LABEL + " whitespace-nowrap" : ""}>
            <Text id="nav.about">About</Text>
          </span>
        </button>
        <div
          data-dev-id="rail.utility"
          className="flex flex-col items-stretch gap-0.5"
        >
          <div
            data-dev-id="rail.update"
            className={RAIL_ROW + " text-xs font-medium text-t2"}
            title={updateView.detail}
          >
            <span
              aria-hidden
              className={RAIL_GLYPH}
              style={
                updateView.standing === "current"
                  ? { color: "var(--c-ok)" }
                  : undefined
              }
            >
              <Icon
                id={
                  updateView.standing === "current"
                    ? "nav.up-to-date"
                    : "nav.update"
                }
                className="h-4 w-4 flex-none"
              />
            </span>
            <span className={collapsed ? COLLAPSED_LABEL + " whitespace-nowrap" : ""}>
              {updateView.standing === "available" ? (
                <Text id="nav.update-ready">Update Ready</Text>
              ) : updateView.standing === "current" ? (
                <Text id="nav.update-current">Current</Text>
              ) : updateView.standing === "updating" ? (
                <span>Updating...</span>
              ) : updateView.standing === "checking" ? (
                <Text id="nav.update-checking">Checking...</Text>
              ) : (
                <Text id="nav.update-unknown">Update Unknown</Text>
              )}
            </span>
          </div>
          <button
            type="button"
            data-dev-id="rail.theme-toggle"
            onClick={toggle}
            aria-label="Toggle light or dark theme"
            title="Toggle light or dark theme"
            className={
              RAIL_ROW +
              " text-xs font-medium text-t2 transition hover:bg-[var(--c-hover)] hover:text-t1"
            }
          >
            <span aria-hidden className={RAIL_GLYPH}>
              <Icon id="nav.theme" className="h-4 w-4 flex-none" />
            </span>
            {/* The peek label every other collapsed control carries. It is not decoration: without
                a second child this button had no flex GAP, so its glyph sat at the box centre
                (25.5) while every other rail glyph sat at 20.5, pulled left by the gap to its own
                zero-width label. Measured with `uishot --measure`, which now reports glyphCx.
                It also earns its place - the rail peek names every other control and named this
                one nothing. */}
            <span className={collapsed ? COLLAPSED_LABEL + " whitespace-nowrap" : ""}>
              <Text id="nav.theme">Theme</Text>
            </span>
          </button>
        </div>
      </div>
      {aboutOpen ? (
        <AboutModal
          onClose={() => setAboutOpen(false)}
          version={aboutVersion(update.data, __APP_VERSION__)}
        />
      ) : null}
    </nav>
    </div>
  );
}

// The About window: what this is + who made it, with links out. Opaque bg-popover over a scrim,
// the same idiom as the app's other modals.
//
// The comment here used to claim "Esc / a scrim click closes it". Only the scrim click was true.
// FOUND BY `windrive.py tour` 2026-07-25, which could not get past it: the sweep clicked About,
// then reported every control behind the scrim as unreachable and every later surface as
// UNREACHABLE, because nothing it tried would dismiss this dialog. Driven live, it carried
// **zero buttons** and ignored Escape, so the only way out was clicking a backdrop that advertises
// nothing. Seven other modals already adopted `useModalDismiss`; this one never did, while still
// declaring `role="dialog" aria-modal`. A modal that traps you is worse than a panel that does not
// claim to be one.
function AboutModal({ onClose, version }: { onClose: () => void; version: string }) {
  const aboutLabel = useText("modal.about.aria", "About Stockroom");
  // Always mounted only while open, so `open` is true whenever this renders. The hook owns Escape,
  // the focus move into the dialog and the focus restore on the way out.
  const dialogRef = useModalDismiss(true, onClose);
  return (
    <div
      data-dev-id="about.scrim"
      className="fixed inset-0 z-[95] flex items-center justify-center bg-black/55 p-4"
      role="presentation"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={aboutLabel}
        data-dev-id="about.root"
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        className="relative w-full max-w-[380px] rounded-card border border-line2 bg-popover p-6 text-center shadow-pop focus-visible:outline-none"
      >
        {/* A VISIBLE way out. Escape and the scrim both work now, and neither is discoverable by
            looking - this dialog had no control of any kind in it. */}
        <button
          type="button"
          data-dev-id="about.close"
          onClick={onClose}
          aria-label="Close About"
          title="Close About"
          className="absolute right-2 top-2 grid h-7 w-7 place-items-center rounded-control text-t3 transition-colors hover:bg-[var(--c-hover)] hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-acc"
        >
          <svg width="11" height="11" viewBox="0 0 11 11" fill="none" aria-hidden>
            <path d="M1 1l9 9M10 1l-9 9" stroke="currentColor" strokeWidth="1.5"
                  strokeLinecap="round" />
          </svg>
        </button>
        <div
          data-dev-id="about.icon"
          className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-control bg-raise2 shadow-card"
        >
          {/* brand category, so <Icon> does NOT auto-add .ico; the original className (with the literal
              ico token) is passed through so --icon-stroke keeps retuning it. Byte-identical output. */}
          <Icon id="brand.wordmark" className="ico h-6 w-6 text-t1" />
        </div>
        <div data-dev-id="about.title" className="text-lg font-semibold tracking-[-0.02em] text-t1">
          <Text id="modal.about.title">Stockroom</Text>
        </div>
        <p data-dev-id="about.credit" className="mt-1 text-sm text-t2">
          <Text id="modal.about.credit">Developed with love by </Text>
          <span className="font-medium text-t1">Sadad Haidari</span>.
        </p>
        <p className="mt-2 text-xs text-t3">
          <span className="font-medium">Version</span>{" "}
          <span className="tnum font-mono">{version}</span>
        </p>
        <div data-dev-id="about.links" className="mt-4 flex justify-center gap-2.5">
          <a
            href="https://www.linkedin.com/in/sadadhaidari"
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-2 rounded-control border border-line2 bg-raise2 px-3 py-2 text-xs font-semibold text-t2 shadow-card transition hover:text-t1 hover:brightness-110"
          >
            <Icon id="brand.linkedin" className="h-4 w-4" />
            <Text id="modal.about.linkedin">LinkedIn</Text>
          </a>
          <a
            href="https://github.com/sadadsh"
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-2 rounded-control border border-line2 bg-raise2 px-3 py-2 text-xs font-semibold text-t2 shadow-card transition hover:text-t1 hover:brightness-110"
          >
            <Icon id="brand.github" className="h-4 w-4" />
            <Text id="modal.about.github">GitHub</Text>
          </a>
        </div>
      </div>
    </div>
  );
}

function RailItem({
  item,
  selected,
  collapsed,
  onSelect,
}: {
  item: NavEntry;
  selected: boolean;
  collapsed: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      data-dev-id={`rail.nav-${item.route}`}
      aria-current={selected ? "page" : undefined}
      // Collapsed, the glyph is all there is, so the name has to come from aria-label (and `title`
      // gives the pointer the same thing). Without it every nav item reads as an unlabelled button.
      // `title` still gives the pointer a native tooltip at rest. No aria-label: the visible label
      // below is in the DOM even while collapsed (it is only visually hidden), so adding one would
      // announce every nav item twice.
      title={collapsed ? item.title : undefined}
      onClick={onSelect}
      className={
        RAIL_ROW + " text-sm transition " +
        (selected
          ? "bg-acc-soft font-semibold text-t1 shadow-[inset_2px_0_0_var(--c-acc)]"
          : "font-medium text-t2 hover:bg-[var(--c-hover)] hover:text-t1")
      }
    >
      <span aria-hidden className={RAIL_GLYPH}>
        {NAV_ICONS[item.route] ?? null}
      </span>
      {/* Always rendered so the accessible name is real text rather than a duplicate aria-label.
          Collapsed, it is clipped to zero width by the panel and faded out. */}
      <span
        className={
          "truncate whitespace-nowrap " + (collapsed ? COLLAPSED_LABEL : "")
        }
      >
        <Text id={`nav.${item.route}`}>{item.title}</Text>
      </span>
    </button>
  );
}
