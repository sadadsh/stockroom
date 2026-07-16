/**
 * The grouped parts list (the mockup's .pk-list). Rows show the display name over
 * the part number, with an incomplete warning triangle on the right. Parts are
 * grouped by category with sticky group headers, matching library-v2.html.
 */
import { useMemo } from "react";
import type { PartSummary } from "../api/types";
import { WarnIcon } from "./icons";
import { Badge } from "./primitives";

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
    <div className="flex flex-col gap-0.5">
      {grouped.map(([category, items]) => (
        <div key={category} className="flex flex-col gap-0.5">
          <div className="sticky top-0 z-[1] mb-0.5 flex items-baseline gap-2 bg-[var(--c-sticky)] px-2.5 pb-1.5 pt-3.5 backdrop-blur">
            <span className="text-2xs font-semibold text-t3">{category}</span>
            <span className="tnum font-mono text-2xs text-t3">{items.length}</span>
          </div>
          {items.map((p) => {
            const selected = p.id === selectedId;
            return (
              <button
                key={p.id}
                type="button"
                onClick={() => onSelect(p.id)}
                aria-current={selected ? "true" : undefined}
                className={
                  // Rows separate by whitespace + a rounded selection/hover pill, not a
                  // hairline on every row (the border-on-everything tell). The selected
                  // row is the one lift; the MPN reads in the mono index face.
                  "flex w-full items-start gap-2 rounded-control px-2.5 py-2 text-left transition-colors " +
                  (selected ? "bg-raise2" : "hover:bg-[var(--c-hover)]")
                }
              >
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
                      <span className="flex-none" title="Another part shares this MPN">
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
