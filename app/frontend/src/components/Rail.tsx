/**
 * The left navigation rail (the mockup's .rail). Only Components is wired in this
 * first slice; the other destinations render as inert labels so the frame reads
 * complete without pretending they work.
 */

interface NavItem {
  glyph: string;
  label: string;
}

const PRIMARY: NavItem[] = [
  { glyph: "▤", label: "Components" },
  { glyph: "▧", label: "Projects" },
  { glyph: "▥", label: "Bench" },
  { glyph: "⎇", label: "Git" },
];

const FOOT: NavItem[] = [
  { glyph: "◍", label: "Activity" },
  { glyph: "☾", label: "Theme" },
  { glyph: "⚙", label: "Settings" },
];

export function Rail() {
  return (
    <div className="flex w-[118px] flex-none flex-col border-r border-line bg-rail px-2.5 py-4">
      <div className="mx-1.5 mb-5 mt-0.5 text-xs font-bold text-t1">
        NETDECK
      </div>
      {PRIMARY.map((item) => (
        <RailItem key={item.label} item={item} selected={item.label === "Components"} />
      ))}
      <div className="mt-auto pt-3">
        {FOOT.map((item) => (
          <RailItem key={item.label} item={item} selected={false} />
        ))}
      </div>
    </div>
  );
}

function RailItem({ item, selected }: { item: NavItem; selected: boolean }) {
  return (
    <div
      className={
        "mb-px flex cursor-default items-center gap-2.5 rounded-control px-2.5 py-2 text-sm transition-colors " +
        (selected
          ? "bg-raise2 text-t1"
          : "text-t3 hover:bg-[rgba(255,255,255,0.03)] hover:text-t2")
      }
    >
      <span className="w-4 text-center text-sm opacity-85">{item.glyph}</span>
      {item.label}
    </div>
  );
}
