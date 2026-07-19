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
import { useUpdateCheck } from "../api/queries";

const svgProps = {
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

const NAV_ICONS: Partial<Record<Route, ReactNode>> = {
  components: (
    <svg {...svgProps}>
      <path d="M12 20v2" />
      <path d="M12 2v2" />
      <path d="M17 20v2" />
      <path d="M17 2v2" />
      <path d="M2 12h2" />
      <path d="M2 17h2" />
      <path d="M2 7h2" />
      <path d="M20 12h2" />
      <path d="M20 17h2" />
      <path d="M20 7h2" />
      <path d="M7 20v2" />
      <path d="M7 2v2" />
      <rect x="4" y="4" width="16" height="16" rx="2" />
      <rect x="8" y="8" width="8" height="8" rx="1" />
    </svg>
  ),
  projects: (
    <svg {...svgProps}>
      <rect width="18" height="18" x="3" y="3" rx="2" />
      <path d="M11 9h4a2 2 0 0 0 2-2V3" />
      <circle cx="9" cy="9" r="2" />
      <path d="M7 21v-4a2 2 0 0 1 2-2h4" />
      <circle cx="15" cy="15" r="2" />
    </svg>
  ),
  settings: (
    <svg {...svgProps}>
      <path d="M9.671 4.136a2.34 2.34 0 0 1 4.659 0 2.34 2.34 0 0 0 3.319 1.915 2.34 2.34 0 0 1 2.33 4.033 2.34 2.34 0 0 0 0 3.831 2.34 2.34 0 0 1-2.33 4.033 2.34 2.34 0 0 0-3.319 1.915 2.34 2.34 0 0 1-4.659 0 2.34 2.34 0 0 0-3.32-1.915 2.34 2.34 0 0 1-2.33-4.033 2.34 2.34 0 0 0 0-3.831A2.34 2.34 0 0 1 6.35 6.051a2.34 2.34 0 0 0 3.319-1.915" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  ),
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

  return (
    <nav
      aria-label="Primary"
      className="flex w-[190px] flex-none flex-col border-r border-line bg-rail px-3 py-4"
    >
      {/* wordmark card (north-star .wm): the stockroom, in miniature, set in a raised tile */}
      <div className="mb-3.5 flex items-center gap-2.5 rounded-control bg-raise2 px-[11px] py-[9px] shadow-card">
        <svg {...svgProps} className="h-5 w-5 flex-none text-t1">
          <path d="M11 21.73a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73z" />
          <path d="M12 22V12" />
          <polyline points="3.29 7 12 12 20.71 7" />
          <path d="m7.5 4.27 9 5.15" />
        </svg>
        <span className="text-[15px] font-semibold tracking-[-0.02em] text-t1">Stockroom</span>
      </div>

      <div className="flex flex-col gap-0.5">
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
      <div className="mt-auto flex flex-col gap-0.5 border-t border-line pt-2">
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
          onClick={() => setAboutOpen(true)}
          className="flex h-[34px] items-center gap-2.5 rounded-control px-2.5 text-left text-[13.5px] font-medium text-t2 transition hover:bg-[var(--c-hover)] hover:text-t1"
        >
          <span aria-hidden className="flex h-[17px] w-[17px] flex-none items-center justify-center">
            <svg {...svgProps}>
              <circle cx="12" cy="12" r="10" />
              <path d="M12 16v-4M12 8h.01" />
            </svg>
          </span>
          About
        </button>
        <div className="mt-1.5 flex items-center gap-1.5">
          {hasUpdate ? (
            <button
              type="button"
              title="A new version is available"
              className="flex h-[34px] flex-1 items-center gap-2 rounded-control border border-line2 bg-raise2 px-2.5 text-xs font-semibold text-t1 shadow-card transition hover:brightness-110"
            >
              <svg {...svgProps} className="h-4 w-4 flex-none">
                <path d="M12 17V3" />
                <path d="m6 11 6 6 6-6" />
                <path d="M19 21H5" />
              </svg>
              Update
            </button>
          ) : (
            <div
              className="flex h-[34px] flex-1 items-center gap-2 rounded-control border border-line bg-raise px-2.5 text-xs font-medium text-t2"
              title="You have the latest version"
            >
              <svg {...svgProps} className="h-4 w-4 flex-none" style={{ color: "var(--c-ok)" }}>
                <path d="M20 6 9 17l-5-5" />
              </svg>
              Up to Date!
            </div>
          )}
          <button
            type="button"
            onClick={toggle}
            aria-label="Toggle light or dark theme"
            title="Toggle light or dark theme"
            className="flex h-[34px] w-[34px] flex-none items-center justify-center rounded-control border border-line2 bg-raise2 text-t2 shadow-card transition hover:brightness-110 hover:text-t1"
          >
            <svg {...svgProps} className="h-4 w-4 flex-none">
              <circle cx="12" cy="12" r="4" />
              <path d="M12 2v2" />
              <path d="M12 20v2" />
              <path d="m4.93 4.93 1.41 1.41" />
              <path d="m17.66 17.66 1.41 1.41" />
              <path d="M2 12h2" />
              <path d="M20 12h2" />
              <path d="m6.34 17.66-1.41 1.41" />
              <path d="m19.07 4.93-1.41 1.41" />
            </svg>
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
  return (
    <div
      className="fixed inset-0 z-[95] flex items-center justify-center bg-black/55 p-4 backdrop-blur-sm"
      role="presentation"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="About Stockroom"
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-[380px] rounded-card border border-line2 bg-popover p-6 text-center shadow-pop"
      >
        <div className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-control bg-raise2 shadow-card">
          <svg {...svgProps} className="h-6 w-6 text-t1">
            <path d="M11 21.73a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73z" />
            <path d="M12 22V12" />
            <polyline points="3.29 7 12 12 20.71 7" />
            <path d="m7.5 4.27 9 5.15" />
          </svg>
        </div>
        <div className="text-lg font-semibold tracking-[-0.02em] text-t1">Stockroom</div>
        <p className="mt-1 text-sm text-t2">
          Developed with love by <span className="font-medium text-t1">Sadad Haidari</span>.
        </p>
        <div className="mt-4 flex justify-center gap-2.5">
          <a
            href="https://www.linkedin.com/in/sadadhaidari"
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-2 rounded-control border border-line2 bg-raise2 px-3 py-2 text-xs font-semibold text-t2 shadow-card transition hover:text-t1 hover:brightness-110"
          >
            <svg viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
              <path d="M20.45 20.45h-3.56v-5.57c0-1.33-.02-3.04-1.85-3.04-1.85 0-2.14 1.45-2.14 2.94v5.67H9.35V9h3.42v1.56h.05c.48-.9 1.64-1.85 3.37-1.85 3.6 0 4.27 2.37 4.27 5.46v6.28zM5.34 7.43a2.06 2.06 0 1 1 0-4.13 2.06 2.06 0 0 1 0 4.13zM7.12 20.45H3.55V9h3.57v11.45zM22.22 0H1.77C.79 0 0 .77 0 1.73v20.54C0 23.22.79 24 1.77 24h20.45c.98 0 1.78-.78 1.78-1.73V1.73C24 .77 23.2 0 22.22 0z" />
            </svg>
            LinkedIn
          </a>
          <a
            href="https://github.com/sadadsh"
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-2 rounded-control border border-line2 bg-raise2 px-3 py-2 text-xs font-semibold text-t2 shadow-card transition hover:text-t1 hover:brightness-110"
          >
            <svg viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
              <path d="M12 .5C5.37.5 0 5.87 0 12.5c0 5.3 3.44 9.8 8.21 11.39.6.11.82-.26.82-.58l-.02-2.05c-3.34.73-4.04-1.61-4.04-1.61-.55-1.39-1.33-1.76-1.33-1.76-1.09-.74.08-.73.08-.73 1.2.09 1.84 1.24 1.84 1.24 1.07 1.83 2.8 1.3 3.49.99.11-.78.42-1.3.76-1.6-2.67-.3-5.47-1.34-5.47-5.96 0-1.32.47-2.39 1.24-3.23-.13-.31-.54-1.53.12-3.18 0 0 1.01-.32 3.3 1.23a11.5 11.5 0 0 1 6.01 0c2.29-1.55 3.3-1.23 3.3-1.23.66 1.65.25 2.87.12 3.18.77.84 1.24 1.91 1.24 3.23 0 4.63-2.8 5.65-5.48 5.95.43.37.81 1.1.81 2.22l-.01 3.29c0 .32.21.7.82.58A12.01 12.01 0 0 0 24 12.5C24 5.87 18.63.5 12 .5z" />
            </svg>
            GitHub
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
      aria-current={selected ? "page" : undefined}
      onClick={onSelect}
      className={
        "flex h-[34px] items-center gap-2.5 rounded-control px-2.5 text-left text-[13.5px] transition " +
        (selected
          ? "bg-raise2 font-semibold text-t1 shadow-card"
          : "font-medium text-t2 hover:bg-[var(--c-hover)] hover:text-t1")
      }
    >
      <span aria-hidden className="flex h-[17px] w-[17px] flex-none items-center justify-center">
        {NAV_ICONS[item.route] ?? null}
      </span>
      {item.title}
    </button>
  );
}
