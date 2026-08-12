import { useMemo, useRef, useState } from "react";
import { observeElementRect, useVirtualizer } from "@tanstack/react-virtual";
import { searchIconCatalog } from "../../design-studio/fontAwesomeRegistry";
import { useCopyFormatter, useText } from "../../lib/copy";
import type { IconCatalogEntry } from "../../lib/iconRegistry";
import { sanitizeIconMarkup } from "../iconResolve";

const ROW_HEIGHT = 52;
const INITIAL_RECT = { width: 320, height: 260 };

function fittedBody(entry: IconCatalogEntry, targetViewBox: string): string {
  const values = targetViewBox.trim().split(/\s+/).map(Number);
  if (values.length !== 4 || values.some((value) => !Number.isFinite(value))) return entry.body;
  const [targetX, targetY, targetWidth, targetHeight] = values;
  const [, , sourceWidth, sourceHeight] = entry.viewBox.split(/\s+/).map(Number);
  if (![targetWidth, targetHeight, sourceWidth, sourceHeight].every((value) => value > 0)) return entry.body;
  const scale = Math.min(targetWidth / sourceWidth, targetHeight / sourceHeight);
  const x = targetX + (targetWidth - sourceWidth * scale) / 2;
  const y = targetY + (targetHeight - sourceHeight * scale) / 2;
  return `<g transform="translate(${x} ${y}) scale(${scale})" fill="currentColor" stroke="none">${entry.body}</g>`;
}

export function IconBrowser({
  onSelect,
  targetViewBox,
}: {
  onSelect: (entry: IconCatalogEntry) => void;
  targetViewBox: string;
}) {
  const [query, setQuery] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const entries = useMemo(() => searchIconCatalog(query), [query]);
  const catalogAria = useText("design-studio.icon-catalog.aria", "Offline Icon Catalog");
  const searchLabel = useText("design-studio.icon-catalog.search", "Search Icon Catalog");
  const searchPlaceholder = useText("design-studio.icon-catalog.search-placeholder", "Search labels, terms, or icon sets");
  const resultsAria = useText("design-studio.icon-catalog.results", "Icon Search Results");
  const selectAria = useCopyFormatter("design-studio.icon-catalog.select", "Select {icon}");
  const countLabel = useCopyFormatter("design-studio.icon-catalog.count", "{count} offline Font Awesome Free icons");
  const virtualizer = useVirtualizer({
    count: entries.length,
    getScrollElement: () => scrollRef.current,
    getItemKey: (index) => entries[index]?.id ?? index,
    estimateSize: () => ROW_HEIGHT,
    overscan: 8,
    initialRect: INITIAL_RECT,
    observeElementRect: (instance, callback) => observeElementRect(instance, (rect) => callback(rect.height > 0 ? rect : INITIAL_RECT)),
  });

  return (
    <section className="mt-3 border-t border-line pt-3" aria-label={catalogAria}>
      <label className="block text-xs text-t2">
        {searchLabel}
        <input
          type="search"
          aria-label={searchLabel}
          value={query}
          onChange={(event) => setQuery(event.currentTarget.value)}
          placeholder={searchPlaceholder}
          className="mt-1 w-full rounded-control border border-line bg-field px-2 py-1.5 text-2xs text-t1 outline-none focus:border-acc"
        />
      </label>
      <div ref={scrollRef} className="mt-2 max-h-64 overflow-auto rounded-control border border-line bg-field" aria-label={resultsAria}>
        <div style={{ height: `${virtualizer.getTotalSize()}px`, position: "relative" }}>
          {virtualizer.getVirtualItems().map((item) => {
            const entry = entries[item.index];
            if (!entry) return null;
            return (
              <button
                key={entry.id}
                type="button"
                aria-label={selectAria({ icon: entry.label })}
                onClick={() => onSelect({ ...entry, body: sanitizeIconMarkup(fittedBody(entry, targetViewBox)) })}
                className="absolute left-0 flex w-full items-center gap-2 px-2 text-left text-t2 hover:bg-raise2 hover:text-t1"
                style={{ height: `${item.size}px`, transform: `translateY(${item.start}px)` }}
              >
                <svg className="h-4 w-4 shrink-0" viewBox={entry.viewBox} fill="currentColor" aria-hidden="true" dangerouslySetInnerHTML={{ __html: sanitizeIconMarkup(entry.body) }} />
                <span className="min-w-0 flex-1 truncate text-2xs font-semibold">{entry.label}</span>
                <span className="text-2xs text-t3">{entry.family}</span>
              </button>
            );
          })}
        </div>
      </div>
      <p className="mt-2 text-2xs text-t3">{countLabel({ count: entries.length.toLocaleString() })}</p>
    </section>
  );
}
