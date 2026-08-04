/**
 * The Components page: the grouped parts list, the search + facet finder, and the opened
 * components themselves. Server state comes from TanStack Query; the only local state is the
 * search text, the active category facet, the complete-only toggle, and the selected part id.
 *
 * A component OPENS into a tab rather than replacing a single detail pane. Comparing two parts is
 * the ordinary case in a library - "is this the same footprint as the other one", "which of these
 * two has the stock" - and a one-slot detail pane made that a navigation exercise with the answer
 * held in the person's head. Tabs are bounded (a strip that can grow forever is not a strip),
 * keyed by stable component id, and persisted through the durable session, so closing the window
 * mid-comparison does not lose it.
 *
 * Honest degradation: a connection error shows a retry surface (not a crash), and a genuinely
 * empty library shows an empty state that names how to add parts.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import {
  usePartsQuery,
  useFacetsQuery,
  useDuplicates,
  useDeletePart,
  useRestoreDeletedPart,
} from "../api/queries";
import { ApiError } from "../api/client";
import { useToast } from "../lib/toast";
import { useAddPart } from "../lib/addPart";
import { useCapture } from "../lib/capture";
import { Finder } from "../components/Finder";
import { PartsList } from "../components/PartsList";
import { SearchOverlay } from "../components/SearchOverlay";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { AddPartIcon, TrashIcon } from "../components/icons";
import {
  Button,
  EmptyState,
  ErrorState,
  LoadingState,
  RouteHeader,
  TabStrip,
  type TabItem,
} from "../components/primitives";
import {
  ComponentWorkspace,
  ComponentWorkspaceEmpty,
} from "../components/component-workspace/ComponentWorkspace";
import { Text, useText } from "../lib/copy";
import { componentTabDevId } from "../lib/componentDevIds";
import {
  closeComponentInSession,
  openComponentInSession,
  pruneOpenComponents,
  readUiSession,
  updateUiSession,
  useUiSession,
} from "../lib/uiSession";
import { COMPONENT_PICKER_WIDTH } from "../lib/libraryLayout";

export function ComponentsPage() {
  const openComponentsLabel = useText("components.open-tabs-label", "Open components");
  const [search, setSearch] = useState(() => readUiSession().component_filters.query);
  const [category, setCategory] = useState<string | null>(
    () => readUiSession().component_filters.category,
  );
  const [completeOnly, setCompleteOnly] = useState(
    () => readUiSession().component_filters.complete_only,
  );
  const [duplicatesOnly, setDuplicatesOnly] = useState(
    () => readUiSession().component_filters.duplicates_only,
  );
  const [selectedId, setSelectedId] = useState<string | null>(
    () => readUiSession().selected_ids.component,
  );
  const [searchOpen, setSearchOpen] = useState(
    () => readUiSession().open_surface === "search",
  );
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [listScrollElement, setListScrollElement] =
    useState<HTMLDivElement | null>(null);
  const selectedIdRef = useRef(selectedId);
  selectedIdRef.current = selectedId;

  const session = useUiSession();
  const partsQuery = usePartsQuery({ q: search, category, completeOnly });
  const facetsQuery = useFacetsQuery();
  const duplicatesQuery = useDuplicates();
  const deletePart = useDeletePart();
  const restoreDeletedPart = useRestoreDeletedPart();
  const { toast } = useToast();
  const { open: openAddPart } = useAddPart();
  const { reopenPartId } = useCapture();
  const confirmDeleteTitle = useText("components.delete-title", "Delete Part");
  const confirmDeleteBody = useText(
    "components.delete-body",
    "This removes the component from the library. It can be restored from the toast that follows.",
  );
  const confirmDeleteLabel = useText("components.delete-confirm", "Delete");

  // Persist the exact primary Library view as one bounded document. This runs
  // only when a value changed, so mounting from an injected snapshot does not
  // generate a write that merely echoes what the host just restored.
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
      current.selected_ids.component === selectedId &&
      current.open_surface === nextSurface
    ) {
      return;
    }
    updateUiSession((snapshot) => ({
      ...snapshot,
      selected_ids: { ...snapshot.selected_ids, component: selectedId },
      component_filters: {
        query: search,
        category,
        complete_only: completeOnly,
        duplicates_only: duplicatesOnly,
      },
      open_surface: nextSurface,
    }));
  }, [category, completeOnly, duplicatesOnly, search, searchOpen, selectedId]);

  // Restore and continuously checkpoint the picker scroll. The stable selected
  // part accompanies the pixel offset, so a future projection can re-anchor
  // after insertions instead of treating the number as an identity.
  //
  // The restore CANNOT run against the loading placeholder. While the list query is
  // in flight the picker body is a one-line "Loading parts..." block, and a browser
  // clamps `scrollTop = N` against that tiny scroll height - the anchor silently
  // became 0 and the checkpoint below then wrote that 0 back over the saved offset.
  // So: wait for the settled list, retry while the assignment is still being clamped
  // (virtual rows arrive over more than one frame), and refuse to checkpoint until
  // the restore has actually landed.
  const listContentSettled = !partsQuery.isLoading && !partsQuery.error;
  const listRestoredRef = useRef(false);
  useEffect(() => {
    if (!listScrollElement || !listContentSettled) return;
    const target = readUiSession().component_list_anchor.offset_px;
    let frame: number | null = null;
    let lastScrollHeight = -1;
    const restore = () => {
      frame = null;
      if (listRestoredRef.current) return;
      listScrollElement.scrollTop = target;
      // Give up (and accept the clamped position) once the content stops growing:
      // an anchor past the end of a now-shorter list is stale, not pending.
      if (
        Math.round(listScrollElement.scrollTop) >= target ||
        listScrollElement.scrollHeight === lastScrollHeight
      ) {
        listRestoredRef.current = true;
        return;
      }
      lastScrollHeight = listScrollElement.scrollHeight;
      frame = requestAnimationFrame(restore);
    };
    restore();
    let pending: number | null = null;
    const checkpoint = () => {
      pending = null;
      if (!listRestoredRef.current) return;
      const offset = Math.max(0, Math.round(listScrollElement.scrollTop));
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
    listScrollElement.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      listScrollElement.removeEventListener("scroll", onScroll);
      if (frame !== null) cancelAnimationFrame(frame);
      if (pending !== null) window.clearTimeout(pending);
      checkpoint();
    };
  }, [listContentSettled, listScrollElement]);

  // The background capture pill asks to reopen its part: open it here so its workspace comes up.
  useEffect(() => {
    if (reopenPartId) openComponent(reopenPartId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reopenPartId]);

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
  const parts = duplicatesOnly
    ? allParts.filter((p) => duplicateIds.has(p.id))
    : allParts;

  // A tab keeps the name it was opened with even when a later search filters its component out of
  // the list. Without this the strip would relabel itself to raw ids the moment someone typed.
  const tabNames = useRef(new Map<string, string>());
  for (const part of allParts) {
    tabNames.current.set(part.id, part.display_name || part.mpn || part.id);
  }

  function openComponent(id: string) {
    setSelectedId(id);
    updateUiSession((snapshot) => openComponentInSession(snapshot, id));
  }

  function closeComponent(id: string) {
    const next = closeComponentInSession(readUiSession(), id);
    updateUiSession(() => next);
    if (next.active_component) setSelectedId(next.active_component);
  }

  function handleDelete() {
    if (!selectedId) return;
    const deletedId = selectedId;
    deletePart.mutate(deletedId, {
      onSuccess: () => {
        toast("Part deleted", "ok", {
          label: "Undo Delete",
          onClick: () => {
            restoreDeletedPart.mutate(deletedId, {
              onSuccess: () => {
                openComponent(deletedId);
                toast("Part restored", "ok");
              },
              onError: (err) =>
                toast(
                  err instanceof ApiError ? err.message : "Could not restore the part",
                  "err",
                ),
            });
          },
        });
        // Drop the tab and the selection; the auto-select effect picks the next part once the
        // invalidated list refetches.
        closeComponent(deletedId);
        setSelectedId(null);
      },
      onError: (err) =>
        toast(err instanceof ApiError ? err.message : "Could not delete", "err"),
    });
  }

  // Auto-select the first part when the current selection falls out of the list
  // (a new search, a category change, or the first successful load). Act only on
  // SETTLED data: while a refetch is in flight TanStack retains the previous
  // list, so re-selecting parts[0] here would re-pick a just-deleted or
  // filtered-out part and fire a wasted, guaranteed-404 workspace request.
  const partsFetching = partsQuery.isFetching;
  const activeComponent = session.active_component;
  useEffect(() => {
    if (partsFetching) return;
    if (parts.length === 0) {
      if (selectedId !== null) setSelectedId(null);
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
  }, [parts, selectedId, partsFetching, activeComponent]);

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

  // Ctrl/Cmd+K (and "/" when not already typing) opens the full-screen parametric search.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setSearchOpen(true);
      } else if (
        e.key === "/" &&
        !searchOpen &&
        !(e.target instanceof HTMLElement &&
          /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName))
      ) {
        e.preventDefault();
        setSearchOpen(true);
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [searchOpen]);

  // Open a part chosen in the search overlay: scope the picker to its category and clear the
  // narrowing filters so the row is present in the list, open it, and close the overlay.
  function openFromSearch(id: string, cat: string) {
    setCategory(cat);
    setCompleteOnly(false);
    setDuplicatesOnly(false);
    setSearch("");
    openComponent(id);
    setSearchOpen(false);
  }

  const emptyLibrary =
    !partsQuery.isLoading &&
    !partsQuery.error &&
    allParts.length === 0 &&
    !hasSearchOrFilter;

  const openTabs: TabItem<string>[] = session.open_components.map((id) => ({
    id,
    label: tabNames.current.get(id) ?? id,
  }));

  if (emptyLibrary) {
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
                source, and verification evidence together.
              </Text>
            </p>
            <Button
              variant="accent"
              data-dev-id="components.add-parts"
              icon={<AddPartIcon />}
              onClick={openAddPart}
              className="mt-4"
            >
              <Text id="components.add-parts">Add Parts</Text>
            </Button>
          </div>
        </div>
      </div>
    );
  }

  // north-star .app: rail | list | opened components, each column self-heading - no full-width
  // page header band (the active rail item + the rail's library readout carry that).
  return (
    <div data-dev-id="components.root" className="flex min-h-0 flex-1">
        {/* picker: a docked panel - an Altium title strip, then the padded body. The rail's
            right border and the workspace's left border frame this column, so it needs none. */}
        <div
          data-dev-id="components.picker"
          className="flex flex-none flex-col"
          style={{ width: COMPONENT_PICKER_WIDTH }}
        >
          <RouteHeader
            data-dev-id="components.list-title"
            right={parts.length ? parts.length.toLocaleString() : undefined}
          >
            <Text id="components.list-title">Components</Text>
          </RouteHeader>
          <div className="px-3 pt-3">
            <Button
              variant="soft"
              data-dev-id="components.add-parts"
              icon={<AddPartIcon />}
              onClick={openAddPart}
              className="mb-2.5 h-9 w-full justify-center"
            >
              <Text id="components.add-parts">Add Parts</Text>
            </Button>
            <Finder
              search={search}
              onSearch={setSearch}
              facets={facetsQuery.data}
              category={category}
              onCategory={setCategory}
              completeOnly={completeOnly}
              onCompleteOnly={setCompleteOnly}
              duplicatesOnly={duplicatesOnly}
              onDuplicatesOnly={setDuplicatesOnly}
              duplicateCount={duplicateIds.size}
              onOpenSearch={() => setSearchOpen(true)}
            />
          </div>
          <div
            ref={setListScrollElement}
            data-dev-id="components.list-scroll"
            className="mt-2 min-h-0 flex-1 overflow-y-auto px-3 pb-3"
          >
            <PickerBody
              isLoading={partsQuery.isLoading}
              error={partsQuery.error}
              parts={parts}
              duplicateIds={duplicateIds}
              selectedId={selectedId}
              onSelect={openComponent}
              scrollElement={listScrollElement}
              onRetry={() => partsQuery.refetch()}
              hasSearchOrFilter={hasSearchOrFilter}
              onClearFilters={() => {
                setSearch("");
                setCategory(null);
                setCompleteOnly(false);
                setDuplicatesOnly(false);
              }}
            />
          </div>
        </div>

        {/* opened components: a tab band on the same 34px chrome line as the rail and picker
            headers, then the workspace itself. The column never scrolls. */}
        <div
          data-dev-id="components.detail-pane"
          className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden border-l border-line"
        >
          <div
            data-dev-id="components.workspace-band"
            className="flex h-[34px] flex-none items-center gap-2 border-b border-line bg-band px-3"
          >
            {openTabs.length > 0 && activeComponent ? (
              <TabStrip
                tabs={openTabs}
                active={activeComponent}
                onSelect={openComponent}
                idBase="component-browser"
                devIdBase="component-browser"
                devIdForTab={componentTabDevId}
                density="compact"
                className="min-w-0 overflow-hidden"
                aria-label={openComponentsLabel}
              />
            ) : (
              <span className="text-xs font-semibold text-t2">
                <Text id="component-browser.band-title">Open Components</Text>
              </span>
            )}
            {activeComponent ? (
              <button
                type="button"
                data-dev-id="component-browser.close-tab"
                onClick={() => closeComponent(activeComponent)}
                className="ml-auto flex-none rounded-control px-1.5 py-0.5 text-2xs font-medium text-t3 transition-colors hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc"
              >
                <Text id="component-browser.close-tab">Close Tab</Text>
              </button>
            ) : null}
            {selectedId ? (
              <button
                type="button"
                data-dev-id="component-browser.delete"
                aria-busy={deletePart.isPending}
                disabled={deletePart.isPending}
                onClick={() => setConfirmDelete(true)}
                className={
                  "flex-none rounded-control px-1.5 py-0.5 text-2xs font-medium text-err " +
                  "transition-colors hover:brightness-125 focus-visible:outline " +
                  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc " +
                  "disabled:pointer-events-none disabled:opacity-60 " +
                  (activeComponent ? "" : "ml-auto ")
                }
              >
                <span className="inline-flex items-center gap-1">
                  <TrashIcon />
                  {deletePart.isPending ? (
                    <Text id="component-browser.deleting">Deleting Part</Text>
                  ) : (
                    <Text id="component-browser.delete">Delete Part</Text>
                  )}
                </span>
              </button>
            ) : null}
          </div>
          <div className="min-h-0 min-w-0 flex-1 overflow-hidden">
            {activeComponent ? (
              <ComponentWorkspace key={activeComponent} componentId={activeComponent} />
            ) : partsQuery.isLoading ? (
              <div
                data-dev-id="components.select-prompt"
                className="flex h-full items-center justify-center px-6"
              >
                {/* Says what THIS pane is waiting for. It used to repeat the picker's own
                    loading line word for word, which put the same sentence on screen twice. */}
                <LoadingState dense id="components.loading">
                  Nothing is open yet. The component list is still loading.
                </LoadingState>
              </div>
            ) : (
              <ComponentWorkspaceEmpty />
            )}
          </div>
        </div>

        {searchOpen ? (
          <SearchOverlay onClose={() => setSearchOpen(false)} onOpenPart={openFromSearch} />
        ) : null}

        <ConfirmDialog
          open={confirmDelete}
          title={confirmDeleteTitle}
          body={confirmDeleteBody}
          confirmLabel={confirmDeleteLabel}
          danger
          onCancel={() => setConfirmDelete(false)}
          onConfirm={() => {
            setConfirmDelete(false);
            handleDelete();
          }}
        />
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
      <LoadingState className="mt-2" id="components.list-loading">
        Loading this library's components...
      </LoadingState>
    );
  }
  if (error) {
    const status = error instanceof ApiError ? error.status : undefined;
    return (
      <div className="mt-2">
        {status === 0 ? (
          <ErrorState id="components.list-unreachable" onRetry={onRetry}>
            Stockroom is not answering on this machine.
          </ErrorState>
        ) : status === 401 ? (
          <ErrorState id="components.list-unauthorized" onRetry={onRetry}>
            This machine is not signed in to the library.
          </ErrorState>
        ) : (
          <ErrorState id="components.list-failed" onRetry={onRetry}>
            This library's components could not be listed.
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
          <EmptyState id="components.list-no-match">
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
