/**
 * The grouped parts list: the picker.
 *
 * A row is three lines and one primary item. The MPN leads and owns its whole line, because a
 * picker row exists to be recognised by the identifier a person looks the part up by; the
 * manufacturer and package qualify it on the second line, and the description - with the
 * attention state right-aligned against it - is the third. Parts are grouped by category under
 * sticky headers.
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
} from "react";
import {
  defaultRangeExtractor,
  observeElementRect,
  type Range,
  useVirtualizer,
} from "@tanstack/react-virtual";
import type { PartSummary } from "../api/types";
import { WarnIcon } from "./icons";
import { Icon } from "./Icon";
import { Text, useText } from "../lib/copy";
import { Badge } from "./primitives";
import { partAttention } from "./partAttention";

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
  /** The picker viewport. Large libraries virtualize against this exact scroll owner. */
  scrollElement: HTMLDivElement | null;
  // Part ids that share an MPN with another part (a real accidental duplicate);
  // each gets a Duplicate badge. Shared footprints are normal and never badged.
  duplicateIds?: Set<string>;
}

type GroupedParts = Array<[string, PartSummary[]]>;
type ListItem =
  | { kind: "category"; key: string; category: string; count: number }
  | { kind: "part"; key: string; part: PartSummary };

// Below this boundary a normal DOM is cheaper and more accessible than a virtual one. Above it,
// DOM cost must follow viewport size rather than library size. The value is a count boundary, not
// a timing claim; the 1,000-row contract is locked by a rendered-node budget in PartsList.test.
export const PARTS_LIST_VIRTUALIZATION_THRESHOLD = 100;
const PART_ROW_HEIGHT = 46;
const CATEGORY_ROW_HEIGHT = 30;
const VIRTUAL_OVERSCAN = 8;
const INITIAL_VIEWPORT = { width: 320, height: 640 };

function groupByCategory(parts: PartSummary[]): GroupedParts {
  const groups = new Map<string, PartSummary[]>();
  for (const p of parts) {
    const key = p.category || "Uncategorized";
    const bucket = groups.get(key);
    if (bucket) bucket.push(p);
    else groups.set(key, [p]);
  }
  return [...groups.entries()].sort((a, b) => a[0].localeCompare(b[0]));
}

function flattenGroups(grouped: GroupedParts): ListItem[] {
  return grouped.flatMap(([category, parts]) => [
    {
      kind: "category" as const,
      key: `category:${category}`,
      category,
      count: parts.length,
    },
    ...parts.map((part) => ({
      kind: "part" as const,
      key: `part:${part.id}`,
      part,
    })),
  ]);
}

export function PartsList({
  parts,
  selectedId,
  onSelect,
  scrollElement,
  duplicateIds,
}: Props) {
  const grouped = useMemo(() => groupByCategory(parts), [parts]);
  const items = useMemo(() => flattenGroups(grouped), [grouped]);
  const virtualized = parts.length > PARTS_LIST_VIRTUALIZATION_THRESHOLD;
  const stickyIndexes = useMemo(
    () =>
      items.flatMap((item, index) =>
        item.kind === "category" ? [index] : [],
      ),
    [items],
  );
  const activeStickyIndex = useRef(stickyIndexes[0] ?? 0);
  const rangeExtractor = useCallback(
    (range: Range) => {
      activeStickyIndex.current =
        [...stickyIndexes]
          .reverse()
          .find((index) => range.startIndex >= index) ??
        stickyIndexes[0] ??
        0;
      return [
        ...new Set([
          activeStickyIndex.current,
          ...defaultRangeExtractor(range),
        ]),
      ].sort((a, b) => a - b);
    },
    [stickyIndexes],
  );
  const estimateSize = useCallback(
    (index: number) =>
      items[index]?.kind === "category"
        ? CATEGORY_ROW_HEIGHT
        : PART_ROW_HEIGHT,
    [items],
  );
  const getItemKey = useCallback(
    (index: number) => items[index]?.key ?? index,
    [items],
  );
  const virtualizer = useVirtualizer({
    count: items.length,
    enabled: virtualized,
    getScrollElement: () => scrollElement,
    getItemKey,
    estimateSize,
    overscan: VIRTUAL_OVERSCAN,
    rangeExtractor,
    initialRect: INITIAL_VIEWPORT,
    // jsdom and a temporarily collapsed picker report a zero rect. Keeping the conservative
    // initial viewport avoids both a blank first paint and the old "render all as fallback"
    // failure mode. A real non-zero browser measurement takes over immediately.
    observeElementRect: (instance, callback) =>
      observeElementRect(instance, (rect) =>
        callback(rect.height > 0 ? rect : INITIAL_VIEWPORT),
      ),
  });
  const selectedIndex = useMemo(
    () =>
      selectedId
        ? items.findIndex(
            (item) => item.kind === "part" && item.part.id === selectedId,
          )
        : -1,
    [items, selectedId],
  );
  const partItems = useMemo(
    () =>
      items.flatMap((item, itemIndex) =>
        item.kind === "part" ? [{ part: item.part, itemIndex }] : [],
      ),
    [items],
  );
  const selectedPartIndex = useMemo(
    () =>
      selectedId
        ? partItems.findIndex(({ part }) => part.id === selectedId)
        : -1,
    [partItems, selectedId],
  );
  const tabbableId =
    selectedPartIndex >= 0 ? selectedId : (partItems[0]?.part.id ?? null);
  const pendingFocusId = useRef<string | null>(null);
  const navigate = useCallback(
    (event: React.KeyboardEvent<HTMLButtonElement>, currentId: string) => {
      const currentIndex = partItems.findIndex(
        ({ part }) => part.id === currentId,
      );
      if (currentIndex < 0) return;
      let nextIndex: number;
      switch (event.key) {
        case "ArrowDown":
          nextIndex = Math.min(currentIndex + 1, partItems.length - 1);
          break;
        case "ArrowUp":
          nextIndex = Math.max(currentIndex - 1, 0);
          break;
        case "PageDown":
          nextIndex = Math.min(currentIndex + 10, partItems.length - 1);
          break;
        case "PageUp":
          nextIndex = Math.max(currentIndex - 10, 0);
          break;
        case "Home":
          nextIndex = 0;
          break;
        case "End":
          nextIndex = partItems.length - 1;
          break;
        default:
          return;
      }
      event.preventDefault();
      if (nextIndex === currentIndex) return;
      const next = partItems[nextIndex];
      if (!next) return;
      pendingFocusId.current = next.part.id;
      onSelect(next.part.id);
      if (
        virtualized &&
        scrollElement &&
        typeof scrollElement.scrollTo === "function"
      ) {
        virtualizer.scrollToIndex(next.itemIndex, { align: "auto" });
      }
    },
    [onSelect, partItems, scrollElement, virtualized, virtualizer],
  );

  // A key can jump beyond the mounted virtual window. Focus the stable part id
  // after TanStack mounts that row; ordinary pointer selection never enters
  // this path and therefore never steals focus.
  useEffect(() => {
    const wanted = pendingFocusId.current;
    if (!wanted || !scrollElement) return;
    const row = Array.from(
      scrollElement.querySelectorAll<HTMLButtonElement>("[data-part-id]"),
    ).find((candidate) => candidate.dataset.partId === wanted);
    if (!row) return;
    row.focus();
    pendingFocusId.current = null;
  });

  // Search-overlay selection can name a row outside the mounted window. Bring that selected row
  // into the viewport when the browser supports programmatic scrolling; ordinary row clicks are
  // already visible and therefore do not move the list.
  useEffect(() => {
    if (!virtualized || selectedIndex < 0) return;
    if (!scrollElement || typeof scrollElement.scrollTo !== "function") return;
    const mounted = virtualizer
      .getVirtualItems()
      .some((item) => item.index === selectedIndex);
    if (!mounted) virtualizer.scrollToIndex(selectedIndex, { align: "auto" });
  }, [scrollElement, selectedIndex, virtualized, virtualizer]);

  if (parts.length === 0) {
    return (
      <div className="px-3 py-8 text-center text-sm text-t3">
        <Text id="components.no-matches">No Matches</Text>
      </div>
    );
  }

  // Preserve the simple one-item/small-library path. Besides avoiding unnecessary observers,
  // this keeps native document flow and sticky category headers for the overwhelmingly common
  // case while the production large-library path below bounds mounted rows.
  if (!virtualized) {
    return (
      <div
        data-dev-id="components.list"
        data-virtualized="false"
        className="flex flex-col"
      >
        {grouped.map(([category, groupParts]) => (
          <div key={category} className="flex flex-col">
            <CategoryHeader category={category} count={groupParts.length} sticky />
            {groupParts.map((part) => (
              <PartRow
                key={part.id}
                part={part}
                selected={part.id === selectedId}
                tabbable={part.id === tabbableId}
                duplicate={duplicateIds?.has(part.id) ?? false}
                onSelect={onSelect}
                onNavigate={navigate}
              />
            ))}
          </div>
        ))}
      </div>
    );
  }

  const virtualItems = virtualizer.getVirtualItems();
  return (
    <div
      data-dev-id="components.list"
      data-virtualized="true"
      className="relative"
      style={{ height: virtualizer.getTotalSize() }}
    >
      {virtualItems.map((virtualItem) => {
        const item = items[virtualItem.index];
        if (!item) return null;
        const isSticky =
          item.kind === "category" &&
          virtualItem.index === activeStickyIndex.current;
        return (
          <div
            key={item.key}
            data-index={virtualItem.index}
            style={
              isSticky
                ? {
                    position: "sticky",
                    top: 0,
                    zIndex: 2,
                    height: virtualItem.size,
                  }
                : {
                    position: "absolute",
                    top: 0,
                    left: 0,
                    width: "100%",
                    height: virtualItem.size,
                    transform: `translateY(${virtualItem.start}px)`,
                  }
            }
          >
            {item.kind === "category" ? (
              <CategoryHeader
                category={item.category}
                count={item.count}
                sticky={false}
              />
            ) : (
              <PartRow
                part={item.part}
                selected={item.part.id === selectedId}
                tabbable={item.part.id === tabbableId}
                duplicate={duplicateIds?.has(item.part.id) ?? false}
                onSelect={onSelect}
                onNavigate={navigate}
                virtual
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

function CategoryHeader({
  category,
  count,
  sticky,
}: {
  category: string;
  count: number;
  sticky: boolean;
}) {
  return (
    <div
      data-dev-id="components.category-header"
      className={
        (sticky ? "sticky top-0 z-[1] " : "") +
        "flex h-[30px] items-baseline gap-2 border-b border-line bg-[var(--c-sticky)] px-2.5"
      }
    >
      <span className="ui-section-title truncate">{category}</span>
      <span className="ui-component-metadata">{count}</span>
    </div>
  );
}

function PartRow({
  part,
  selected,
  tabbable,
  duplicate,
  onSelect,
  onNavigate,
  virtual = false,
}: {
  part: PartSummary;
  selected: boolean;
  tabbable: boolean;
  duplicate: boolean;
  onSelect: (id: string) => void;
  onNavigate: (
    event: React.KeyboardEvent<HTMLButtonElement>,
    currentId: string,
  ) => void;
  virtual?: boolean;
}) {
  const duplicateTitle = useText(
    "components.row-duplicate-title",
    "Another part shares this MPN",
  );
  const attention = partAttention(part);
  const attentionId = attention ? `part-attention-${part.id}` : undefined;
  // The generated display name only earns a line when it says something the MPN does not.
  const describes = Boolean(part.display_name) && part.display_name !== part.mpn;
  return (
    <button
      type="button"
      data-dev-id="components.row"
      data-part-id={part.id}
      onClick={() => onSelect(part.id)}
      onKeyDown={(event) => onNavigate(event, part.id)}
      aria-current={selected ? "true" : undefined}
      // NO aria-posinset / aria-setsize here. They were added to tell a screen reader "row 3 of
      // 1,000" while the virtualizer keeps only the visible rows in the DOM - a real need - but
      // `role="button"` does not support either attribute, and the list container carries no list
      // role, so nothing ever read them. They were a promise the accessibility tree never saw.
      // Conveying position properly means giving the picker real listbox semantics (container
      // `role="listbox"`, rows `role="option"` + `aria-selected`, category strips `role="group"`),
      // which changes how every caller queries a row and so is a deliberate change of its own
      // rather than a side effect of deleting two inert attributes.
      aria-describedby={attentionId}
      tabIndex={tabbable ? 0 : -1}
      className={
        // A CONTIGUOUS selected row, not a floating rounded card with a gap either side. The
        // selection is an opaque neutral fill spanning the full width of the picker with a solid
        // edge marker, which is what a desktop list does; the rounded pill it replaces made every
        // row look like a control and made the selected one look like a pressed button.
        // 46px: three lines of 15/14/14 leading plus 2px of air top and bottom. The row used to
        // be padded to whatever three lines came to, which put it above the 42-50px a desktop
        // list row is held to and made the virtual estimate a guess.
        "flex w-full items-center gap-2.5 overflow-hidden px-2.5 text-left transition-colors " +
        (virtual ? "h-full " : "h-[46px] ") +
        // The selection is a muted amber fill plus a 2px amber edge. It used to be a neutral
        // `#626262` with a grey marker, which is the same value range as the hover wash and light
        // enough to drop the row's metadata line to 2.0:1 - so the selected row was both the
        // hardest row to distinguish and the hardest to read. Hue separates at no cost to contrast:
        // measured on the amber, t1 10.70, t2 7.25, t4 4.06 in dark and 12.86 / 8.20 / 3.85 in
        // light. Still contiguous, still full-width, still not a rounded card.
        (selected
          ? "bg-selected shadow-[inset_2px_0_0_var(--c-selected-edge)]"
          : "hover:bg-[var(--c-hover)]")
      }
    >
      <RowThumbnail category={part.category} />
      {/* Three lines, in the order the spec fixes them: the identifier, then Manufacturer ·
          Package, then the description. Every one of them shares this one column, so the row has a
          single left edge and the MPN owns the full width of it.

          The MPN used to share line one with the package, and the ATTENTION block held a fixed
          112px beside them both. At a 290px picker that left the identifier about 8px and it
          rendered as `C...` - one letter and an ellipsis - while a footprint name and a truncated
          hint kept their space. That is the hierarchy exactly inverted: the MPN is the one
          visually primary item in a picker row, and everything else on the row qualifies it. So
          the secondary items moved DOWN rather than the identifier being cut: nothing shares line
          one, and both remaining lines hand their space to the MPN before it loses a character. */}
      <div className="min-w-0 flex-1">
        <span
          data-dev-id="components.row-mpn"
          className="ui-row-primary block truncate"
          title={part.mpn || part.display_name}
        >
          {part.mpn || part.display_name}
        </span>
        {part.manufacturer || part.package ? (
          // `flex-1` on the manufacturer is `flex: 1 1 0%`: it asks for none of the line and takes
          // whatever is left, so the package keeps its own width and the manufacturer is the one
          // that gives way. Both can still truncate; neither can reach the MPN's line.
          <span className="flex items-baseline gap-2">
            <span className="ui-row-secondary min-w-0 flex-1 truncate">{part.manufacturer}</span>
            {part.package ? (
              <span
                data-dev-id="components.row-package"
                className="ui-row-metadata min-w-0 truncate"
              >
                {part.package}
              </span>
            ) : null}
          </span>
        ) : null}
        {/* Line three: the description, and the attention state right-aligned against it. The
            description is the one thing on the row whose truncation costs nothing - the whole of
            it is on the opened component - so it is the item that yields, and the attention keeps
            its words. The full sentence, reason and next step both, is on the row's tooltip and
            its accessible label whatever the width. */}
        {attention || describes ? (
          <span className="flex items-center gap-2">
            <span className="ui-row-metadata min-w-0 flex-1 truncate">
              {describes ? part.display_name : ""}
            </span>
            {attention ? (
              <span
                id={attentionId}
                data-dev-id="components.row-warn"
                className="flex min-w-0 items-center gap-1"
                title={attention.description}
              >
                <span className="sr-only">{attention.description}</span>
                <WarnIcon className="h-3 w-3 flex-none text-warn-text" />
                <span className="ui-status-text truncate text-warn-text">
                  {attention.reason}
                </span>
              </span>
            ) : null}
          </span>
        ) : null}
      </div>
      {duplicate ? (
        <span
          data-dev-id="components.row-duplicate"
          className="flex-none"
          title={duplicateTitle}
        >
          <Badge tone="warn" size="sm">
            <Text id="components.row-duplicate-label">Duplicate</Text>
          </Badge>
        </span>
      ) : null}
    </button>
  );
}
