/**
 * The Components page: the grouped parts list, the search + facet finder, and the
 * part detail panel, all wired to the real library API. Server state comes from
 * TanStack Query; the only local state is the search text, the active category
 * facet, the complete-only toggle, and the selected part id.
 *
 * Honest degradation: a connection error shows a retry surface (not a crash), and
 * a genuinely empty library shows an empty state that names how to add parts.
 */
import { useEffect, useMemo, useState } from "react";
import {
  usePartsQuery,
  useFacetsQuery,
  useDuplicates,
  usePartDetailQuery,
  useEditField,
  useMoveCategory,
  useDeletePart,
  useSetSpecs,
  useAttachSymbol,
  useAttachFootprint,
} from "../api/queries";
import { ApiError } from "../api/client";
import type { SourcedField } from "../api/types";
import { useToast } from "../lib/toast";
import { useAddPart } from "../lib/addPart";
import { Finder } from "../components/Finder";
import { PartsList } from "../components/PartsList";
import { DetailPanel } from "../components/DetailPanel";
import { SearchOverlay } from "../components/SearchOverlay";
import { AddPartIcon } from "../components/icons";
import { Button } from "../components/primitives";
import { Text } from "../lib/copy";

export function ComponentsPage() {
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<string | null>(null);
  const [completeOnly, setCompleteOnly] = useState(false);
  const [duplicatesOnly, setDuplicatesOnly] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);

  const partsQuery = usePartsQuery({ q: search, category, completeOnly });
  const facetsQuery = useFacetsQuery();
  const duplicatesQuery = useDuplicates();
  const detailQuery = usePartDetailQuery(selectedId);
  const editField = useEditField();
  const moveCategory = useMoveCategory();
  const deletePart = useDeletePart();
  const setSpecs = useSetSpecs();
  const attachSymbol = useAttachSymbol();
  const attachFootprint = useAttachFootprint();
  const { toast } = useToast();
  const { open: openAddPart } = useAddPart();

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
  const categories = Object.keys(facetsQuery.data?.by_category ?? {}).sort();
  const detailBusy =
    editField.isPending ||
    moveCategory.isPending ||
    deletePart.isPending ||
    setSpecs.isPending ||
    attachSymbol.isPending ||
    attachFootprint.isPending;

  function toastError(err: unknown, fallback: string) {
    toast(err instanceof ApiError ? err.message : fallback, "err");
  }

  function handleEditField(field: string, value: unknown) {
    if (!selectedId) return;
    editField.mutate(
      { id: selectedId, field, value },
      {
        onSuccess: () => toast("Saved", "ok"),
        onError: (err) => toastError(err, "Could not save"),
      },
    );
  }

  function handleMoveCategory(nextCategory: string) {
    if (!selectedId) return;
    moveCategory.mutate(
      { id: selectedId, category: nextCategory },
      {
        onSuccess: () => toast(`Moved to ${nextCategory}`, "ok"),
        onError: (err) => toastError(err, "Could not move"),
      },
    );
  }

  function handleApplyPinout(sourced: SourcedField) {
    if (!selectedId) return;
    setSpecs.mutate(
      {
        id: selectedId,
        specs: {
          pinout: {
            value: sourced.value,
            source: sourced.source,
            confidence: sourced.confidence,
          },
        },
      },
      {
        onSuccess: () => toast("Pinout saved", "ok"),
        onError: (err) => toastError(err, "Could not save the pinout"),
      },
    );
  }

  function handleAttachSymbol(lib: string, name: string) {
    if (!selectedId) return;
    attachSymbol.mutate(
      { id: selectedId, lib, name },
      {
        onSuccess: () => toast("Symbol attached", "ok"),
        onError: (err) => toastError(err, "Could not attach the symbol"),
      },
    );
  }

  function handleAttachFootprint(lib: string, name: string) {
    if (!selectedId) return;
    attachFootprint.mutate(
      { id: selectedId, lib, name },
      {
        onSuccess: () => toast("Footprint attached", "ok"),
        onError: (err) => toastError(err, "Could not attach the footprint"),
      },
    );
  }

  function handleDelete() {
    if (!selectedId) return;
    deletePart.mutate(selectedId, {
      onSuccess: () => {
        toast("Part deleted", "ok");
        // Drop the selection; the auto-select effect picks the next part once the
        // invalidated list refetches.
        setSelectedId(null);
      },
      onError: (err) => toastError(err, "Could not delete"),
    });
  }

  // Auto-select the first part when the current selection falls out of the list
  // (a new search, a category change, or the first successful load). Act only on
  // SETTLED data: while a refetch is in flight TanStack retains the previous
  // list, so re-selecting parts[0] here would re-pick a just-deleted or
  // filtered-out part and fire a wasted, guaranteed-404 detail request.
  const partsFetching = partsQuery.isFetching;
  useEffect(() => {
    if (partsFetching) return;
    if (parts.length === 0) {
      if (selectedId !== null) setSelectedId(null);
      return;
    }
    if (!selectedId || !parts.some((p) => p.id === selectedId)) {
      setSelectedId(parts[0].id);
    }
  }, [parts, selectedId, partsFetching]);

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
  // narrowing filters so the row is present in the list, select it, and close the overlay.
  function openFromSearch(id: string, cat: string) {
    setCategory(cat);
    setCompleteOnly(false);
    setDuplicatesOnly(false);
    setSearch("");
    setSelectedId(id);
    setSearchOpen(false);
  }

  const selectedSummary = parts.find((p) => p.id === selectedId) ?? null;

  // north-star .app: rail | list | detail, each column self-heading - no full-width page
  // header band (the active rail item + the rail's library readout carry that).
  return (
    <div data-dev-id="components.root" className="flex min-h-0 flex-1">
        {/* picker */}
        <div data-dev-id="components.picker" className="flex w-[320px] flex-none flex-col px-3.5 pt-4">
          <div className="px-2 pt-2">
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
          <div data-dev-id="components.list-scroll" className="mt-2 min-h-0 flex-1 overflow-y-auto px-2 pb-3">
            <PickerBody
              isLoading={partsQuery.isLoading}
              error={partsQuery.error}
              parts={parts}
              duplicateIds={duplicateIds}
              selectedId={selectedId}
              onSelect={setSelectedId}
              onRetry={() => partsQuery.refetch()}
              hasSearchOrFilter={!!search || !!category || completeOnly || duplicatesOnly}
              onClearFilters={() => {
                setSearch("");
                setCategory(null);
                setCompleteOnly(false);
                setDuplicatesOnly(false);
              }}
            />
          </div>
        </div>

        {/* detail: the panel owns its own height, padding, and internal scroll (a fixed
            rail + a tabbed workbench), so this column is a non-scrolling viewport. */}
        <div data-dev-id="components.detail-pane" className="min-h-0 min-w-0 flex-1 overflow-hidden border-l border-line">
          {selectedId ? (
            <DetailPanel
              detail={detailQuery.data}
              isLoading={detailQuery.isLoading}
              error={detailQuery.error}
              missing={selectedSummary?.missing ?? []}
              isComplete={selectedSummary?.is_complete ?? false}
              onEditField={handleEditField}
              onMoveCategory={handleMoveCategory}
              categories={categories}
              onDelete={handleDelete}
              onApplyPinout={handleApplyPinout}
              onAttachSymbol={handleAttachSymbol}
              onAttachFootprint={handleAttachFootprint}
              busy={detailBusy}
            />
          ) : (
            <div data-dev-id="components.select-prompt" className="flex h-full min-h-[300px] items-center justify-center text-sm text-t3">
              {partsQuery.isLoading ? (
                <Text id="components.loading">Loading components...</Text>
              ) : (
                <Text id="components.select-prompt">Select a part to see its details.</Text>
              )}
            </div>
          )}
        </div>

        {searchOpen ? (
          <SearchOverlay onClose={() => setSearchOpen(false)} onOpenPart={openFromSearch} />
        ) : null}
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
  onRetry: () => void;
  hasSearchOrFilter: boolean;
  onClearFilters: () => void;
}) {
  if (isLoading) {
    return (
      <div className="px-3 py-8 text-center text-sm text-t3">
        Loading parts...
      </div>
    );
  }
  if (error) {
    const status = error instanceof ApiError ? error.status : undefined;
    const message =
      status === 0
        ? "Cannot reach the Stockroom server."
        : status === 401
          ? "Not authorized. The API token is missing or invalid."
          : error.message;
    return (
      <div className="flex flex-col items-center gap-3 px-3 py-8 text-center">
        <div className="text-sm text-err">{message}</div>
        <Button small onClick={onRetry}>
          Try Again
        </Button>
      </div>
    );
  }
  if (parts.length === 0) {
    // An honest empty state: distinguish "no matches for this filter" from
    // "the library itself is empty".
    if (hasSearchOrFilter) {
      return (
        <div className="flex flex-col items-center gap-3 px-3 py-8 text-center">
          <div className="text-sm text-t3">
            No parts match the current search or filter.
          </div>
          <Button small onClick={onClearFilters}>
            Clear Filters
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
    />
  );
}
