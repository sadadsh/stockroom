/**
 * The left navigation rail (north-star .nav): a wordmark card at the top, the primary
 * destinations, and a footer pinned to the bottom that carries Settings and a single
 * utility row - the Update action (when one is available) sitting beside the light/dark
 * theme toggle. Icons are the artifact's own set, inline, so the rail matches the
 * north-star 1:1.
 */
import { useState, type ReactNode } from "react";
import { railNav, railRouteFor, type NavEntry } from "../lib/nav";
import { useRouter, type Route } from "../lib/router";
import { useTheme } from "../lib/theme";
import { useApplyUpdate, useUpdateCheck } from "../api/queries";
import { ApiError } from "../api/client";
import { useToast } from "../lib/toast";
import { Text, useText } from "../lib/copy";
import { Icon } from "./Icon";

function errMsg(err: unknown): string {
  return err instanceof ApiError ? err.message : "Something went wrong.";
}

// The primary nav destinations. Each glyph was a sizeless `.ico` svg taking its 17px box from the
// parent span; <Icon>'s primary branch would inject its default h-3.5 box, so we pass h-full w-full
// to fill the identical 17px container (appearance preserved; the parent span stays).
const NAV_ICONS: Partial<Record<Route, ReactNode>> = {
  components: <Icon id="nav.components" className="h-full w-full" />,
  projects: <Icon id="nav.projects" className="h-full w-full" />,
  settings: <Icon id="nav.settings" className="h-full w-full" />,
};

export function Rail() {
  const { route, navigate } = useRouter();
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
      className="flex w-[190px] flex-none flex-col border-r border-line bg-rail px-3 py-4"
    >
      {/* wordmark (north-star .wm): the rail's panel-title bar - same band + bottom hairline as every
          other docked panel header (Components list, the opened component), so the three panes read
          as one Altium workspace. Full-bleed to the rail edges via negative margins. */}
      <div
        data-dev-id="rail.wordmark"
        className="-mx-3 -mt-4 mb-3 flex h-[34px] flex-none items-center gap-2.5 border-b border-line bg-band px-3.5"
      >
        {/* brand category, so <Icon> does NOT auto-add .ico; the original className (with the literal
            ico token) is passed through so --icon-stroke keeps retuning it. Byte-identical output. */}
        <Icon id="brand.wordmark" className="ico h-5 w-5 flex-none text-t1" />
        <span className="text-base font-semibold tracking-[-0.01em] text-t1">
          <Text id="nav.brand">Stockroom</Text>
        </span>
      </div>

      <div data-dev-id="rail.nav" className="flex flex-col gap-0.5">
        {primary.map((item) => (
          <RailItem
            key={item.route}
            item={item}
            selected={active === item.route}
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
            onSelect={() => navigate(item.route)}
          />
        ))}
        <button
          type="button"
          data-dev-id="rail.about"
          onClick={() => setAboutOpen(true)}
          className="flex h-[34px] items-center gap-2.5 rounded-control px-2.5 text-left text-base font-medium text-t2 transition hover:bg-[var(--c-hover)] hover:text-t1"
        >
          <span aria-hidden className="flex h-[17px] w-[17px] flex-none items-center justify-center">
            <Icon id="nav.about" className="h-full w-full" />
          </span>
          <Text id="nav.about">About</Text>
        </button>
        <div data-dev-id="rail.utility" className="mt-1.5 flex items-center gap-1.5">
          {hasUpdate ? (
            <button
              type="button"
              data-dev-id="rail.update"
              title="A new version is available"
              onClick={onApplyUpdate}
              disabled={apply.isPending}
              className="flex h-[32px] flex-1 items-center gap-2 rounded-control border border-line bg-raise px-2.5 text-xs font-semibold text-t1 transition hover:bg-raise2 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-raise"
            >
              <Icon id="nav.update" className="h-4 w-4 flex-none" />
              {apply.isPending ? (
                <Text id="nav.update-busy">Updating...</Text>
              ) : (
                <Text id="nav.update">Update</Text>
              )}
            </button>
          ) : (
            <div
              data-dev-id="rail.update"
              className="flex h-[32px] flex-1 items-center gap-2 rounded-control border border-line bg-raise px-2.5 text-xs font-medium text-t2"
              title="You have the latest version"
            >
              {/* The registry stores the plain check (currentColor); the --c-ok tint was a call-site
                  inline style on the svg. Reapply it on a wrapping span so currentColor resolves to
                  the ok green exactly as before, without tinting the adjacent label. */}
              <span className="flex flex-none" style={{ color: "var(--c-ok)" }}>
                <Icon id="nav.up-to-date" className="h-4 w-4 flex-none" />
              </span>
              <Text id="nav.up-to-date">Up to Date!</Text>
            </div>
          )}
          <button
            type="button"
            data-dev-id="rail.theme-toggle"
            onClick={toggle}
            aria-label="Toggle light or dark theme"
            title="Toggle light or dark theme"
            className="flex h-[32px] w-[32px] flex-none items-center justify-center rounded-control border border-line bg-raise text-t2 transition hover:bg-raise2 hover:text-t1"
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
// same idiom as the app's other modals; Esc / a scrim click closes it.
function AboutModal({ onClose }: { onClose: () => void }) {
  const aboutLabel = useText("modal.about.aria", "About Stockroom");
  return (
    <div
      data-dev-id="about.scrim"
      className="fixed inset-0 z-[95] flex items-center justify-center bg-black/55 p-4"
      role="presentation"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={aboutLabel}
        data-dev-id="about.root"
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-[380px] rounded-card border border-line2 bg-popover p-6 text-center shadow-pop"
      >
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
  onSelect,
}: {
  item: NavEntry;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      data-dev-id={`rail.nav-${item.route}`}
      aria-current={selected ? "page" : undefined}
      onClick={onSelect}
      className={
        "flex h-[32px] items-center gap-2.5 rounded-control px-2.5 text-left text-base transition " +
        (selected
          ? "bg-acc-soft font-semibold text-t1 shadow-[inset_2px_0_0_var(--c-acc)]"
          : "font-medium text-t2 hover:bg-[var(--c-hover)] hover:text-t1")
      }
    >
      <span aria-hidden className="flex h-[17px] w-[17px] flex-none items-center justify-center">
        {NAV_ICONS[item.route] ?? null}
      </span>
      <Text id={`nav.${item.route}`}>{item.title}</Text>
    </button>
  );
}
