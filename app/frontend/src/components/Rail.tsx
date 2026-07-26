/**
 * The left navigation rail (north-star .nav): a wordmark card at the top, the primary
 * destinations, and a footer pinned to the bottom that carries Settings and a single
 * utility row - the Update action (when one is available) sitting beside the light/dark
 * theme toggle. Icons are the artifact's own set, inline, so the rail matches the
 * north-star 1:1.
 */
import { useEffect, useState, type ReactNode } from "react";
import { railNav, railRouteFor, type NavEntry } from "../lib/nav";
import { useRouter, type Route } from "../lib/router";
import { useTheme } from "../lib/theme";
import { useApplyUpdate, useUpdateCheck } from "../api/queries";
import { ApiError } from "../api/client";
import { useToast } from "../lib/toast";
import { Text, useText } from "../lib/copy";
import { Icon } from "./Icon";
import { readPref, writePref } from "../lib/uiPrefs";
import { useModalDismiss } from "../lib/useModalDismiss";

// The peek's label reveal, in ONE place. Every label in the rail uses it, because the first cut wired
// only the primary nav and Settings - so hovering produced a panel where three of the bottom controls
// were still bare icons, which reads as broken rather than as compact.
const PEEK_LABEL =
  "w-0 overflow-hidden opacity-0 transition-opacity duration-150 motion-reduce:transition-none " +
  "[@media(hover:hover)]:group-hover/rail:w-auto [@media(hover:hover)]:group-hover/rail:opacity-100 " +
  "[@media(hover:hover)]:group-hover/rail:delay-150 " +
  "group-focus-within/rail:w-auto group-focus-within/rail:opacity-100";

/** A collapsed rail control becomes a labelled row during the peek. */
const PEEK_ROW =
  "[@media(hover:hover)]:group-hover/rail:justify-start " +
  "[@media(hover:hover)]:group-hover/rail:px-2.5 " +
  "group-focus-within/rail:justify-start group-focus-within/rail:px-2.5";

function errMsg(err: unknown): string {
  return err instanceof ApiError ? err.message : "Something went wrong.";
}

// The primary nav destinations. Each glyph was a sizeless `.ico` svg taking its 17px box from the
// parent span; <Icon>'s primary branch would inject its default h-3.5 box, so we pass h-full w-full
// to fill the identical 17px container (appearance preserved; the parent span stays).
const NAV_ICONS: Partial<Record<Route, ReactNode>> = {
  components: <Icon id="nav.components" className="h-full w-full" />,
  stm: <Icon id="nav.stm" className="h-full w-full" />,
  projects: <Icon id="nav.projects" className="h-full w-full" />,
  settings: <Icon id="nav.settings" className="h-full w-full" />,
};

// Whether the rail is collapsed to icons. A WORKSPACE preference, so it persists the same
// best-effort way the theme does (punch 13a) - a rail that reopened on every launch would be a
// setting you re-apply forever. Read lazily so the first paint is already correct.
const RAIL_STORAGE_KEY = "stockroom.rail.collapsed";

function readCollapsed(): boolean {
  // Host-injected preference first, localStorage only as the dev-server fallback. The host binds an
  // ephemeral port, so localStorage is empty on every launch and the collapsed rail always came
  // back expanded. See lib/uiPrefs.ts.
  return readPref<boolean>(
    "rail_collapsed",
    RAIL_STORAGE_KEY,
    (raw) => (raw === "1" ? true : raw === "0" ? false : undefined),
    false,
  );
}

export function Rail() {
  const { route, navigate } = useRouter();
  const [collapsed, setCollapsed] = useState(readCollapsed);
  useEffect(() => {
    writePref("rail_collapsed", collapsed, RAIL_STORAGE_KEY);
  }, [collapsed]);
  const { toggle } = useTheme();
  const items = railNav();
  const primary = items.filter((item) => item.group === "primary");
  const footItems = items.filter((item) => item.group === "foot");
  const active = railRouteFor(route);

  const update = useUpdateCheck();
  const hasUpdate = !!update.data?.update_available;
  const [aboutOpen, setAboutOpen] = useState(false);

  // The Update pill applies the update right here - the same flow (and the same toasts) as
  // Settings' Apply Update, so the two entry points can never behave differently.
  const apply = useApplyUpdate();
  const { toast } = useToast();
  const toastRestart = useText("settings.update.toast-restart", "Update applied. Restart to finish.");
  const toastApplied = useText("settings.update.toast-applied", "Update applied.");

  function onApplyUpdate() {
    apply.mutate(undefined, {
      onSuccess: (r) => {
        if (r.restart_requested) {
          toast(toastRestart, "neutral");
        } else if (r.updated) {
          toast(toastApplied, "ok");
        } else {
          toast(r.detail || r.state, "neutral");
        }
      },
      onError: (e) => toast(errMsg(e), "err"),
    });
  }

  return (
    // COLLAPSED, the outer shell holds a FIXED 52px of layout and the rail itself overlays on top of
    // it, so hovering reveals the labels WITHOUT reflowing the page (the owner's choice from previews,
    // 2026-07-26). Pinned open, there is no overlay at all and the content reflows exactly once.
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
          // The peek. `@media (hover:hover)` so a touch device never gets a state it cannot leave -
          // there the toggle is the only way, which is why the toggle stays. `focus-within` gives the
          // same expansion to the keyboard, and it is NOT paired with forcing focus inside: research
          // is explicit that auto-opening AND moving focus is what disorients people. The 150ms
          // hover-intent delay stops a pointer merely crossing the rail from opening it; leaving is
          // instant, because a panel that lingers over content reads as stuck.
          ? "absolute inset-y-0 left-0 h-full w-[52px] overflow-hidden px-2 " +
            // --c-rail is a translucent TINT (rgba .032 dark / .5 light). That was fine while the rail
            // sat IN the flex flow over the canvas; overlaying content it let the parts list read
            // straight through the panel. Composite the tint over an opaque canvas base in one
            // element, so the peek is opaque and still exactly the rail's colour.
            "bg-canvas [background-image:linear-gradient(var(--c-rail),var(--c-rail))] " +
            "[@media(hover:hover)]:hover:w-[190px] [@media(hover:hover)]:hover:px-3 " +
            "[@media(hover:hover)]:hover:shadow-pop [@media(hover:hover)]:hover:delay-150 " +
            "focus-within:w-[190px] focus-within:px-3 focus-within:shadow-pop"
          : "bg-rail w-[190px] px-3")
      }
    >
      {/* wordmark (north-star .wm): the rail's panel-title bar - same band + bottom hairline as every
          other docked panel header (Components list, the opened component), so the three panes read
          as one Altium workspace. Full-bleed to the rail edges via negative margins. */}
      <div
        data-dev-id="rail.wordmark"
        className={
          "-mt-4 mb-3 flex h-[34px] flex-none items-center gap-2.5 border-b border-line bg-band " +
          (collapsed ? "-mx-2 justify-center px-0" : "-mx-3 px-3.5")
        }
      >
        {/* brand category, so <Icon> does NOT auto-add .ico; the original className (with the literal
            ico token) is passed through so --icon-stroke keeps retuning it. Byte-identical output. */}
        <span className={collapsed ? PEEK_LABEL + " flex-none" : "flex-none"}>
          <Icon id="brand.wordmark" className="ico h-5 w-5 flex-none text-t1" />
        </span>
        <span
          className={
            "text-base font-semibold tracking-[-0.01em] text-t1 whitespace-nowrap " +
            (collapsed ? PEEK_LABEL : "")
          }
        >
          <Text id="nav.brand">Stockroom</Text>
        </span>
        {/* The rail's collapse control lives HERE, in its panel-title bar, because that is where a
            docked panel's own controls belong - the same place Altium puts them. It used to sit at
            the foot as 10px t3 text beside a raw mono guillemet, which made the one control that
            reshapes the workspace the faintest thing in the rail.

            COLLAPSED, this button REPLACES the wordmark rather than crowding it: 52px of rail holds
            exactly one 17px control, and the brand is already stated by the OS title bar, while the
            toggle is the only thing here anyone can act on.

            One glyph serves both directions, mirrored on the x axis, so "collapse" and "expand" can
            never drift out of sync. */}
        <button
          type="button"
          data-dev-id="rail.collapse"
          aria-label={collapsed ? "Expand Rail" : "Collapse Rail"}
          title={collapsed ? "Expand Rail" : "Collapse Rail"}
          aria-expanded={!collapsed}
          onClick={() => setCollapsed((v) => !v)}
          className={
            "flex h-[24px] w-[24px] flex-none items-center justify-center rounded-control " +
            "text-t2 transition hover:bg-[var(--c-hover)] hover:text-t1 " +
            "focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 " +
            "focus-visible:outline-acc " +
            (collapsed ? "mx-auto" : "ml-auto -mr-1")
          }
        >
          <span aria-hidden className="flex h-[17px] w-[17px] items-center justify-center">
            <Icon
              id="nav.collapse-rail"
              className={"h-full w-full" + (collapsed ? " -scale-x-100" : "")}
            />
          </span>
        </button>
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

      {/* footer (north-star .navfoot), pinned to the bottom: Settings, then a utility row -
          the Update action (when one is available) beside the light/dark theme toggle. */}
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
            "flex h-[34px] items-center gap-2.5 rounded-control text-left text-base font-medium text-t2 transition hover:bg-[var(--c-hover)] hover:text-t1 " +
            (collapsed ? "justify-center px-0 " + PEEK_ROW : "px-2.5")
          }
        >
          <span aria-hidden className="flex h-[17px] w-[17px] flex-none items-center justify-center">
            <Icon id="nav.about" className="h-full w-full" />
          </span>
          <span className={collapsed ? PEEK_LABEL + " whitespace-nowrap" : ""}>
            <Text id="nav.about">About</Text>
          </span>
        </button>
        <div
          data-dev-id="rail.utility"
          // COLLAPSED, this row must join the icon rhythm above it rather than keeping its own:
          // `mt-1.5` + `gap-1.5` + 32px children measured a 36 / 39 / 38px pitch against the nav
          // items' 36, which is the "some things are uneven there" the owner reported. Collapsed it
          // now uses the footer's own `gap-0.5` and no top margin, so every control in the rail sits
          // on ONE 36px step. Expanded keeps the tighter pill row, where the update chip and the
          // theme button genuinely are a side-by-side utility pair with labels to justify the boxes.
          className={
            "flex " +
            (collapsed ? "flex-col items-stretch gap-0.5" : "mt-1.5 items-center gap-1.5")
          }
        >
          {hasUpdate ? (
            <button
              type="button"
              data-dev-id="rail.update"
              title="A new version is available"
              aria-label={collapsed ? "Update" : undefined}
              onClick={onApplyUpdate}
              disabled={apply.isPending}
              className={
                // Collapsed: 34px and BARE, matching every other rail icon. Boxed 32px chips beside
                // bare 34px nav icons is what made the collapsed rail read as botched.
                "flex items-center gap-2.5 rounded-control text-xs font-semibold text-t1 transition hover:bg-raise2 disabled:cursor-not-allowed disabled:opacity-50 " +
                (collapsed
                  ? "h-[34px] justify-center px-0 hover:bg-[var(--c-hover)] " + PEEK_ROW
                  : "h-[32px] flex-1 border border-line bg-raise px-2.5 disabled:hover:bg-raise")
              }
            >
              <Icon id="nav.update" className="h-4 w-4 flex-none" />
              <span className={collapsed ? PEEK_LABEL + " whitespace-nowrap" : ""}>
                {apply.isPending ? (
                  <Text id="nav.update-busy">Updating...</Text>
                ) : (
                  <Text id="nav.update">Update</Text>
                )}
              </span>
            </button>
          ) : (
            <div
              data-dev-id="rail.update"
              className={
                "flex items-center gap-2.5 rounded-control text-xs font-medium text-t2 " +
                (collapsed
                  ? "h-[34px] justify-center px-0 " + PEEK_ROW
                  : "h-[32px] flex-1 border border-line bg-raise px-2.5")
              }
              title="You have the latest version"
            >
              {/* The registry stores the plain check (currentColor); the --c-ok tint was a call-site
                  inline style on the svg. Reapply it on a wrapping span so currentColor resolves to
                  the ok green exactly as before, without tinting the adjacent label. */}
              <span className="flex flex-none" style={{ color: "var(--c-ok)" }}>
                <Icon id="nav.up-to-date" className="h-4 w-4 flex-none" />
              </span>
              <span className={collapsed ? PEEK_LABEL + " whitespace-nowrap" : ""}>
                <Text id="nav.up-to-date">Up to Date!</Text>
              </span>
            </div>
          )}
          <button
            type="button"
            data-dev-id="rail.theme-toggle"
            onClick={toggle}
            aria-label="Toggle light or dark theme"
            title="Toggle light or dark theme"
            className={
              "flex flex-none items-center justify-center rounded-control text-t2 transition hover:text-t1 " +
              (collapsed
                ? "h-[34px] w-full gap-2.5 hover:bg-[var(--c-hover)] " + PEEK_ROW
                : "h-[32px] w-[32px] border border-line bg-raise hover:bg-raise2")
            }
          >
            <Icon id="nav.theme" className="h-4 w-4 flex-none" />
            {/* The peek label every other collapsed control carries. It is not decoration: without
                a second child this button had no flex GAP, so its glyph sat at the box centre
                (25.5) while every other rail glyph sat at 20.5, pulled left by the gap to its own
                zero-width label. Measured with `uishot --measure`, which now reports glyphCx.
                It also earns its place - the rail peek names every other control and named this
                one nothing. */}
            <span className={collapsed ? PEEK_LABEL + " whitespace-nowrap" : "sr-only"}>
              <Text id="nav.theme">Theme</Text>
            </span>
          </button>
        </div>
      </div>
      {aboutOpen ? <AboutModal onClose={() => setAboutOpen(false)} /> : null}
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
function AboutModal({ onClose }: { onClose: () => void }) {
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
          <span className="tnum font-mono">{__APP_VERSION__}</span>
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
        "flex h-[32px] items-center gap-2.5 rounded-control text-left text-base transition " +
        (collapsed
          ? "justify-center px-0 " + PEEK_ROW + " "
          : "px-2.5 ") +
        (selected
          ? "bg-acc-soft font-semibold text-t1 shadow-[inset_2px_0_0_var(--c-acc)]"
          : "font-medium text-t2 hover:bg-[var(--c-hover)] hover:text-t1")
      }
    >
      <span aria-hidden className="flex h-[17px] w-[17px] flex-none items-center justify-center">
        {NAV_ICONS[item.route] ?? null}
      </span>
      {/* ALWAYS rendered, so the peek has something to reveal and the accessible name is real text
          rather than an aria-label. Collapsed it is clipped to zero width by the panel's
          `overflow-hidden` and faded out; the peek gives it both back. */}
      <span
        className={
          "truncate whitespace-nowrap " + (collapsed ? PEEK_LABEL : "")
        }
      >
        <Text id={`nav.${item.route}`}>{item.title}</Text>
      </span>
    </button>
  );
}
