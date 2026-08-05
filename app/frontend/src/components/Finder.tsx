/**
 * The picker's search and filters.
 *
 * The search box is a REAL inline input. It used to be a button that opened the full-screen
 * parametric search, which meant the picker had no way to narrow itself: typing three characters
 * of a part number - the commonest thing anyone does in a library - took over the whole window.
 * It is wired to the API's `q`, which matches MPN, manufacturer, description, category, package
 * and the derived key specification values.
 *
 * The parametric search is a SEPARATE control beside it, and stays separate. The two answer
 * different questions ("which of these is it" versus "which parts meet these constraints") and
 * merging them is what produced a text box that was not one.
 *
 * The filters are compact and, when any are on, say so in words underneath: a bare count badge
 * told a person that something was hidden without telling them what.
 */
import { useState } from "react";
import type { Facets } from "../api/types";
import { SearchIcon } from "./icons";
import { Icon } from "./Icon";
import { Text, useText, useCopyFormatter } from "../lib/copy";

interface Props {
  search: string;
  onSearch: (value: string) => void;
  facets: Facets | undefined;
  category: string | null;
  onCategory: (category: string | null) => void;
  completeOnly: boolean;
  onCompleteOnly: (value: boolean) => void;
  duplicatesOnly: boolean;
  onDuplicatesOnly: (value: boolean) => void;
  duplicateCount: number;
  // When set, the search field is a trigger for the full-screen parametric search (the
  // north-star search): focusing/clicking it opens the overlay rather than editing inline.
  onOpenSearch?: () => void;
}

export function Finder({
  search,
  onSearch,
  facets,
  category,
  onCategory,
  completeOnly,
  onCompleteOnly,
  duplicatesOnly,
  onDuplicatesOnly,
  duplicateCount,
  onOpenSearch,
}: Props) {
  const [open, setOpen] = useState(false);
  const activeFilters =
    (category ? 1 : 0) + (completeOnly ? 1 : 0) + (duplicatesOnly ? 1 : 0);
  const categories = facets
    ? Object.entries(facets.by_category).sort((a, b) => a[0].localeCompare(b[0]))
    : [];
  // Copy for an attribute (placeholder + label), so it is reworded through the same override
  // as any <Text> label when dev mode saves it.
  const searchLabel = useText("components.search-placeholder", "Search Components");
  const filtersLabel = useText("components.filter-button-label", "Filters");
  const advancedLabel = useText("components.advanced-search-label", "Advanced Search");
  const clearLabel = useText("components.clear-filters", "Clear Filters");
  const summary = useCopyFormatter("components.filter-summary", "Showing: {filters}");
  const completeText = useText("components.filter-complete-label", "Complete Only");
  const duplicatesText = useText("components.filter-duplicates-label", "Duplicates");
  const activeSummary = [
    category ?? null,
    completeOnly ? completeText : null,
    duplicatesOnly ? duplicatesText : null,
  ].filter(Boolean) as string[];

  return (
    <div data-dev-id="components.finder" className="relative">
      <div className="flex items-center gap-1.5">
        <div
          data-dev-id="components.search-box"
          className="flex h-[24px] min-w-0 flex-1 items-center gap-2 rounded-control border border-line bg-field pl-2 pr-1.5 focus-within:border-line2"
        >
          <SearchIcon className="flex-none text-t3" />
          <input
            data-dev-id="components.search-input"
            value={search}
            onChange={(e) => onSearch(e.target.value)}
            placeholder={searchLabel}
            aria-label={searchLabel}
            className="ui-control-label min-w-0 flex-1 cursor-text bg-transparent text-t1 outline-none placeholder:text-t3"
          />
        </div>
        {onOpenSearch ? (
          <button
            type="button"
            data-dev-id="components.advanced-search"
            aria-label={advancedLabel}
            title={advancedLabel}
            onClick={onOpenSearch}
            className="ui-control-label inline-flex h-[24px] flex-none items-center gap-1.5 rounded-control border border-line bg-raise px-2 text-t2 transition-colors hover:bg-raise2 hover:text-t1"
          >
            <Text id="components.advanced-search-label">Advanced Search</Text>
          </button>
        ) : null}
        <button
          type="button"
          data-dev-id="components.filter-button"
          aria-label={filtersLabel}
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
          className="inline-flex h-[24px] flex-none items-center gap-1.5 rounded-control border border-line bg-raise px-2 text-t3 transition-colors hover:bg-raise2 hover:text-t1"
        >
          <Icon id="finder.filter" />
          {activeFilters > 0 ? (
            <span className="ui-status-text tabular-nums text-t1">{activeFilters}</span>
          ) : null}
        </button>
      </div>

      {/* What is currently hidden, in words. A count alone said something was filtered without
          saying what, which is the state people get stuck in. */}
      {activeSummary.length > 0 ? (
        <p
          data-dev-id="components.filter-summary"
          className="ui-row-metadata mt-1 flex min-w-0 items-baseline gap-2"
        >
          <span className="min-w-0 flex-1 truncate">
            {summary({ filters: activeSummary.join(" · ") })}
          </span>
          <button
            type="button"
            onClick={() => {
              onCategory(null);
              onCompleteOnly(false);
              onDuplicatesOnly(false);
            }}
            className="ui-control-label flex-none text-t2 transition-colors hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus"
          >
            {clearLabel}
          </button>
        </p>
      ) : null}

      {open ? (
        <div
          data-dev-id="components.filter-panel"
          className="absolute inset-x-0 top-[calc(100%+6px)] z-[70] rounded-card border border-line2 bg-popover p-3 shadow-pop"
        >
          <div className="mb-2 flex items-center justify-between">
            <div className="text-2xs font-semibold text-t3">
              <Text id="components.filter-show">Show</Text>
            </div>
            <label
              data-dev-id="components.filter-complete"
              className="flex cursor-pointer select-none items-center gap-2 text-sm text-t1"
            >
              <span
                className={
                  "flex h-[17px] w-[17px] flex-none items-center justify-center rounded-control border-[1.5px] text-xs " +
                  (completeOnly
                    ? "border-acc bg-acc text-acc-on"
                    : "border-line2 text-transparent")
                }
              >
                {"✓"}
              </span>
              <input
                type="checkbox"
                className="sr-only"
                checked={completeOnly}
                onChange={(e) => onCompleteOnly(e.target.checked)}
              />
              <Text id="components.filter-complete-label">Complete Only</Text>
            </label>
          </div>

          {duplicateCount > 0 ? (
            <div className="mb-2 flex items-center justify-end">
              <label
                data-dev-id="components.filter-duplicates"
                className="flex cursor-pointer select-none items-center gap-2 text-sm text-t1"
              >
                <span
                  className={
                    "flex h-[17px] w-[17px] flex-none items-center justify-center rounded-control border-[1.5px] text-xs " +
                    (duplicatesOnly
                      ? "border-acc bg-acc text-acc-on"
                      : "border-line2 text-transparent")
                  }
                >
                  {"✓"}
                </span>
                <input
                  type="checkbox"
                  className="sr-only"
                  checked={duplicatesOnly}
                  onChange={(e) => onDuplicatesOnly(e.target.checked)}
                />
                Duplicates ({duplicateCount})
              </label>
            </div>
          ) : null}

          <div className="mb-2 mt-3 text-2xs font-semibold text-t3">
            <Text id="components.filter-category">Category</Text>
          </div>
          <div data-dev-id="components.filter-categories" className="max-h-64 overflow-y-auto">
            <FacetRow
              label="All Categories"
              count={facets ? facets.complete + facets.incomplete : 0}
              active={category === null}
              onClick={() => onCategory(null)}
            />
            {categories.map(([name, count]) => (
              <FacetRow
                key={name}
                label={name}
                count={count}
                active={category === name}
                onClick={() => onCategory(name)}
              />
            ))}
            {categories.length === 0 ? (
              <div className="px-1.5 py-2 text-xs text-t3">
                <Text id="components.filter-no-categories">No categories so far</Text>
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function FacetRow({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        "flex w-full items-center gap-2.5 rounded-control px-1.5 py-1.5 text-left text-sm " +
        (active ? "bg-raise text-t1" : "text-t2 hover:bg-raise")
      }
    >
      <span
        className={
          "flex h-[15px] w-[15px] flex-none items-center justify-center rounded-full border-[1.5px] " +
          (active ? "border-acc" : "border-line2")
        }
      >
        {active ? (
          <span className="h-[7px] w-[7px] rounded-full bg-acc" />
        ) : null}
      </span>
      <span className="min-w-0 flex-1 truncate">{label}</span>
      <span className="tnum flex-none text-2xs text-t3">{count}</span>
    </button>
  );
}
