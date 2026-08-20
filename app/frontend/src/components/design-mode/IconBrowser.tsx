import { useEffect, useMemo, useState } from "react";
import {
  DEFAULT_OFFLINE_ICON_FAMILY,
  loadOfflineIconCollections,
  offlineIconFamilies,
  searchOfflineIcons,
  type OfflineIconFamily,
} from "../../design-studio/offlineIconRegistry";
import { useCopyFormatter, useText } from "../../lib/copy";
import type { IconCatalogEntry } from "../../lib/iconRegistry";
import { sanitizeIconMarkup } from "../iconResolve";

const ICON_RESULT_PAGE_SIZE = 200;

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
  autoFocus = false,
}: {
  onSelect: (entry: IconCatalogEntry) => void;
  targetViewBox: string;
  autoFocus?: boolean;
}) {
  const [query, setQuery] = useState("");
  const [family, setFamily] = useState<OfflineIconFamily>(DEFAULT_OFFLINE_ICON_FAMILY);
  const [visibleLimit, setVisibleLimit] = useState(ICON_RESULT_PAGE_SIZE);
  const [familyEntries, setFamilyEntries] = useState<readonly IconCatalogEntry[]>([]);
  const entries = useMemo(() => searchOfflineIcons(query, family, familyEntries), [familyEntries, family, query]);
  const visibleEntries = entries.slice(0, visibleLimit);
  const families = useMemo(() => offlineIconFamilies(), []);
  useEffect(() => {
    let active = true;
    setFamilyEntries([]);
    void loadOfflineIconCollections(family).then((loaded) => { if (active) setFamilyEntries(loaded); });
    return () => { active = false; };
  }, [family]);
  useEffect(() => setVisibleLimit(ICON_RESULT_PAGE_SIZE), [family, query]);
  const catalogAria = useText("design-studio.icon-catalog.aria", "Offline Icon Catalog");
  const searchLabel = useText("design-studio.icon-catalog.search", "Search Icon Catalog");
  const searchPlaceholder = useText("design-studio.icon-catalog.search-placeholder", "Search labels, terms, or icon sets");
  const resultsAria = useText("design-studio.icon-catalog.results", "Icon Search Results");
  const selectAria = useCopyFormatter("design-studio.icon-catalog.select", "Select {icon} from {family}");
  const countLabel = useCopyFormatter("design-studio.icon-catalog.count", "{count} offline icons");
  const progressLabel = useCopyFormatter("design-studio.icon-catalog.progress", "{shown} of {count} icons shown");
  const showMoreLabel = useText("design-studio.icon-catalog.show-more", "Show More Icons");
  const libraryLabel = useText("design-studio.icon-catalog.library", "Icon Catalog");
  return (
    <section className="mt-3 pt-3" aria-label={catalogAria}>
      <div className="grid grid-cols-[1fr_9rem] gap-2">
      <label className="block text-xs text-t2">
        <span className="sr-only">{searchLabel}</span>
        <input
          type="search"
          autoFocus={autoFocus}
          aria-label={searchLabel}
          value={query}
          onChange={(event) => setQuery(event.currentTarget.value)}
          placeholder={searchPlaceholder}
          className="w-full rounded-control bg-field px-2 py-1.5 text-2xs text-t1 outline-none focus:ring-1 focus:ring-focus"
        />
      </label>
      <select aria-label={libraryLabel} value={family} onChange={(event) => setFamily(event.currentTarget.value as OfflineIconFamily)} className="rounded-control bg-field px-2 text-2xs text-t1">
        {families.map((item) => <option key={item} value={item}>{item}</option>)}
      </select>
      </div>
      <div className="mt-2 max-h-[60vh] overflow-auto rounded-control bg-field p-2" aria-label={resultsAria}>
        <div className="grid grid-cols-4 gap-1 sm:grid-cols-6 lg:grid-cols-8">
          {visibleEntries.map((entry) => (
              <button
                key={entry.id}
                type="button"
                aria-label={selectAria({ icon: entry.label, family: entry.family })}
                onClick={() => onSelect({ ...entry, body: sanitizeIconMarkup(fittedBody(entry, targetViewBox)) })}
                className="flex min-h-20 min-w-0 flex-col items-center justify-center gap-2 rounded-control p-2 text-center text-t2 hover:bg-raise2 hover:text-t1"
              >
                <svg className="h-7 w-7 shrink-0" viewBox={entry.viewBox} fill="currentColor" aria-hidden="true" dangerouslySetInnerHTML={{ __html: sanitizeIconMarkup(entry.body) }} />
                <span className="w-full truncate text-2xs font-semibold">{entry.label}</span>
                <span className="w-full truncate text-2xs text-t3">{entry.family}</span>
              </button>
          ))}
        </div>
        {visibleEntries.length < entries.length ? (
          <button
            type="button"
            onClick={() => setVisibleLimit((current) => Math.min(entries.length, current + ICON_RESULT_PAGE_SIZE))}
            className="mt-2 w-full rounded-control bg-raise2 px-3 py-2 text-xs font-semibold text-t1 hover:bg-control-hover"
          >
            {showMoreLabel}
          </button>
        ) : null}
      </div>
      <p className="mt-2 text-2xs text-t3">
        {progressLabel({ shown: visibleEntries.length.toLocaleString(), count: entries.length.toLocaleString() })}
        {" · "}{countLabel({ count: entries.length.toLocaleString() })}
      </p>
    </section>
  );
}
