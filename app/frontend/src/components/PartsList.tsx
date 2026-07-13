/**
 * The grouped parts list (the mockup's .pk-list). Rows show the display name over
 * the part number, with an incomplete warning triangle on the right. Parts are
 * grouped by category with sticky group headers, matching library-v2.html.
 */
import { useMemo } from "react";
import type { PartSummary } from "../api/types";
import { WarnIcon } from "./icons";

interface Props {
  parts: PartSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
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

export function PartsList({ parts, selectedId, onSelect }: Props) {
  const grouped = useMemo(() => groupByCategory(parts), [parts]);

  if (parts.length === 0) {
    return (
      <div className="px-3 py-8 text-center text-sm text-t3">No Matches</div>
    );
  }

  return (
    <div>
      {grouped.map(([category, items]) => (
        <div key={category}>
          <div className="sticky top-0 z-[1] bg-[var(--c-sticky)] px-2 pb-1.5 pt-3.5 text-2xs font-semibold text-t3 backdrop-blur">
            {category}
          </div>
          {items.map((p) => {
            const selected = p.id === selectedId;
            return (
              <button
                key={p.id}
                type="button"
                onClick={() => onSelect(p.id)}
                className={
                  "flex w-full items-start border-b border-line px-2.5 py-2.5 text-left transition-colors last:border-b-0 " +
                  (selected
                    ? "bg-raise2"
                    : "hover:bg-[var(--c-hover)]")
                }
              >
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium text-t1">
                    {p.display_name}
                  </div>
                  {p.mpn ? (
                    <div className="truncate text-2xs text-t3 mt-0.5">
                      {p.mpn}
                    </div>
                  ) : null}
                </div>
                {!p.is_complete ? (
                  <span
                    className="mt-0.5 flex flex-none items-center text-err"
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
