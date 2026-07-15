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
      className="flex w-[118px] flex-none flex-col border-r border-line bg-rail px-2.5 py-4"
    >
      <div className="mx-1.5 mb-5 mt-0.5 text-xs font-bold text-t1">Stockroom</div>
      {primary.map((item) => (
        <RailItem
          key={item.route}
          item={item}
          selected={active === item.route}
          onSelect={() => navigate(item.route)}
        />
      ))}
      <div className="mt-auto pt-3">
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
        "mb-px flex h-8 items-center gap-2.5 rounded-control px-2.5 text-left text-sm transition-colors " +
        (selected
          ? "bg-raise2 text-t1"
          : "text-t3 hover:bg-[var(--c-hover)] hover:text-t2")
      }
    >
      <span aria-hidden className="flex h-4 w-4 flex-none items-center justify-center">
        {Icon ? <Icon className="h-4 w-4" /> : null}
      </span>
      {item.title}
    </button>
  );
}
