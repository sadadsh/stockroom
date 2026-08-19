/**
 * The Components page: the grouped parts list, the search + facet finder, and the opened
 * components themselves. Server state comes from TanStack Query; the only local state is the
 * search text, the active category facet, the complete-only toggle, and the selected part id.
 *
 * Selecting a picker row OPENS that component into the workspace beside it. There is no
 * per-component tab strip: the native window already carries one tab for Stockroom and one for the
 * provider page a CAD trip opens, and a second row of tabs inside the application competed with it
 * for the same job. The open set and the active component are still tracked in the durable session,
 * because the per-component view state (which CAD asset is expanded) has to live somewhere stable.
 *
 * Honest degradation: a connection error shows a retry surface (not a crash), and a genuinely
 * empty library shows an empty state that names how to add parts.
 */
import { useEffect, useLayoutEffect, useMemo, useReducer, useRef, useState } from "react";
import {
  usePartsQuery,
  useFacetsQuery,
  useDuplicates,
  useRestoreDeletedPart,
} from "../api/queries";
import { ApiError } from "../api/client";
import { useToast } from "../lib/toast";
import { useAddPart } from "../lib/addPart";
import { useCapture } from "../lib/capture";
import { Finder } from "../components/Finder";
import { PartsList } from "../components/PartsList";
import { SearchOverlay } from "../components/SearchOverlay";
import { useScenarioUiState } from "../design-studio/scenarioState";
import { AddPartIcon } from "../components/icons";
import {
  Button,
  EmptyState,
  ErrorState,
  LoadingState,
  RouteHeader,
} from "../components/primitives";
import {
  ComponentWorkspace,
  ComponentWorkspaceEmpty,
} from "../components/component-workspace/ComponentWorkspace";
import { Text, useText } from "../lib/copy";
import {
  closeComponentInSession,
  openComponentInSession,
  pruneOpenComponents,
  readUiSession,
  updateUiSession,
  useUiSession,
} from "../lib/uiSession";
import { COMPONENT_PICKER_WIDTH } from "../lib/libraryLayout";

// The picker's narrowings, exactly as the UI session persists them.
interface ComponentFilters {
  query: string;
  category: string | null;
  completeOnly: boolean;
  duplicatesOnly: boolean;
}

type FiltersAction =
  | { type: "replaced"; value: ComponentFilters }
  | { type: "query"; value: string }
  | { type: "category"; value: string | null }
  | { type: "completeOnly"; value: boolean }
  | { type: "duplicatesOnly"; value: boolean }
  | { type: "cleared" }
  // The search overlay scopes the picker to one category and drops every other narrowing, so the
  // chosen row is definitely present in the list.
  | { type: "scopedToCategory"; category: string };

const NO_FILTERS: ComponentFilters = {
  query: "",
  category: null,
  completeOnly: false,
  duplicatesOnly: false,
};

function initialFilters(): ComponentFilters {
  const persisted = readUiSession().component_filters;
  return {
    query: persisted.query,
    category: persisted.category,
    completeOnly: persisted.complete_only,
    duplicatesOnly: persisted.duplicates_only,
  };
}

function filtersReducer(state: ComponentFilters, action: FiltersAction): ComponentFilters {
  switch (action.type) {
    case "replaced":
      return action.value;
    case "query":
      return { ...state, query: action.value };
    case "category":
      return { ...state, category: action.value };
    case "completeOnly":
      return { ...state, completeOnly: action.value };
    case "duplicatesOnly":
      return { ...state, duplicatesOnly: action.value };
    case "cleared":
      return NO_FILTERS;
    case "scopedToCategory":
      return { ...NO_FILTERS, category: action.category };
  }
}

export function ComponentsPage() {
  // A toast takes a resolved string and so does its action's label, which is why these are read here
  // rather than wrapped at a render site: there is no element to wrap.
  const partDeleted = useText("components.toast-deleted", "Part deleted");
  const undoDeleteLabel = useText("components.toast-undo-delete", "Undo Delete");
  const partRestored = useText("components.toast-restored", "Part restored");
  const restoreFailed = useText("components.toast-restore-failed", "Could not restore the part");
  // The four narrowings are ONE thing: they are persisted as one component_filters document,
  // cleared as a group, and rewritten as a group when the search overlay scopes the picker to a
  // category. So they move as one transition rather than four setter calls that have to agree.
  const scenarioUi = useScenarioUiState();
  const [filters, dispatchFilters] = useReducer(filtersReducer, undefined, () => {
    const persisted = initialFilters();
    const preview = scenarioUi.components?.filters;
    return preview
      ? {
          query: preview.query ?? persisted.query,
          category: preview.category === undefined ? persisted.category : preview.category,
          completeOnly: preview.completeOnly ?? persisted.completeOnly,
          duplicatesOnly: preview.duplicatesOnly ?? persisted.duplicatesOnly,
        }
      : persisted;
  });
  const { query: search, category, completeOnly, duplicatesOnly } = filters;
  const priorScenarioFilters = useRef<ComponentFilters | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(
    () => scenarioUi.components?.selectedId === undefined
      ? readUiSession().selected_ids.component
      : scenarioUi.components.selectedId,
  );
  const displayedSelectedId = scenarioUi.components?.selectedId === undefined
    ? selectedId
    : scenarioUi.components.selectedId;
  const [searchOpen, setSearchOpen] = useState(
    () => readUiSession().open_surface === "search",
  );
  const scenarioSearchOpen = scenarioUi.search?.open;
  const scenarioServiceError = scenarioUi.service?.error;
  const priorSearchOpen = useRef<boolean | null>(null);
  const [listScrollElement, setListScrollElement] =
    useState<HTMLDivElement | null>(null);

  useEffect(() => {
    const preview = scenarioUi.components;
    if (!preview) {
      if (priorScenarioFilters.current) {
        dispatchFilters({ type: "replaced", value: priorScenarioFilters.current });
      }
      priorScenarioFilters.current = null;
      return;
    }
    if (priorScenarioFilters.current === null) priorScenarioFilters.current = filters;
    dispatchFilters({
      type: "replaced",
      value: {
        query: preview.filters?.query ?? "",
        category: preview.filters?.category ?? null,
        completeOnly: preview.filters?.completeOnly ?? false,
        duplicatesOnly: preview.filters?.duplicatesOnly ?? false,
      },
    });
    // A scenario object is the transition boundary. The prior filters are captured exactly once
    // and restored on exit; including `filters` here would overwrite that saved real-data state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenarioUi.components]);

  const session = useUiSession();
  const partsQuery = usePartsQuery({ q: search, category, completeOnly });
  const facetsQuery = useFacetsQuery();
  const duplicatesQuery = useDuplicates();
  const restoreDeletedPart = useRestoreDeletedPart();
  const { toast } = useToast();
  const { open: openAddPart } = useAddPart();
  const { onReopen } = useCapture();

  useEffect(() => {
    if (scenarioSearchOpen === undefined) {
      if (priorSearchOpen.current !== null) setSearchOpen(priorSearchOpen.current);
      priorSearchOpen.current = null;
      return;
    }
    if (priorSearchOpen.current === null) priorSearchOpen.current = searchOpen;
    setSearchOpen(scenarioSearchOpen);
  }, [scenarioSearchOpen]);

  // Persist the exact primary Library view as one bounded document. This runs
  // only when a value changed, so mounting from an injected snapshot does not
  // generate a write that merely echoes what the host just restored.
  //
  // The SELECTION is not checkpointed here. It is written by the act that changes it
  // (selectComponent below), because as part of this effect the auto-select further down set
  // selectedId, which woke this effect, which re-rendered the page a third time for one action.
  useEffect(() => {
    const current = readUiSession();
    const nextSurface = searchOpen
      ? "search"
      : current.open_surface === "search"
        ? null
        : current.open_surface;
    if (
      current.component_filters.query === search &&
      current.component_filters.category === category &&
      current.component_filters.complete_only === completeOnly &&
      current.component_filters.duplicates_only === duplicatesOnly &&
      current.open_surface === nextSurface
    ) {
      return;
    }
    updateUiSession((snapshot) => ({
      ...snapshot,
      component_filters: {
        query: search,
        category,
        complete_only: completeOnly,
        duplicates_only: duplicatesOnly,
      },
      open_surface: nextSurface,
    }));
  }, [category, completeOnly, duplicatesOnly, search, searchOpen]);

  usePickerScrollAnchor(
    listScrollElement,
    !partsQuery.isLoading && !partsQuery.error,
    displayedSelectedId,
  );
  useSearchHotkey(searchOpen, () => setSearchOpen(true));

  // Ids that share an MPN with another part (a real accidental duplicate). Shared
  // footprints are normal and never counted. Drives the Duplicate badges and the
  // Duplicates filter; the filter is applied client-side over the server list.
  const duplicateIds = useMemo(
    () =>
      new Set(
        (duplicatesQuery.data?.by_mpn ?? []).flatMap((g) => g.parts.map((p) => p.id)),
      ),
    [duplicatesQuery.data],
  );
  const allParts = partsQuery.data?.parts ?? [];
  const parts = useMemo(
    () => duplicatesOnly ? allParts.filter((part) => duplicateIds.has(part.id)) : allParts,
    [allParts, duplicateIds, duplicatesOnly],
  );

  // Move the selection and checkpoint it in the same act. Both belong to the selection: keeping
  // the checkpoint in a separate effect meant every selection cost an extra render pass.
  function selectComponent(id: string | null) {
    setSelectedId(id);
    if (readUiSession().selected_ids.component === id) return;
    updateUiSession((snapshot) => ({
      ...snapshot,
      selected_ids: { ...snapshot.selected_ids, component: id },
    }));
  }

  function openComponent(id: string) {
    setSelectedId(id);
    updateUiSession((snapshot) => {
      const opened = openComponentInSession(snapshot, id);
      return { ...opened, selected_ids: { ...opened.selected_ids, component: id } };
    });
  }

  /**
   * The background capture pill, and the intake flow, ask to reopen a part: open it here, because
   * this page owns the selection and the tab strip.
   *
   * A SUBSCRIPTION, and the effect does nothing but subscribe and hand back its unsubscribe. The
   * capture store used to publish a latched `reopenPartId` instead, which cost one render to read
   * and a second because reading it moved the selection, which woke the auto-select effect below -
   * three renders for a click that knew the answer before the first one. The store now calls this
   * inside the click, so the selection moves in the same commit as everything else that click does.
   *
   * The handler goes through a ref because `openComponent` is a fresh closure every render and this
   * subscription must not be torn down and rebuilt on each one; the ref is written in a LAYOUT
   * effect so a request delivered from a passive effect elsewhere can never run last render's copy.
   */
  const openComponentRef = useRef(openComponent);
  useLayoutEffect(() => {
    openComponentRef.current = openComponent;
  });
  useEffect(() => onReopen((partId) => openComponentRef.current(partId)), [onReopen]);

  /**
   * A component was deleted from its own workspace.
   *
   * The confirmation and the mutation belong to the workspace, which is where the component is.
   * The AFTERMATH belongs here: the page holds the selection, and it is still mounted once that
   * workspace has gone - which is the only place an Undo can outlive the thing it undoes.
   */
  function componentDeleted(id: string) {
    setSelectedId(null);
    updateUiSession(() => {
      const closed = closeComponentInSession(readUiSession(), id);
      return { ...closed, selected_ids: { ...closed.selected_ids, component: null } };
    });
    toast(partDeleted, "ok", {
      label: undoDeleteLabel,
      onClick: () => {
        restoreDeletedPart.mutate(id, {
          onSuccess: () => {
            openComponent(id);
            toast(partRestored, "ok");
          },
          onError: (err) =>
            toast(
              err instanceof ApiError ? err.message : restoreFailed,
              "err",
            ),
        });
      },
    });
  }

  // Auto-select the first part when the current selection falls out of the list
  // (a new search, a category change, or the first successful load). Act only on
  // SETTLED data: while a refetch is in flight TanStack retains the previous
  // list, so re-selecting parts[0] here would re-pick a just-deleted or
  // filtered-out part and fire a wasted, guaranteed-404 workspace request.
  const partsFetching = partsQuery.isFetching;
  const activeComponent = scenarioUi.components?.selectedId === undefined
    ? session.active_component
    : scenarioUi.components.selectedId;
  const scenarioWorkspaceKey = JSON.stringify({
    surface: scenarioUi.components?.surface ?? null,
    preview: scenarioUi.components?.preview ?? null,
    confirmDelete: scenarioUi.components?.confirmDelete ?? false,
    sourcesTab: scenarioUi.components?.sourcesTab ?? null,
  });
  useEffect(() => {
    if (partsFetching) return;
    if (scenarioUi.components?.autoSelect === false) return;
    if (parts.length === 0) {
      if (selectedId !== null) selectComponent(null);
      return;
    }
    if (!selectedId || !parts.some((p) => p.id === selectedId)) {
      openComponent(parts[0].id);
    } else if (activeComponent !== selectedId) {
      // A restored snapshot names the selection but may predate the tab strip (a migrated v1
      // session), so the selected component still has to be given its tab.
      openComponent(selectedId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [parts, selectedId, partsFetching, activeComponent, scenarioUi.components?.autoSelect]);

  // A tab whose component left the library cannot render, so it goes. Only ever evaluated against
  // an UNFILTERED settled list: a search narrows what is listed without deleting anything, and
  // pruning on a filtered list would close tabs as someone typed.
  const hasSearchOrFilter = !!search || !!category || completeOnly || duplicatesOnly;
  useEffect(() => {
    if (partsFetching || hasSearchOrFilter || allParts.length === 0) return;
    const available = new Set(allParts.map((part) => part.id));
    updateUiSession((snapshot) => pruneOpenComponents(snapshot, available));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allParts, partsFetching, hasSearchOrFilter]);


  // Open a part chosen in the search overlay: scope the picker to its category and clear the
  // narrowing filters so the row is present in the list, open it, and close the overlay.
  function openFromSearch(id: string, cat: string) {
    dispatchFilters({ type: "scopedToCategory", category: cat });
    openComponent(id);
    setSearchOpen(false);
  }

  const emptyLibrary =
    !partsQuery.isLoading &&
    !partsQuery.error &&
    allParts.length === 0 &&
    !hasSearchOrFilter;

  if (emptyLibrary) return <EmptyLibrary onAddParts={openAddPart} />;

  // north-star .app: rail | list | opened components, each column self-heading - no full-width
  // page header band (the active rail item + the rail's library readout carry that).
  return (
    <div data-dev-id="components.root" className="flex min-h-0 flex-1">
        {/* picker: a docked panel - an Altium title strip, then the padded body. The rail's
            right border and the workspace's left border frame this column, so it needs none. */}
        <PickerColumn
          count={parts.length}
          onAddParts={openAddPart}
          filters={filters}
          dispatchFilters={dispatchFilters}
          facets={facetsQuery.data}
          duplicateIds={duplicateIds}
          onOpenSearch={() => setSearchOpen(true)}
          isLoading={partsQuery.isLoading}
          error={scenarioServiceError ? new ApiError(0, scenarioServiceError) : partsQuery.error}
          parts={parts}
          selectedId={displayedSelectedId}
          onSelect={openComponent}
          scrollElement={listScrollElement}
          onScrollElement={setListScrollElement}
          onRetry={() => partsQuery.refetch()}
          hasSearchOrFilter={hasSearchOrFilter}
        />

        {/* the opened component: no tab band above it, because there are no per-component tabs.
            The column never scrolls; the workspace inside it owns its own three scroll regions. */}
        <div
          data-dev-id="components.detail-pane"
          className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden border-l border-line"
        >
          <div className="min-h-0 min-w-0 flex-1 overflow-hidden">
            {activeComponent ? (
              <ComponentWorkspace
                key={`${activeComponent}:${scenarioWorkspaceKey}`}
                componentId={activeComponent}
                onDeleted={componentDeleted}
                initialSurface={scenarioUi.components?.surface}
                initialPreview={scenarioUi.components?.preview}
                initialConfirmDelete={scenarioUi.components?.confirmDelete}
                initialSourcesTab={scenarioUi.components?.sourcesTab}
                initialCadView={scenarioUi.components?.cadView}
              />
            ) : partsQuery.isLoading ? (
              <div
                data-dev-id="components.select-prompt"
                className="flex h-full items-center justify-center px-6"
              >
                {/* Says what THIS pane is waiting for. It used to repeat the picker's own
                    loading line word for word, which put the same sentence on screen twice. */}
                <LoadingState dense id="components.loading">Nothing is open so far. The component list is still loading.</LoadingState>
              </div>
            ) : (
              <ComponentWorkspaceEmpty />
            )}
          </div>
        </div>

        {searchOpen ? (
          <SearchOverlay
            key={JSON.stringify(scenarioUi.search ?? {})}
            onClose={() => setSearchOpen(false)}
            onOpenPart={openFromSearch}
          />
        ) : null}

    </div>
  );
}

/**
 * The whole route when the library holds nothing yet.
 *
 * It replaces the page rather than sitting inside it, which is the reason it is a component and not
 * a branch of the page's markup: there is no picker, no workspace and no search to render beside
 * it, so it shares no state with any of them and takes only the one action it offers. This is the
 * ONE place Add Parts keeps its large form - adding a part genuinely is the whole screen's purpose
 * here, where everywhere else it is a compact toolbar action.
 */
function EmptyLibrary({ onAddParts }: { onAddParts: () => void }) {
  // Keep the only action in a new catalog free of Design Studio geometry wrappers. A saved toolbar
  // label override must never move this required first action outside its button.
  const addParts = useText("components.add-parts", "Add Parts");
  return (
    <div data-dev-id="components.root" className="flex min-h-0 flex-1">
      <div
        data-dev-id="components.empty"
        className="flex flex-1 items-center justify-center p-6"
      >
        <div className="flex max-w-md flex-col items-center text-center">
          <span className="mb-3 text-t3">
            <AddPartIcon />
          </span>
          <h1 className="text-base font-semibold text-t1">
            <Text id="components.empty-title">No Components Yet</Text>
          </h1>
          <p className="mt-1.5 text-sm leading-relaxed text-t3">
            <Text id="components.empty-body">
              Add a manufacturer part number. Stockroom will keep its KiCad, Altium, STEP,
              source, and validation evidence together.
            </Text>
          </p>
          <Button
            variant="accent"
            data-dev-id="components.empty-add"
            icon={<AddPartIcon />}
            onClick={onAddParts}
            className="mt-4"
          >
            {addParts}
          </Button>
        </div>
      </div>
    </div>
  );
}

function PickerBody({
  isLoading,
  error,
  parts,
  duplicateIds,
  selectedId,
  onSelect,
  scrollElement,
  onRetry,
  hasSearchOrFilter,
  onClearFilters,
}: {
  isLoading: boolean;
  error: Error | null;
  parts: import("../api/types").PartSummary[];
  duplicateIds: Set<string>;
  selectedId: string | null;
  onSelect: (id: string) => void;
  scrollElement: HTMLDivElement | null;
  onRetry: () => void;
  hasSearchOrFilter: boolean;
  onClearFilters: () => void;
}) {
  // Every branch below is one of the shared product states rather than five hand-written
  // centred divs, and every string goes through the copy layer. It did not: "Loading parts...",
  // "Try Again", "Cannot reach the Stockroom server." and "Clear Filters" were the only
  // user-visible strings on this route that could not be overridden, and the failure branch put
  // `error.message` - a raw transport exception - straight in front of the person.
  if (isLoading) {
    return (
      <LoadingState className="mt-2" id="components.list-loading" devId="components.list-loading">
        Loading this catalog's components...
      </LoadingState>
    );
  }
  if (error) {
    const status = error instanceof ApiError ? error.status : undefined;
    return (
      <div className="mt-2">
        {status === 0 ? (
          <ErrorState id="components.list-unreachable" devId="components.list-unreachable" onRetry={onRetry}>
            Stockroom is not answering on this machine.
          </ErrorState>
        ) : status === 401 ? (
          <ErrorState id="components.list-unauthorized" onRetry={onRetry}>
            This machine is not signed in to the catalog.
          </ErrorState>
        ) : (
          <ErrorState id="components.list-failed" devId="components.list-failed" onRetry={onRetry}>
            This catalog's components could not be listed.
          </ErrorState>
        )}
      </div>
    );
  }
  if (parts.length === 0) {
    // An honest empty state: distinguish "no matches for this filter" from
    // "the library itself is empty".
    if (hasSearchOrFilter) {
      return (
        <div className="mt-2 flex flex-col items-start gap-2">
          <EmptyState id="components.list-no-match" devId="components.list-no-match">
            No component matches the current search or filter.
          </EmptyState>
          <Button small onClick={onClearFilters}>
            <Text id="components.clear-filters">Clear Filters</Text>
          </Button>
        </div>
      );
    }
    return (
      <div data-dev-id="components.empty" className="flex flex-col items-center gap-2.5 px-4 py-10 text-center">
        <span className="text-t3">
          <AddPartIcon />
        </span>
        <div className="text-sm font-medium text-t2">
          <Text id="components.empty-title">No Components Yet</Text>
        </div>
        <div className="text-xs text-t3">
          <Text id="components.empty-hint">Add a part to get started.</Text>
        </div>
      </div>
    );
  }
  return (
    <PartsList
      parts={parts}
      duplicateIds={duplicateIds}
      selectedId={selectedId}
      onSelect={onSelect}
      scrollElement={scrollElement}
    />
  );
}


// The docked picker column: the title strip with Add Parts, the finder, and the scrolling list.
// Extracted so ComponentsPage stays the page's data flow rather than also being this pane's markup.
function PickerColumn({
  count,
  onAddParts,
  filters,
  dispatchFilters,
  facets,
  duplicateIds,
  onOpenSearch,
  isLoading,
  error,
  parts,
  selectedId,
  onSelect,
  scrollElement,
  onScrollElement,
  onRetry,
  hasSearchOrFilter,
}: {
  count: number;
  onAddParts: () => void;
  filters: ComponentFilters;
  dispatchFilters: (action: FiltersAction) => void;
  facets: React.ComponentProps<typeof Finder>["facets"];
  duplicateIds: Set<string>;
  onOpenSearch: () => void;
  isLoading: boolean;
  error: Error | null;
  parts: React.ComponentProps<typeof PartsList>["parts"];
  selectedId: string | null;
  onSelect: (id: string) => void;
  scrollElement: HTMLDivElement | null;
  onScrollElement: (element: HTMLDivElement | null) => void;
  onRetry: () => void;
  hasSearchOrFilter: boolean;
}) {
  // Keep the required toolbar action immune to stale personal geometry from earlier layouts.
  const addParts = useText("components.add-parts", "Add Parts");
  return (
        <div
          data-dev-id="components.picker"
          className="flex flex-none flex-col"
          style={{ width: COMPONENT_PICKER_WIDTH }}
        >
          <RouteHeader
            data-dev-id="components.list-title"
            right={count ? count.toLocaleString() : undefined}
          >
            <Text id="components.list-title">Components</Text>
          </RouteHeader>
          <div className="px-3 pt-3">
            <Finder
              search={filters.query}
              onSearch={(value) => dispatchFilters({ type: "query", value })}
              facets={facets}
              category={filters.category}
              onCategory={(value) => dispatchFilters({ type: "category", value })}
              completeOnly={filters.completeOnly}
              onCompleteOnly={(value) => dispatchFilters({ type: "completeOnly", value })}
              duplicatesOnly={filters.duplicatesOnly}
              onDuplicatesOnly={(value) => dispatchFilters({ type: "duplicatesOnly", value })}
              duplicateCount={duplicateIds.size}
              onOpenSearch={onOpenSearch}
            />
            <Button
              variant="accent"
              data-dev-id="components.toolbar-add"
              icon={<AddPartIcon />}
              onClick={onAddParts}
              className="mt-2 w-full justify-center"
            >
              {addParts}
            </Button>
          </div>
          <div
            ref={onScrollElement}
            data-dev-id="components.list-scroll"
            className="mt-2 min-h-0 flex-1 overflow-y-auto px-3 pb-3"
          >
            <PickerBody
              isLoading={isLoading}
              error={error}
              parts={parts}
              duplicateIds={duplicateIds}
              selectedId={selectedId}
              onSelect={onSelect}
              scrollElement={scrollElement}
              onRetry={onRetry}
              hasSearchOrFilter={hasSearchOrFilter}
              onClearFilters={() => dispatchFilters({ type: "cleared" })}
            />
          </div>
    </div>
  );
}

// Ctrl/Cmd+K (and "/" when not already typing) opens the full-screen parametric search. The opener
// is held in a ref so the listener subscribes once per searchOpen change rather than re-attaching
// on every render because the caller passed a fresh arrow function.
function useSearchHotkey(searchOpen: boolean, onOpen: () => void) {
  const openRef = useRef(onOpen);
  useLayoutEffect(() => {
    openRef.current = onOpen;
  });
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        openRef.current();
      } else if (
        e.key === "/" &&
        !searchOpen &&
        !(e.target instanceof HTMLElement &&
          /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName))
      ) {
        e.preventDefault();
        openRef.current();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [searchOpen]);
}

/**
 * Restore and continuously checkpoint the picker scroll, as one concern rather than as three
 * loose pieces of the page body.
 *
 * part accompanies the pixel offset, so a future projection can re-anchor
 * after insertions instead of treating the number as an identity.
 * 
 * The restore CANNOT run against the loading placeholder. While the list query is
 * in flight the picker body is a one-line "Loading parts..." block, and a browser
 * clamps `scrollTop = N` against that tiny scroll height - the anchor silently
 * became 0 and the checkpoint below then wrote that 0 back over the saved offset.
 * So: wait for the settled list, retry while the assignment is still being clamped
 * (virtual rows arrive over more than one frame), and refuse to checkpoint until
 * the restore has actually landed.
 */
function usePickerScrollAnchor(
  scrollElement: HTMLDivElement | null,
  contentSettled: boolean,
  selectedId: string | null,
) {
  const selectedIdRef = useRef(selectedId);
  // Synced in a layout effect, not during render: render can be replayed or thrown away, and the
  // persisted list anchor must never name a selection no commit ever published. Layout effects land
  // before this commit's passive effects, so the scroll checkpoint below (and its teardown flush)
  // still writes this render's selection.
  useLayoutEffect(() => {
    selectedIdRef.current = selectedId;
  });
  const listRestoredRef = useRef(false);
  useEffect(() => {
    if (!scrollElement || !contentSettled) return;
    const target = readUiSession().component_list_anchor.offset_px;
    let frame: number | null = null;
    let lastScrollHeight = -1;
    const restore = () => {
      frame = null;
      if (listRestoredRef.current) return;
      scrollElement.scrollTop = target;
      // Give up (and accept the clamped position) once the content stops growing:
      // an anchor past the end of a now-shorter list is stale, not pending.
      if (
        Math.round(scrollElement.scrollTop) >= target ||
        scrollElement.scrollHeight === lastScrollHeight
      ) {
        listRestoredRef.current = true;
        return;
      }
      lastScrollHeight = scrollElement.scrollHeight;
      frame = requestAnimationFrame(restore);
    };
    restore();
    let pending: number | null = null;
    const checkpoint = () => {
      pending = null;
      if (!listRestoredRef.current) return;
      const offset = Math.max(0, Math.round(scrollElement.scrollTop));
      const current = readUiSession();
      if (
        current.component_list_anchor.offset_px === offset &&
        current.component_list_anchor.part_id === selectedIdRef.current
      ) {
        return;
      }
      updateUiSession((snapshot) => ({
        ...snapshot,
        component_list_anchor: {
          part_id: selectedIdRef.current,
          offset_px: offset,
        },
      }));
    };
    const onScroll = () => {
      if (pending !== null) window.clearTimeout(pending);
      pending = window.setTimeout(checkpoint, 40);
    };
    scrollElement.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      scrollElement.removeEventListener("scroll", onScroll);
      if (frame !== null) cancelAnimationFrame(frame);
      if (pending !== null) window.clearTimeout(pending);
      checkpoint();
    };
  }, [contentSettled, scrollElement]);
}
