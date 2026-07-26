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
    <nav
      aria-label="Primary"
      data-dev-id="rail.root"
      className={
        "flex flex-none flex-col border-r border-line bg-rail py-4 transition-[width] duration-150 " +
        "motion-reduce:transition-none " +
        (collapsed ? "w-[52px] px-2" : "w-[190px] px-3")
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
        {collapsed ? null : (
          <Icon id="brand.wordmark" className="ico h-5 w-5 flex-none text-t1" />
        )}
        {collapsed ? null : (
          <span className="text-base font-semibold tracking-[-0.01em] text-t1">
            <Text id="nav.brand">Stockroom</Text>
          </span>
        )}
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
            (collapsed ? "justify-center px-0" : "px-2.5")
          }
        >
          <span aria-hidden className="flex h-[17px] w-[17px] flex-none items-center justify-center">
            <Icon id="nav.about" className="h-full w-full" />
          </span>
          {collapsed ? null : <Text id="nav.about">About</Text>}
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
                "flex items-center gap-2 rounded-control text-xs font-semibold text-t1 transition hover:bg-raise2 disabled:cursor-not-allowed disabled:opacity-50 " +
                (collapsed
                  ? "h-[34px] justify-center px-0 hover:bg-[var(--c-hover)]"
                  : "h-[32px] flex-1 border border-line bg-raise px-2.5 disabled:hover:bg-raise")
              }
            >
              <Icon id="nav.update" className="h-4 w-4 flex-none" />
              {collapsed ? null : apply.isPending ? (
                <Text id="nav.update-busy">Updating...</Text>
              ) : (
                <Text id="nav.update">Update</Text>
              )}
            </button>
          ) : (
            <div
              data-dev-id="rail.update"
              className={
                "flex items-center gap-2 rounded-control text-xs font-medium text-t2 " +
                (collapsed
                  ? "h-[34px] justify-center px-0"
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
              {collapsed ? null : <Text id="nav.up-to-date">Up to Date!</Text>}
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
                ? "h-[34px] w-full hover:bg-[var(--c-hover)]"
                : "h-[32px] w-[32px] border border-line bg-raise hover:bg-raise2")
            }
          >
            <Icon id="nav.theme" className="h-4 w-4 flex-none" />
          </button>
        </div>
      </div>
      {aboutOpen ? <AboutModal onClose={() => setAboutOpen(false)} /> : null}
    </nav>
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
      aria-label={collapsed ? item.title : undefined}
      title={collapsed ? item.title : undefined}
      onClick={onSelect}
      className={
        "flex h-[32px] items-center gap-2.5 rounded-control text-left text-base transition " +
        (collapsed ? "justify-center px-0 " : "px-2.5 ") +
        (selected
          ? "bg-acc-soft font-semibold text-t1 shadow-[inset_2px_0_0_var(--c-acc)]"
          : "font-medium text-t2 hover:bg-[var(--c-hover)] hover:text-t1")
      }
    >
      <span aria-hidden className="flex h-[17px] w-[17px] flex-none items-center justify-center">
        {NAV_ICONS[item.route] ?? null}
      </span>
      {collapsed ? null : <Text id={`nav.${item.route}`}>{item.title}</Text>}
    </button>
  );
}
