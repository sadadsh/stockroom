/**
 * The EXHAUSTIVE specification sheet: every group, every fact, every source, every alternate.
 *
 * The compact Specifications tab is a summary and must stay one - it lives inside a viewport that
 * never scrolls, so it shows counts and a couple of representative facts per group. This is where
 * the rest actually is, and it is complete on purpose: a person who came here to check one number
 * against a datasheet needs the number, who said it, and what the other sources said instead. A
 * value shown with no attribution is a value they have to go and verify somewhere else.
 *
 * Search and sort exist because "complete" is only useful if it is navigable. Pins are the SAME
 * pins the Overview's Key Specifications block reads (`lib/keySpecs` + `lib/pinnedSpecs`), so
 * pinning here changes what that block shows - two pin stores that could disagree would be worse
 * than no pinning at all.
 */
import { useMemo, useState, type ReactNode } from "react";
import type {
  ComponentFact,
  ComponentSpecificationsView,
  SpecificationGroupView,
} from "../../api/workspaceTypes";
import { Text, useText } from "../../lib/copy";
import { isPinned, type PinnedSpecs } from "../../lib/keySpecs";
import { Badge } from "../primitives";
import { SheetEmpty, SheetSection, SheetTable, SourceNote } from "./SheetParts";

/** How the sheet orders facts. `group` is the projection's own order, which groups by meaning. */
export type SpecSort = "group" | "name" | "source";

/** An `<option>` cannot hold an element, so its copy resolves through `useText`, not `<Text>`. */
function useSortOptions(): ReadonlyArray<{ id: SpecSort; label: string }> {
  return [
    { id: "group", label: useText("component-browser.spec-sort-group", "By Group") },
    { id: "name", label: useText("component-browser.spec-sort-name", "By Name") },
    { id: "source", label: useText("component-browser.spec-sort-source", "By Source") },
  ];
}

/** The value as it reads on a row: the formatted value plus its unit, or an honest blank. */
export function factText(fact: ComponentFact): string {
  const value = fact.formattedValue.trim();
  if (!value) return "";
  return fact.unit ? `${value} ${fact.unit}` : value;
}

/** Does this fact match what was typed? Label, value and source are all searchable. */
export function factMatches(fact: ComponentFact, needle: string): boolean {
  if (!needle) return true;
  const hay = [fact.label, fact.formattedValue, fact.source?.label ?? "", fact.id]
    .join(" ")
    .toLowerCase();
  return hay.includes(needle.toLowerCase());
}

/**
 * The groups a query and a sort produce.
 *
 * Sorting by name or by source deliberately DISSOLVES the groups into one list: keeping the group
 * headings while reordering inside them would answer neither question ("where is the fact called
 * X", "what did Mouser actually tell us"), and would leave a person scanning five short lists.
 */
export function sheetGroups(
  specifications: ComponentSpecificationsView,
  query: string,
  sort: SpecSort,
  allLabel: string,
): SpecificationGroupView[] {
  const needle = query.trim();
  const groups = specifications.groups
    .map((group) => ({
      ...group,
      facts: group.facts.filter((fact) => factMatches(fact, needle)),
    }))
    .filter((group) => group.facts.length > 0)
    .map((group) => ({ ...group, count: group.facts.length }));

  if (sort === "group") return groups;

  const flat = groups.flatMap((group) => group.facts);
  const sorted = [...flat].sort((a, b) =>
    sort === "name"
      ? a.label.localeCompare(b.label)
      : (a.source?.label ?? "").localeCompare(b.source?.label ?? "") ||
        a.label.localeCompare(b.label),
  );
  return sorted.length === 0
    ? []
    : [{ id: "all", label: allLabel, facts: sorted, count: sorted.length }];
}

export function SpecificationsSheet({
  specifications,
  category,
  pinned,
  onTogglePin,
  pinout,
}: {
  specifications: ComponentSpecificationsView;
  category: string;
  pinned: PinnedSpecs;
  onTogglePin: (specKey: string) => void;
  /** The pinout table's own actions, so the sheet does not have to know how a write happens. */
  pinout: ReactNode;
}) {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SpecSort>("group");
  const sortOptions = useSortOptions();
  const searchLabel = useText("component-browser.spec-search", "Search specifications");
  const sortLabel = useText("component-browser.spec-sort", "Sort specifications");
  const allLabel = useText("component-browser.spec-all-group", "All Specifications");

  const groups = useMemo(
    () => sheetGroups(specifications, query, sort, allLabel),
    [specifications, query, sort, allLabel],
  );
  const pinnedFacts = useMemo(
    () =>
      specifications.groups
        .flatMap((group) => group.facts)
        .filter((fact) => isPinned(pinned, category, fact.id)),
    [specifications, pinned, category],
  );

  return (
    <div data-dev-id="component-browser.spec-sheet" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <input
          data-dev-id="component-browser.spec-search"
          type="search"
          value={query}
          aria-label={searchLabel}
          placeholder={searchLabel}
          onChange={(event) => setQuery(event.target.value)}
          className="h-7 min-w-0 flex-1 rounded-control border border-line bg-field px-2 text-xs text-t1 outline-none focus:border-acc"
        />
        <select
          data-dev-id="component-browser.spec-sort"
          aria-label={sortLabel}
          value={sort}
          onChange={(event) => setSort(event.target.value as SpecSort)}
          className="h-7 flex-none rounded-control border border-line bg-field px-1.5 text-xs text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc"
        >
          {sortOptions.map((option) => (
            <option key={option.id} value={option.id}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      {pinnedFacts.length > 0 ? (
        <SheetSection
          title="Pinned"
          copyId="component-browser.spec-pinned-title"
          count={pinnedFacts.length}
        >
          <FactTable
            facts={pinnedFacts}
            category={category}
            pinned={pinned}
            onTogglePin={onTogglePin}
          />
        </SheetSection>
      ) : null}

      {groups.length === 0 ? (
        <SheetEmpty id="component-browser.specifications-empty">
          No specifications on record.
        </SheetEmpty>
      ) : (
        groups.map((group) => (
          <SheetSection
            key={group.id}
            devId="component-browser.spec-group"
            /* The group label is projected DATA (`stockroom.workspace.SPEC_GROUPS`), so it does
               not pass through the copy layer - see SheetSection's note on `copyId`. */
            title={`${group.label} (${group.count})`}
          >
            <FactTable
              facts={group.facts}
              category={category}
              pinned={pinned}
              onTogglePin={onTogglePin}
            />
          </SheetSection>
        ))
      )}

      {pinout}
    </div>
  );
}

/** Every fact, its value, who said it, and every other answer that was offered for it. */
function FactTable({
  facts,
  category,
  pinned,
  onTogglePin,
}: {
  facts: ComponentFact[];
  category: string;
  pinned: PinnedSpecs;
  onTogglePin: (specKey: string) => void;
}) {
  const tableLabel = useText("component-browser.spec-table", "Specifications");
  const emptyValue = useText("component-browser.no-value", "None");
  const pinLabel = useText("component-browser.spec-pin", "Pin");
  const unpinLabel = useText("component-browser.spec-pinned", "Pinned");
  return (
    <SheetTable
      label={tableLabel}
      headings={[
        <Text key="s" id="component-browser.spec-col-name">
          Specification
        </Text>,
        <Text key="v" id="component-browser.spec-col-value">
          Value
        </Text>,
        <Text key="o" id="component-browser.spec-col-source">
          Source
        </Text>,
        <Text key="p" id="component-browser.spec-col-pin">
          Pin
        </Text>,
      ]}
    >
      {facts.map((fact) => {
        const isOn = isPinned(pinned, category, fact.id);
        return (
          <tr
            key={`${fact.id}:${fact.label}`}
            data-dev-id="component-browser.spec-row"
            className="border-b border-line/60 align-top last:border-b-0"
          >
            <td className="px-3 py-1.5 text-t2">{fact.label}</td>
            <td className="px-3 py-1.5">
              <span className="tnum font-mono text-t1">{factText(fact) || emptyValue}</span>
              {fact.state === "conflict" ? (
                <Badge size="sm" tone="warn" className="ml-2">
                  <Text id="component-browser.spec-conflict">Sources Disagree</Text>
                </Badge>
              ) : null}
              {fact.alternates.length > 0 ? (
                <ul className="mt-1 flex flex-col gap-0.5">
                  {fact.alternates.map((alternate) => (
                    <li
                      key={`${alternate.sourceId}:${alternate.formattedValue}`}
                      data-dev-id="component-browser.spec-alternate"
                      className="flex items-baseline gap-2 text-2xs text-t3"
                    >
                      <span className="tnum font-mono">
                        {alternate.formattedValue || emptyValue}
                      </span>
                      <span>{alternate.sourceLabel || alternate.sourceId}</span>
                    </li>
                  ))}
                </ul>
              ) : null}
            </td>
            <td className="px-3 py-1.5">
              <SourceNote source={fact.source} />
            </td>
            <td className="px-3 py-1.5">
              <button
                type="button"
                data-dev-id="component-browser.spec-row-pin"
                aria-pressed={isOn}
                aria-label={`${isOn ? unpinLabel : pinLabel} ${fact.label}`}
                onClick={() => onTogglePin(fact.id)}
                className="rounded-control px-1 text-2xs text-t3 transition-colors hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc"
              >
                {isOn ? unpinLabel : pinLabel}
              </button>
            </td>
          </tr>
        );
      })}
    </SheetTable>
  );
}

/** The pinout columns, in the order the record wrote them, unioned across every pin. */
export function pinoutColumns(pinout: Array<Record<string, unknown>>): string[] {
  const columns: string[] = [];
  for (const entry of pinout) {
    for (const key of Object.keys(entry)) {
      if (!columns.includes(key)) columns.push(key);
    }
  }
  return columns;
}

/** The complete pinout, one row per pin. Never truncated: this is the exhaustive surface. */
export function PinoutTable({
  pinout,
  action,
}: {
  pinout: Array<Record<string, unknown>>;
  action?: ReactNode;
}) {
  const tableLabel = useText("component-browser.pinout-table", "Pinout");
  const columns = pinoutColumns(pinout);
  return (
    <SheetSection
      title="Pinout"
      copyId="component-browser.pinout-title"
      count={pinout.length}
      action={action}
    >
      {pinout.length === 0 ? (
        <SheetEmpty id="component-browser.pinout-empty">No pinout on record.</SheetEmpty>
      ) : (
        <SheetTable
          devId="component-browser.pinout-table"
          label={tableLabel}
          headings={columns.map((column) => column.replace(/_/g, " "))}
        >
          {pinout.map((entry, index) => (
            <tr key={index} className="border-b border-line/60 last:border-b-0">
              {columns.map((column) => (
                <td key={column} className="tnum whitespace-nowrap px-3 py-1 font-mono">
                  {formatPin(entry[column])}
                </td>
              ))}
            </tr>
          ))}
        </SheetTable>
      )}
    </SheetSection>
  );
}

function formatPin(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return "";
  return String(value);
}
