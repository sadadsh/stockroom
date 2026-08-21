/**
 * The middle column: Specifications. Usable values are visible immediately.
 *
 * Not behind an Overview, tab, or modal. Missing values and per-row source drawers stay quiet until
 * the header's Details control is used; ordinary sourced rows and their filters stay in place.
 *
 * The search box and the four filters NARROW this list. Neither of them navigates, replaces the
 * column or opens a second surface: the rows that answer stay exactly where they were, in the
 * groups they belong to, so a person who searched for "voltage" can still see which heading each
 * answer came from.
 *
 * Nothing here decides what a specification means. The groups arrive grouped by the category's own
 * schema, the key block arrives already chosen, and each row arrives carrying its own applicability,
 * importance and verification state. A column that re-derived any of those would be a second answer
 * to a question the projection has already answered - and the two would disagree the first time a
 * category schema changed.
 *
 * THE COLUMN IS SEVEN PLACEMENTS NOW (plan Phase 1) and `SpecificationsColumnChrome` is what holds
 * them together. Two pieces of state decide what all seven draw, and neither of them moved:
 *
 *   THE FILTER is still lifted to `ComponentWorkspace`, because the identity header's quality
 *   summary and the Manage menu both set it from outside this column.
 *
 *   THE SEARCH TEXT is still owned here, because nothing outside the column has ever set it. It
 *   lives on the CHROME rather than on the search box, for the same reason it used to live on the
 *   column rather than on the input: the filtered result decides what four other pieces draw, and a
 *   second component recomputing it would be a second answer.
 *
 * The four conditions the document names for this column - is there a key block, is there a group,
 * are there two headings to jump between, is there a pinout - are all answered from that one
 * derivation, and the groups the document REPEATS over are the ones that survived it. The document
 * names the collection (`dossier.specificationGroups`); which of its members are on screen right
 * now is a runtime answer, exactly like a visibility condition.
 */
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { SpecificationGroup, SpecificationRecord } from "../../api/dossierTypes";
import { useWriteSpecification, type SpecificationWrite } from "../../api/queries";
import { Text, useCopyFormatter, useText } from "../../lib/copy";
import { formatCount } from "../../lib/formatValue";
import {
  LayoutRuntimeScope,
  type LayoutRepeatItem,
  type PiecePartProps,
  type RegionChromeProps,
} from "../../layout/LayoutRenderer";
import { WORKSPACE_CONDITION } from "../../layout/defaultWorkspaceLayout";
import { useWorkspaceRender } from "../../layout/workspaceRenderContext";
import { Button, EmptyState } from "../primitives";
import { SpecificationRow } from "./SpecificationRow";
import {
  WorkspaceColumnFrame,
  WorkspaceColumnScroller,
  WorkspaceColumnTitleStrip,
} from "./WorkspaceColumns";
import {
  countForFilter,
  filterGroups,
  sectionAnchors,
  totalSpecifications,
  isEmptyState,
  KEY_SECTION_ID,
  SPEC_FILTERS,
  type SpecFilter,
} from "./specificationRows";

const FILTER_COPY: Record<SpecFilter, { id: string; label: string }> = {
  all: { id: "component-browser.spec-filter-all", label: "All" },
  missing: { id: "component-browser.spec-filter-missing", label: "Missing" },
  conflicts: { id: "component-browser.spec-filter-conflicts", label: "Conflicts" },
  unverified: { id: "component-browser.spec-filter-unverified", label: "Unverified" },
};

/** The collection id the document repeats the groups over. Stated once, read by both sides. */
export const SPECIFICATION_GROUPS_COLLECTION = "dossier.specificationGroups";

/**
 * One group the current filter left on screen.
 *
 * Read off `filterGroups`'s own return type rather than restated, so the piece and the filter
 * cannot disagree about what a surviving group is.
 */
type FilteredGroup = ReturnType<typeof filterGroups>[number];

/** Everything the column derives once, and every one of its seven pieces reads. */
interface SpecificationsColumnState {
  query: string;
  setQuery: (value: string) => void;
  total: number;
  filtered: readonly FilteredGroup[];
  filteredKey: readonly SpecificationRecord[];
  anchors: ReturnType<typeof sectionAnchors>;
  scrollToSection: (sectionId: string) => void;
  sourceUrl: (sourceId: string) => string;
  runWrite: (input: SpecificationWrite) => Promise<unknown>;
  writing: boolean;
  showDetails: boolean;
}

const SpecificationsColumnContext = createContext<SpecificationsColumnState | null>(null);

function useColumn(): SpecificationsColumnState | null {
  return useContext(SpecificationsColumnContext);
}

/**
 * The column's frame, its one derivation, and the answers to its own conditions.
 *
 * The search text lives here so that the filtered result exists ONCE. Everything downstream - the
 * counts in the filter row, the anchor strip, the key block, the groups the document repeats over,
 * and the empty state - reads it rather than re-filtering.
 */
export function SpecificationsColumnChrome({ children }: RegionChromeProps) {
  const workspace = useWorkspaceRender();
  const [query, setQuery] = useState("");
  const componentId = workspace?.componentId ?? "";
  const write = useWriteSpecification(componentId);
  const keySectionLabel = useText("component-browser.key-specs-title", "Main Specifications");
  const dossier = workspace?.dossier;
  const filter = workspace?.specifications.filter ?? "all";
  const scrollRef = workspace?.specifications.scrollRef;
  const showDetails = workspace?.specifications.showDetails ?? true;

  const groups = useMemo(() => dossier?.specificationGroups ?? [], [dossier]);
  const keySpecifications = useMemo(() => dossier?.keySpecifications ?? [], [dossier]);
  const visibleGroups = useMemo(
    () =>
      showDetails
        ? groups
        : groups.map((group) => ({
            ...group,
            specifications: group.specifications.filter(
              (record) => !isEmptyState(record.verificationState),
            ),
          })),
    [groups, showDetails],
  );
  const visibleKeySpecifications = useMemo(
    () =>
      showDetails
        ? keySpecifications
        : keySpecifications.filter((record) => !isEmptyState(record.verificationState)),
    [keySpecifications, showDetails],
  );
  const total = useMemo(
    () => totalSpecifications(groups, keySpecifications),
    [groups, keySpecifications],
  );
  const filtered = useMemo(
    () => filterGroups(visibleGroups, filter, query),
    [visibleGroups, filter, query],
  );
  const filteredKey = useMemo(
    () =>
      filterGroups([keyGroup(visibleKeySpecifications, keySectionLabel)], filter, query)[0]?.records ?? [],
    [visibleKeySpecifications, keySectionLabel, filter, query],
  );

  // The headings that are ON SCREEN right now, which is what the strip may offer. A link to a
  // group the current filter emptied would scroll to nothing.
  const anchors = useMemo(
    () =>
      sectionAnchors(
        filtered.map((entry) => entry.group),
        filteredKey,
        keySectionLabel,
      ),
    [filtered, filteredKey, keySectionLabel],
  );

  /**
   * Bring one heading to the top of the column's OWN scroller.
   *
   * Not `scrollIntoView`, which walks up to the nearest scrollable ancestor and can move a
   * surface the person did not ask to move. The column owns one scroll container and this scrolls
   * exactly that one, so the header, the other two columns and the page all stay where they are.
   */
  const scrollToSection = useCallback(
    (sectionId: string) => {
      const scroller = scrollRef?.current;
      const section = scroller?.querySelector<HTMLElement>(
        `[data-spec-section="${CSS.escape(sectionId)}"]`,
      );
      if (!scroller || !section) return;
      scroller.scrollTop += section.getBoundingClientRect().top -
        scroller.getBoundingClientRect().top;
    },
    [scrollRef],
  );

  /**
   * Where a named source can be looked at.
   *
   * A distributor's own listing for THIS part, or the manufacturer's own page when it has been
   * verified as such. Anything else has no destination and produces no control, because a
   * `View Source` that opens nothing is a dead click path.
   */
  const sourceUrl = useCallback(
    (sourceId: string): string => {
      if (!sourceId || !dossier) return "";
      const offer = dossier.distributorOffers.find((item) => item.provider === sourceId);
      if (offer?.offerUrl) return offer.offerUrl;
      const page = dossier.identity.manufacturerPage;
      if (page.verified && page.sourceId === sourceId) return page.url;
      return "";
    },
    [dossier],
  );

  const runWrite = useCallback(
    (input: SpecificationWrite) => write.mutateAsync(input),
    [write],
  );

  const state = useMemo<SpecificationsColumnState>(
    () => ({
      query,
      setQuery,
      total,
      filtered,
      filteredKey,
      anchors,
      scrollToSection,
      sourceUrl,
      runWrite,
      writing: write.isPending,
      showDetails,
    }),
    [
      anchors,
      filtered,
      filteredKey,
      query,
      runWrite,
      scrollToSection,
      sourceUrl,
      total,
      write.isPending,
      showDetails,
    ],
  );

  const conditions = useMemo(
    () => ({
      [WORKSPACE_CONDITION.specificationsKeyBlock]: filteredKey.length > 0,
      [WORKSPACE_CONDITION.specificationsGroup]: filtered.length > 0,
      [WORKSPACE_CONDITION.specificationsAnchors]: anchors.length >= 2,
      [WORKSPACE_CONDITION.specificationsEmpty]:
        filtered.length === 0 && filteredKey.length === 0,
      [WORKSPACE_CONDITION.specificationsPinout]: (dossier?.diagnostics.pinCount ?? 0) > 0,
    }),
    [anchors, dossier, filtered, filteredKey],
  );

  const collections = useMemo(
    () => ({
      // The document names the collection; the runtime says which of its members survived the
      // filter and the search. Same relationship a visibility condition has to its placement.
      [SPECIFICATION_GROUPS_COLLECTION]: filtered.map<LayoutRepeatItem>((entry) => ({
        key: entry.group.id,
        value: entry,
      })),
    }),
    [filtered],
  );

  if (!workspace) return null;
  return (
    <WorkspaceColumnFrame id="specifications" devId="component-browser.column-specifications">
      <SpecificationsColumnContext.Provider value={state}>
        <LayoutRuntimeScope conditions={conditions} collections={collections}>
          {children}
        </LayoutRuntimeScope>
      </SpecificationsColumnContext.Provider>
    </WorkspaceColumnFrame>
  );
}

export function SpecificationsTitleStripPart() {
  const column = useColumn();
  if (!column) return null;
  return (
    <WorkspaceColumnTitleStrip
      title={<Text id="component-browser.column-specifications">Specifications</Text>}
      meta={column.total > 0 ? formatCount(column.total) : undefined}
    />
  );
}

/**
 * The toolbar band.
 *
 * Above the scroller rather than sticky INSIDE it: the column has exactly one scroll container and
 * this keeps it that way, while the toolbar and the anchor strip stay on screen for the whole
 * length of the list, which is the whole point of both.
 */
export function SpecificationsToolbarChrome({ children }: RegionChromeProps) {
  return <div className="flex flex-none flex-col gap-1 bg-band/35 px-2 py-1.5">{children}</div>;
}

export function SpecificationsSearchPart() {
  const column = useColumn();
  const searchLabel = useText("component-browser.spec-search", "Search specifications");
  const searchPlaceholder = useText(
    "component-browser.spec-search-placeholder",
    "Search specifications…",
  );
  if (!column) return null;
  return (
    <input
      type="search"
      data-dev-id="component-browser.spec-search"
      aria-label={searchLabel}
      placeholder={searchPlaceholder}
      value={column.query}
      onChange={(event) => column.setQuery(event.target.value)}
      className={
        "ui-property-value h-[22px] w-full rounded-control border border-line bg-field px-1.5 " +
        "focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-1 " +
        "focus-visible:outline-focus"
      }
    />
  );
}

export function SpecificationsFiltersPart() {
  const workspace = useWorkspaceRender();
  const column = useColumn();
  const filtersLabel = useText("component-browser.spec-filters", "Filter specifications");
  if (!workspace || !column) return null;
  const { filter, onFilter } = workspace.specifications;
  const { specificationGroups, keySpecifications, qualitySummary } = workspace.dossier;
  const expectedGaps = qualitySummary.completeness.missingExpected.length;
  const recommendedGaps = qualitySummary.completeness.missingRecommended.length;
  const gaps = [
    expectedGaps > 0
      ? `${formatCount(expectedGaps)} expected ${expectedGaps === 1 ? "gap" : "gaps"}`
      : "",
    recommendedGaps > 0
      ? `${formatCount(recommendedGaps)} recommended ${recommendedGaps === 1 ? "gap" : "gaps"}`
      : "",
  ].filter(Boolean).join(" · ");
  return (
    <div role="group" aria-label={filtersLabel} className="flex flex-wrap items-center gap-1">
      {SPEC_FILTERS.map((candidate) => {
        const count =
          candidate === "all"
            ? column.total
            : countForFilter(specificationGroups, keySpecifications, candidate);
        return (
          <button
            key={candidate}
            type="button"
            data-dev-id="component-browser.spec-filter"
            data-spec-filter={candidate}
            aria-pressed={filter === candidate}
            onClick={() => onFilter(candidate)}
            className={
              "ui-control-label flex h-[20px] items-center gap-1 rounded-control border px-1.5 " +
              "transition-colors focus-visible:outline focus-visible:outline-2 " +
              "focus-visible:outline-offset-1 focus-visible:outline-focus " +
              (filter === candidate
                ? "border-line-dark bg-control-pressed text-t1"
                : "border-transparent bg-transparent text-t2 hover:bg-control-hover hover:text-t1")
            }
          >
            <Text id={FILTER_COPY[candidate].id}>{FILTER_COPY[candidate].label}</Text>
            {count > 0 ? (
              <span className="ui-component-metadata">{formatCount(count)}</span>
            ) : null}
          </button>
        );
      })}
      {gaps ? (
        <span
          data-dev-id="component-browser.spec-gaps"
          className="ui-component-metadata ml-auto"
        >
          {gaps}
        </span>
      ) : null}
    </div>
  );
}

/**
 * The headings this part has, as a jump strip.
 *
 * The list is whatever the dossier sent for THIS category and nothing else: a resistor has no
 * Timing group and a connector has no Memory group, so a fixed strip would offer links to headings
 * that are not on the screen. It wraps rather than scrolling sideways - a second scrollbar inside a
 * column that already owns one is a surface nobody can predict the behaviour of.
 */
export function SpecificationsAnchorsPart() {
  const column = useColumn();
  const stripLabel = useText("component-browser.spec-anchors", "Specification sections");
  const jumpLabel = useCopyFormatter("component-browser.spec-anchor", "Go to {section}");
  if (!column) return null;
  return (
    <nav
      data-dev-id="component-browser.spec-anchors"
      aria-label={stripLabel}
      className="flex flex-wrap items-center gap-x-0.5 gap-y-0.5"
    >
      {column.anchors.map((anchor) => (
        <button
          key={anchor.id}
          type="button"
          data-dev-id="component-browser.spec-anchor"
          data-spec-anchor={anchor.id}
          title={jumpLabel({ section: anchor.label })}
          onClick={() => column.scrollToSection(anchor.id)}
          className={
            "ui-component-metadata flex h-[18px] items-center rounded-control px-1.5 " +
            "transition-colors hover:bg-control-hover hover:text-t1 focus-visible:outline " +
            "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-focus"
          }
        >
          {anchor.label}
        </button>
      ))}
    </nav>
  );
}

/** The column's one scroller. */
export function SpecificationsBodyChrome({ children }: RegionChromeProps) {
  const workspace = useWorkspaceRender();
  if (!workspace) return null;
  return (
    <WorkspaceColumnScroller
      id="specifications"
      scrollRef={(node) => {
        workspace.specifications.scrollRef.current = node;
      }}
    >
      {children}
    </WorkspaceColumnScroller>
  );
}

/**
 * The key block.
 *
 * A distinct piece from a specification group: it is promoted out of the groups by the category
 * schema, it is emphasised, and it anchors under its own `KEY_SECTION_ID` rather than under a group
 * id the dossier sent.
 */
export function SpecificationsKeyBlockPart() {
  const column = useColumn();
  if (!column) return null;
  return (
    <SpecSection
      devId="component-browser.key-specs"
      sectionId={KEY_SECTION_ID}
      title={<Text id="component-browser.key-specs-title">Main Specifications</Text>}
      count={column.filteredKey.length}
    >
      {column.filteredKey.map((record) => (
        <SpecificationRow
          key={`key:${record.key}`}
          record={record}
          emphasise
          busy={column.writing}
          onWrite={column.runWrite}
          sourceUrl={column.sourceUrl}
          showDetails={column.showDetails}
        />
      ))}
    </SpecSection>
  );
}

/** One specification group, once per member of the collection the document repeats over. */
export function SpecificationsGroupPart({ item }: PiecePartProps) {
  const column = useColumn();
  const entry = item as FilteredGroup | undefined;
  if (!column || !entry) return null;
  return (
    <SpecSection
      devId="component-browser.spec-group"
      sectionId={entry.group.id}
      title={entry.group.label}
      count={entry.records.length}
    >
      {entry.records.map((record) => (
        <SpecificationRow
          key={record.key}
          record={record}
          busy={column.writing}
          onWrite={column.runWrite}
          sourceUrl={column.sourceUrl}
          showDetails={column.showDetails}
        />
      ))}
    </SpecSection>
  );
}

/**
 * What the column says when the filter left nothing.
 *
 * Two different sentences, because they are two different facts: a component nobody has specified
 * at all is not the same as a filter that matched none of the twelve rows that are there.
 */
export function SpecificationsEmptyPart() {
  const column = useColumn();
  if (!column) return null;
  return (
    <div className="px-2 py-3">
      {column.total === 0 ? (
        <EmptyState dense id="component-browser.specs-empty">
          No specification has been recorded for this component so far.
        </EmptyState>
      ) : (
        <EmptyState dense id="component-browser.specs-no-match">
          No specification matches this filter.
        </EmptyState>
      )}
    </div>
  );
}

/** The pinout section: a heading, a count, and the one control that opens the tabular surface. */
export function SpecificationsPinoutPart() {
  const workspace = useWorkspaceRender();
  if (!workspace) return null;
  return (
    <SpecSection
      devId="component-browser.pinout"
      sectionId="interface_pinout_table"
      title={<Text id="component-browser.pinout-section">Interface and Pinout</Text>}
      count={workspace.dossier.diagnostics.pinCount}
    >
      <div className="px-2 py-1">
        <Button
          small
          data-dev-id="component-browser.pinout-open"
          onClick={workspace.specifications.onViewPinout}
        >
          <Text id="component-browser.pinout-open">View Pinout</Text>
        </Button>
      </div>
    </SpecSection>
  );
}

/** The key block reuses the group filter, so it narrows by exactly the same rule as every group. */
function keyGroup(records: readonly SpecificationRecord[], label: string): SpecificationGroup {
  return {
    id: KEY_SECTION_ID,
    label,
    specifications: [...records],
    count: records.length,
  };
}

/**
 * One group of rows: a compact heading band directly above a contiguous property table.
 *
 * Collapsible, but never collapsed by default. Someone who opens a component wants the numbers,
 * not a list of the names of the numbers.
 */
function SpecSection({
  devId,
  sectionId,
  title,
  count,
  children,
}: {
  devId: string;
  /** What the anchor strip scrolls to. */
  sectionId: string;
  title: ReactNode;
  count: number;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(true);
  const headingRef = useRef<HTMLElement | null>(null);
  return (
    <section
      ref={headingRef}
      data-dev-id={devId}
      data-spec-section={sectionId}
      className="pb-1 last:pb-0"
    >
      <h3>
        <button
          type="button"
          data-dev-id="component-browser.spec-group-toggle"
          aria-expanded={open}
          onClick={() => setOpen((current) => !current)}
          className={
            // Type weight, height and the breathing room after each group carry the hierarchy.
            // Repeating a rule and a filled band for every family recreated the wall of lines the
            // compact property rows deliberately removed.
            "flex h-[24px] w-full items-center gap-2 px-2 text-left " +
            "transition-colors hover:bg-[var(--c-hover)] focus-visible:outline " +
            "focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus"
          }
        >
          {/* Wraps rather than truncating: a heading is the only name its rows have. */}
          <span className="ui-section-title min-w-0 break-words">{title}</span>
          <span className="ui-component-metadata ml-auto flex-none">{formatCount(count)}</span>
        </button>
      </h3>
      {open ? <div>{children}</div> : null}
    </section>
  );
}
