/**
 * The grouped parts list (the mockup's .pk-list). Rows show the display name over
 * the part number, with an incomplete warning triangle on the right. Parts are
 * grouped by category with sticky group headers, matching library-v2.html.
 */
import { useMemo } from "react";
import type { PartSummary } from "../api/types";
import { WarnIcon } from "./icons";
import { Icon } from "./Icon";
import { Badge } from "./primitives";

// The row icon: a 30px tile carrying the part's category glyph. It deliberately does NOT render
// the 3D model (the owner's call): a 30px 3D render of a chip/passive is a muddy grey blob that
// tells you nothing the row text does not, and each one is a real GPU pass. The category glyph
// (capacitor / resistor / IC / ...) reads instantly and identifies the part's KIND at a glance.
// The full 3D model lives in the detail hero, where it is big enough to matter.
export function RowThumbnail({ category }: { category: string }) {
  return (
    <span
      data-dev-id="components.row-thumbnail"
      className="flex h-[30px] w-[30px] flex-none items-center justify-center overflow-hidden rounded-control border border-line bg-field text-t2"
    >
      <CategoryGlyph category={category} />
    </span>
  );
}

// A small monochrome category glyph for the row thumbnail (north-star .rthumb): the part seen
// as its kind at a glance. Neutral stroke art, so it inherits the row's text color and never
// carries a hue. Falls back to a generic chip for a category with no dedicated glyph.
function CategoryGlyph({ category }: { category: string }) {
  const c = category.toLowerCase();
  // The thumbnail geometry (viewBox 32x18, weight 1.6, round caps) now lives in the registry entry;
  // the branch only picks the id + forwards the same className, so each glyph is identical + editable.
  const cls = "h-3.5 w-6 text-t2";
  if (c.includes("resistor")) return <Icon id="glyph.resistor" className={cls} />;
  if (c.includes("capacitor")) return <Icon id="glyph.capacitor" className={cls} />;
  if (c.includes("inductor") || c.includes("ferrite")) return <Icon id="glyph.inductor" className={cls} />;
  if (c.includes("diode") || c.includes("led")) return <Icon id="glyph.diode" className={cls} />;
  if (c.includes("connector") || c.includes("header")) return <Icon id="glyph.connector" className={cls} />;
  if (c.includes("crystal") || c.includes("oscillator")) return <Icon id="glyph.crystal" className={cls} />;
  // ICs, modules, sensors, and anything else: a chip with pins
  return <Icon id="glyph.ic" className={cls} />;
}

interface Props {
  parts: PartSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  // Part ids that share an MPN with another part (a real accidental duplicate);
  // each gets a Duplicate badge. Shared footprints are normal and never badged.
  duplicateIds?: Set<string>;
}

function groupByCategory(parts: PartSummary[]): Array<[string, PartSummary[]]> {
  const groups = new Map<string, PartSummary[]>();
  for (const p of parts) {
    const key = p.category || "Uncategorized";
    const bucket = groups.get(key);
    if (bucket) bucket.push(p);
    else groups.set(key, [p]);
  }
  return [...groups.entries()].sort((a, b) => a[0].localeCompare(b[0]));
}

export function PartsList({ parts, selectedId, onSelect, duplicateIds }: Props) {
  const grouped = useMemo(() => groupByCategory(parts), [parts]);

  if (parts.length === 0) {
    return (
      <div className="px-3 py-8 text-center text-sm text-t3">No Matches</div>
    );
  }

  return (
    <div data-dev-id="components.list" className="flex flex-col gap-0.5">
      {grouped.map(([category, items]) => (
        <div key={category} className="flex flex-col gap-0.5">
          <div
            data-dev-id="components.category-header"
            className="sticky top-0 z-[1] mb-0.5 flex items-baseline gap-2 bg-[var(--c-sticky)] px-2.5 pb-1.5 pt-3.5 backdrop-blur"
          >
            <span className="text-xs font-semibold text-t2">{category}</span>
            <span className="tnum font-mono text-2xs text-t3">{items.length}</span>
          </div>
          {items.map((p) => {
            const selected = p.id === selectedId;
            return (
              <button
                key={p.id}
                type="button"
                data-dev-id="components.row"
                onClick={() => onSelect(p.id)}
                aria-current={selected ? "true" : undefined}
                className={
                  // Rows separate by whitespace + a rounded selection/hover pill, not a
                  // hairline on every row (the border-on-everything tell). The selected
                  // row is the one lift; the MPN reads in the mono index face.
                  "flex w-full items-center gap-2.5 rounded-control px-2.5 py-2 text-left transition-colors " +
                  (selected
                    ? "bg-acc-soft shadow-[inset_2px_0_0_var(--c-acc)]"
                    : "hover:bg-[var(--c-hover)]")
                }
              >
                <RowThumbnail category={p.category} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span
                      className={
                        "truncate text-sm " +
                        (selected ? "font-semibold text-t1" : "font-medium text-t1")
                      }
                    >
                      {p.display_name}
                    </span>
                    {duplicateIds?.has(p.id) ? (
                      <span
                        data-dev-id="components.row-duplicate"
                        className="flex-none"
                        title="Another part shares this MPN"
                      >
                        <Badge tone="warn" size="sm">
                          Duplicate
                        </Badge>
                      </span>
                    ) : null}
                  </div>
                  {p.mpn ? (
                    <div className="tnum mt-0.5 truncate font-mono text-2xs text-t3">
                      {p.mpn}
                    </div>
                  ) : null}
                </div>
                {!p.is_complete ? (
                  <span
                    data-dev-id="components.row-warn"
                    className="mt-0.5 flex flex-none items-center text-warn"
                    title={`Incomplete: missing ${p.missing.join(", ")}`}
                  >
                    <WarnIcon className="h-3.5 w-3.5" />
                  </span>
                ) : null}
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );
}
