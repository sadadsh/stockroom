/**
 * The left navigation rail (north-star .nav): a wordmark card at the top, the primary
 * destinations, and a footer that carries the one Update Available action, the theme
 * (Appearance) toggle, and a live Library / Synced readout - all wired to real state.
 * Icons are the artifact's own set, inline, so the rail matches the north-star 1:1.
 */
import type { ReactNode } from "react";
import { railNav, railRouteFor, type NavEntry } from "../lib/nav";
import { useRouter, type Route } from "../lib/router";
import { useTheme } from "../lib/theme";
import { useFacetsQuery, useSyncStatus, useUpdateCheck } from "../api/queries";

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

function syncReadout(
  data: { current_branch: string; ahead: number; behind: number } | undefined,
): string {
  if (!data) return "…";
  const drift =
    data.ahead === 0 && data.behind === 0
      ? "clean"
      : [data.ahead ? `${data.ahead} ahead` : "", data.behind ? `${data.behind} behind` : ""]
          .filter(Boolean)
          .join(", ");
  return `${data.current_branch} · ${drift}`;
}

export function Rail() {
  const { route, navigate } = useRouter();
  const { toggle } = useTheme();
  const items = railNav();
  const active = railRouteFor(route);

  const facets = useFacetsQuery();
  const sync = useSyncStatus();
  const update = useUpdateCheck();
  const total = facets.data ? facets.data.complete + facets.data.incomplete : null;

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
        {items.map((item) => (
          <RailItem
            key={item.route}
            item={item}
            selected={active === item.route}
            onSelect={() => navigate(item.route)}
          />
        ))}
      </div>

      {/* footer (north-star .navfoot): the one Update action, the Appearance toggle, and a
          live library / sync readout. */}
      <div className="mt-auto border-t border-line pt-2">
        {update.data?.update_available ? (
          <button
            type="button"
            className="mb-2 flex h-[35px] w-full items-center gap-2.5 rounded-control border border-line2 bg-raise2 px-[11px] text-xs font-semibold text-t1 shadow-card transition hover:brightness-110"
          >
            <svg {...svgProps} className="h-4 w-4 flex-none">
              <path d="M12 17V3" />
              <path d="m6 11 6 6 6-6" />
              <path d="M19 21H5" />
            </svg>
            Update Available
          </button>
        ) : null}
        <button
          type="button"
          onClick={toggle}
          aria-label="Appearance"
          className="mb-1.5 flex h-[34px] w-full items-center gap-2.5 rounded-control px-2.5 text-[13px] font-medium text-t2 transition hover:bg-[var(--c-hover)] hover:text-t1"
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
          Appearance
        </button>
        <div className="px-2.5 pb-0.5 pt-1">
          <div className="flex justify-between py-[3px] text-[11px] text-t3">
            <span>Library</span>
            <span className="tnum font-mono text-t2">
              {total == null ? "—" : `${total} parts`}
            </span>
          </div>
          <div className="flex justify-between py-[3px] text-[11px] text-t3">
            <span>Synced</span>
            <span className="tnum font-mono text-t2">{syncReadout(sync.data)}</span>
          </div>
        </div>
      </div>
    </nav>
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
