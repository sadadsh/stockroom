/**
 * The left navigation rail (the mockup's .rail). Items are derived from NAV's
 * top-level destinations and navigate through the router; a folded Library tab
 * route keeps the Library entry highlighted (railRouteFor), so the rail always
 * reflects where the user is. Icons are the app's SVG set in a fixed box so
 * every item has identical sizing.
 */
import type { ComponentType } from "react";
import { railNav, railRouteFor, type NavEntry } from "../lib/nav";
import { useRouter, type Route } from "../lib/router";
import { LibraryIcon, ProjectsIcon, SettingsIcon } from "./icons";

const RAIL_ICONS: Partial<Record<Route, ComponentType<{ className?: string }>>> = {
  components: LibraryIcon,
  projects: ProjectsIcon,
  settings: SettingsIcon,
};

export function Rail() {
  const { route, navigate } = useRouter();
  const items = railNav();
  const primary = items.filter((item) => item.group === "primary");
  const foot = items.filter((item) => item.group === "foot");
  const active = railRouteFor(route);

  return (
    <nav
      aria-label="Primary"
      className="flex w-[136px] flex-none flex-col border-r border-line bg-rail"
    >
      {/* header zone: same height + hairline as the content header bar, so the top of
          the app reads as one band; the wordmark's mark left-aligns with the nav icons. */}
      <div className="flex h-14 flex-none items-center gap-2.5 border-b border-line px-[14px]">
        {/* the wordmark reads as the brand anchor: the stacked-bins mark sits in an
            accent-soft logo tile (the same pop the active nav item carries), so the top of
            the rail is the one place the accent lives at rest. */}
        <span className="flex h-7 w-7 flex-none items-center justify-center rounded-control bg-acc-soft text-acc-strong">
          <svg
            width="16"
            height="16"
            viewBox="0 0 18 18"
            fill="none"
            aria-hidden="true"
          >
            <rect x="2.5" y="2.5" width="13" height="5" rx="1.4" stroke="currentColor" strokeWidth="1.5" />
            <rect x="2.5" y="10.5" width="13" height="5" rx="1.4" stroke="currentColor" strokeWidth="1.5" />
            <circle cx="5.6" cy="5" r="0.9" fill="currentColor" />
            <circle cx="5.6" cy="13" r="0.9" fill="currentColor" />
          </svg>
        </span>
        <span className="text-[15px] font-semibold tracking-[-0.02em] text-t1">
          Stockroom
        </span>
      </div>
      <div className="flex flex-col gap-0.5 px-1.5 pt-2.5">
        {primary.map((item) => (
          <RailItem
            key={item.route}
            item={item}
            selected={active === item.route}
            onSelect={() => navigate(item.route)}
          />
        ))}
      </div>
      <div className="mt-auto flex flex-col gap-0.5 px-1.5 pb-4">
        {foot.map((item) => (
          <RailItem
            key={item.route}
            item={item}
            selected={active === item.route}
            onSelect={() => navigate(item.route)}
          />
        ))}
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
  const Icon = RAIL_ICONS[item.route];
  return (
    <button
      type="button"
      aria-current={selected ? "page" : undefined}
      onClick={onSelect}
      className={
        "flex h-8 items-center gap-2.5 rounded-control px-2 text-left text-sm transition-colors " +
        (selected
          ? "bg-acc-soft font-semibold text-acc-strong"
          : "text-t2 hover:bg-[var(--c-hover)] hover:text-t1")
      }
    >
      <span aria-hidden className="flex h-4 w-4 flex-none items-center justify-center">
        {Icon ? <Icon className="h-4 w-4" /> : null}
      </span>
      {item.title}
    </button>
  );
}
