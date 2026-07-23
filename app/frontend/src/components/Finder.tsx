/**
 * The search + facet control at the top of the picker (the mockup's .finder).
 * The search box is wired to the API's `q` param; category facets come from
 * /api/library/facets and scope the list to a single category; the completeness
 * toggle maps to `complete_only`. A small badge shows how many filters are on.
 */
import { useState } from "react";
import type { Facets } from "../api/types";
import { SearchIcon } from "./icons";
import { Icon } from "./Icon";
import { useText } from "../lib/copy";

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
  const searchLabel = useText("components.search-placeholder", "Search Parts");

  return (
    <div data-dev-id="components.finder" className="relative">
      <div
        data-dev-id="components.search-box"
        className="flex h-[34px] items-center gap-2.5 rounded-control border border-line bg-field pl-2.5 pr-1.5 focus-within:border-acc"
      >
        <SearchIcon className="flex-none text-t3" />
        <input
          data-dev-id="components.search-input"
          value={search}
          onChange={(e) => onSearch(e.target.value)}
          onFocus={onOpenSearch ? (e) => { e.target.blur(); onOpenSearch(); } : undefined}
          onMouseDown={
            onOpenSearch
              ? (e) => { e.preventDefault(); onOpenSearch(); }
              : undefined
          }
          readOnly={!!onOpenSearch}
          placeholder={searchLabel}
          aria-label={searchLabel}
          className="min-w-0 flex-1 cursor-text bg-transparent text-sm text-t1 outline-none placeholder:text-t3"
        />
        {onOpenSearch ? (
          <kbd className="mr-0.5 flex-none rounded-control border border-line bg-raise px-1.5 py-[2px] font-mono text-2xs font-medium text-t3">
            Ctrl K
          </kbd>
        ) : null}
        <button
          type="button"
          data-dev-id="components.filter-button"
          aria-label="Filters"
          onClick={() => setOpen((v) => !v)}
          className="inline-flex items-center gap-1.5 rounded-control p-1.5 text-t3 hover:bg-raise2 hover:text-t1"
        >
          <Icon id="finder.filter" />
          {activeFilters > 0 ? (
            <span className="rounded-full bg-acc px-1.5 text-2xs font-bold leading-[14px] text-acc-on">
              {activeFilters}
            </span>
          ) : null}
        </button>
      </div>

      {open ? (
        <div
          data-dev-id="components.filter-panel"
          className="absolute inset-x-0 top-[calc(100%+6px)] z-[70] rounded-card border border-line2 bg-popover p-3 shadow-pop"
        >
          <div className="mb-2 flex items-center justify-between">
            <div className="text-2xs font-semibold text-t3">Show</div>
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
              Complete Only
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
            Category
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
                No categories yet
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
