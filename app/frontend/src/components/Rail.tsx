/**
 * The left navigation rail (the mockup's .rail). Items are derived from NAV's
 * available destinations and navigate through the router, so the rail always
 * reflects exactly what the app can do, never an inert label. New surfaces
 * appear here automatically the moment their NAV entry is marked available.
 */
import { availableNav, type NavEntry } from "../lib/nav";
import { useRouter } from "../lib/router";

export function Rail() {
  const { route, navigate } = useRouter();
  const items = availableNav();
  const primary = items.filter((item) => item.group === "primary");
  const foot = items.filter((item) => item.group === "foot");

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
          selected={route === item.route}
          onSelect={() => navigate(item.route)}
        />
      ))}
      <div className="mt-auto pt-3">
        {foot.map((item) => (
          <RailItem
            key={item.route}
            item={item}
            selected={route === item.route}
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
  return (
    <button
      type="button"
      aria-current={selected ? "page" : undefined}
      onClick={onSelect}
      className={
        "mb-px flex items-center gap-2.5 rounded-control px-2.5 py-2 text-left text-sm transition-colors " +
        (selected
          ? "bg-raise2 text-t1"
          : "text-t3 hover:bg-[rgba(255,255,255,0.03)] hover:text-t2")
      }
    >
      <span className="w-4 text-center text-sm opacity-85">{item.glyph}</span>
      {item.title}
    </button>
  );
}
