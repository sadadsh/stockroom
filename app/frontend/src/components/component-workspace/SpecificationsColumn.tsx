/**
 * The middle column: Specifications. The dominant surface, visible immediately.
 *
 * Not behind an Overview, not behind a tab, not behind a View All, not in a modal. This is the
 * thing a person opens a component to read, so it is the thing that is on screen when the component
 * opens - every group expanded, every EXPECTED row present whether or not anybody supplied a value,
 * and a toolbar of FILTERS rather than a set of pages.
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
 */
import {
  useCallback,
  useMemo,
  useRef,
  useState,
  type MutableRefObject,
  type ReactNode,
} from "react";
import type { ComponentDossier, SpecificationRecord } from "../../api/dossierTypes";
import { useWriteSpecification, type SpecificationWrite } from "../../api/queries";
import { Text, useCopyFormatter, useText } from "../../lib/copy";
import { formatCount } from "../../lib/formatValue";
import { Button, EmptyState } from "../primitives";
import { WorkspaceColumn } from "./WorkspaceColumns";
import { SpecificationRow } from "./SpecificationRow";
import {
  countForFilter,
  filterGroups,
  sectionAnchors,
  totalSpecifications,
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

export function SpecificationsColumn({
  componentId,
  dossier,
  filter,
  onFilter,
  scrollRef,
  onViewPinout,
}: {
  componentId: string;
  dossier: ComponentDossier;
  filter: SpecFilter;
  onFilter: (filter: SpecFilter) => void;
  scrollRef: MutableRefObject<HTMLDivElement | null>;
  /** The pinout is genuinely tabular and opens on its own surface. */
  onViewPinout: () => void;
}) {
  const [query, setQuery] = useState("");
  const groups = dossier.specificationGroups;
  const keySpecifications = dossier.keySpecifications;
  const searchLabel = useText("component-browser.spec-search", "Search specifications");
  const searchPlaceholder = useText(
    "component-browser.spec-search-placeholder",
    "Search specifications…",
  );
  const filtersLabel = useText("component-browser.spec-filters", "Filter specifications");
  const keySectionLabel = useText("component-browser.key-specs-title", "Key Specifications");
  const write = useWriteSpecification(componentId);
  const total = useMemo(
    () => totalSpecifications(groups, keySpecifications),
    [groups, keySpecifications],
  );
  const filtered = useMemo(() => filterGroups(groups, filter, query), [groups, filter, query]);
  const filteredKey = useMemo(
    () => filterGroups([keyGroup(keySpecifications, keySectionLabel)], filter, query)[0]?.records ?? [],
    [keySpecifications, keySectionLabel, filter, query],
  );
  const { pinCount } = dossier.diagnostics;

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
      const scroller = scrollRef.current;
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
      if (!sourceId) return "";
      const offer = dossier.distributorOffers.find((item) => item.provider === sourceId);
      if (offer?.offerUrl) return offer.offerUrl;
      const page = dossier.identity.manufacturerPage;
      if (page.verified && page.sourceId === sourceId) return page.url;
      return "";
    },
    [dossier.distributorOffers, dossier.identity.manufacturerPage],
  );

  const runWrite = useCallback(
    (input: SpecificationWrite) => write.mutateAsync(input),
    [write],
  );

  return (
    <WorkspaceColumn
      id="specifications"
      devId="component-browser.column-specifications"
      title={<Text id="component-browser.column-specifications">Specifications</Text>}
      meta={total > 0 ? formatCount(total) : undefined}
      toolbar={
        // Above the scroller rather than sticky INSIDE it: the column has exactly one scroll
        // container and this keeps it that way, while the toolbar and the anchor strip stay on
        // screen for the whole length of the list, which is the whole point of both.
        <div className="flex flex-none flex-col gap-1 border-b border-line px-2 py-1">
          <input
            type="search"
            data-dev-id="component-browser.spec-search"
            aria-label={searchLabel}
            placeholder={searchPlaceholder}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className={
              "ui-property-value h-[22px] w-full rounded-control border border-line bg-field px-1.5 " +
              "focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-1 " +
              "focus-visible:outline-focus"
            }
          />
          <div role="group" aria-label={filtersLabel} className="flex items-center gap-1">
            {SPEC_FILTERS.map((candidate) => {
              const count =
                candidate === "all"
                  ? total
                  : countForFilter(groups, keySpecifications, candidate);
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
          </div>
          <SectionAnchorStrip anchors={anchors} onJump={scrollToSection} />
        </div>
      }
      scrollRef={(node) => {
        scrollRef.current = node;
      }}
    >
      {filteredKey.length > 0 ? (
        <SpecSection
          devId="component-browser.key-specs"
          sectionId={KEY_SECTION_ID}
          title={<Text id="component-browser.key-specs-title">Key Specifications</Text>}
          count={filteredKey.length}
        >
          {filteredKey.map((record) => (
            <SpecificationRow
              key={`key:${record.key}`}
              record={record}
              emphasise
              busy={write.isPending}
              onWrite={runWrite}
              sourceUrl={sourceUrl}
            />
          ))}
        </SpecSection>
      ) : null}

      {filtered.length === 0 && filteredKey.length === 0 ? (
        <div className="px-2 py-3">
          {total === 0 ? (
            <EmptyState dense id="component-browser.specs-empty">
              No specification has been recorded for this component yet.
            </EmptyState>
          ) : (
            <EmptyState dense id="component-browser.specs-no-match">
              No specification matches this filter.
            </EmptyState>
          )}
        </div>
      ) : (
        filtered.map(({ group, records }) => (
          <SpecSection
            key={group.id}
            devId="component-browser.spec-group"
            sectionId={group.id}
            title={group.label}
            count={records.length}
          >
            {records.map((record) => (
              <SpecificationRow
                key={record.key}
                record={record}
                busy={write.isPending}
                onWrite={runWrite}
                sourceUrl={sourceUrl}
              />
            ))}
          </SpecSection>
        ))
      )}

      {pinCount > 0 ? (
        <SpecSection
          devId="component-browser.pinout"
          sectionId="interface_pinout_table"
          title={<Text id="component-browser.pinout-section">Interface and Pinout</Text>}
          count={pinCount}
        >
          <div className="px-2 py-1">
            <Button small data-dev-id="component-browser.pinout-open" onClick={onViewPinout}>
              <Text id="component-browser.pinout-open">View Pinout</Text>
            </Button>
          </div>
        </SpecSection>
      ) : null}
    </WorkspaceColumn>
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
function SectionAnchorStrip({
  anchors,
  onJump,
}: {
  anchors: ReturnType<typeof sectionAnchors>;
  onJump: (id: string) => void;
}) {
  const stripLabel = useText("component-browser.spec-anchors", "Specification sections");
  const jumpLabel = useCopyFormatter("component-browser.spec-anchor", "Go to {section}");
  if (anchors.length < 2) return null;
  return (
    <nav
      data-dev-id="component-browser.spec-anchors"
      aria-label={stripLabel}
      className="flex flex-wrap items-center gap-x-0.5 gap-y-0.5"
    >
      {anchors.map((anchor) => (
        <button
          key={anchor.id}
          type="button"
          data-dev-id="component-browser.spec-anchor"
          data-spec-anchor={anchor.id}
          title={jumpLabel({ section: anchor.label })}
          onClick={() => onJump(anchor.id)}
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

/** The key block reuses the group filter, so it narrows by exactly the same rule as every group. */
function keyGroup(records: readonly SpecificationRecord[], label: string) {
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
      className="border-b border-line last:border-b-0"
    >
      <h3>
        <button
          type="button"
          data-dev-id="component-browser.spec-group-toggle"
          aria-expanded={open}
          onClick={() => setOpen((current) => !current)}
          className={
            "flex h-[21px] w-full items-center gap-2 bg-band px-2 text-left transition-colors " +
            "hover:bg-control-hover focus-visible:outline focus-visible:outline-2 " +
            "focus-visible:-outline-offset-2 focus-visible:outline-focus"
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
