/**
 * The Components page: the grouped parts list, the search + facet finder, and the
 * part detail panel, all wired to the real library API. Server state comes from
 * TanStack Query; the only local state is the search text, the active category
 * facet, the complete-only toggle, and the selected part id.
 *
 * Honest degradation: a connection error shows a retry surface (not a crash), and
 * a genuinely empty library shows an empty state that names how to add parts.
 */
import { useEffect, useState } from "react";
import {
  usePartsQuery,
  useFacetsQuery,
  usePartDetailQuery,
  useEditField,
  useMoveCategory,
  useDeletePart,
} from "../api/queries";
import { ApiError } from "../api/client";
import { useToast } from "../lib/toast";
import { Finder } from "../components/Finder";
import { PartsList } from "../components/PartsList";
import { DetailPanel } from "../components/DetailPanel";
import { UploadIcon } from "../components/icons";
import { Button } from "../components/primitives";

export function ComponentsPage() {
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<string | null>(null);
  const [completeOnly, setCompleteOnly] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const partsQuery = usePartsQuery({ q: search, category, completeOnly });
  const facetsQuery = useFacetsQuery();
  const detailQuery = usePartDetailQuery(selectedId);
  const editField = useEditField();
  const moveCategory = useMoveCategory();
  const deletePart = useDeletePart();
  const { toast } = useToast();

  const parts = partsQuery.data?.parts ?? [];
  const categories = Object.keys(facetsQuery.data?.by_category ?? {}).sort();
  const detailBusy =
    editField.isPending || moveCategory.isPending || deletePart.isPending;

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
        onSuccess: () => toast(`Moved To ${nextCategory}`, "ok"),
        onError: (err) => toastError(err, "Could not move"),
      },
    );
  }

  function handleDelete() {
    if (!selectedId) return;
    deletePart.mutate(selectedId, {
      onSuccess: () => {
        toast("Part Deleted", "ok");
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

  const selectedSummary = parts.find((p) => p.id === selectedId) ?? null;

  return (
    <>
      <div className="flex h-14 flex-none items-center px-[18px]">
        <div className="text-lg font-semibold text-t1">Components</div>
        <div className="ml-auto text-2xs text-t3">
          {partsQuery.data ? `${partsQuery.data.count} Parts` : ""}
        </div>
      </div>

      <div className="flex min-h-0 flex-1">
        {/* picker */}
        <div className="flex w-[348px] flex-none flex-col px-3.5 pt-1.5">
          <div className="px-2 pt-2">
            <Finder
              search={search}
              onSearch={setSearch}
              facets={facetsQuery.data}
              category={category}
              onCategory={setCategory}
              completeOnly={completeOnly}
              onCompleteOnly={setCompleteOnly}
            />
          </div>
          <div className="mt-2 min-h-0 flex-1 overflow-y-auto px-2 pb-3">
            <PickerBody
              isLoading={partsQuery.isLoading}
              error={partsQuery.error}
              parts={parts}
              selectedId={selectedId}
              onSelect={setSelectedId}
              onRetry={() => partsQuery.refetch()}
              hasSearchOrFilter={!!search || !!category || completeOnly}
              onClearFilters={() => {
                setSearch("");
                setCategory(null);
                setCompleteOnly(false);
              }}
            />
          </div>
        </div>

        {/* detail */}
        <div className="min-w-0 flex-1 overflow-y-auto border-l border-line px-[30px] pt-[22px]">
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
              busy={detailBusy}
            />
          ) : (
            <div className="flex h-full min-h-[300px] items-center justify-center text-sm text-t3">
              {partsQuery.isLoading
                ? "Loading Library..."
                : "Select A Part To See Its Details."}
            </div>
          )}
        </div>
      </div>
    </>
  );
}

function PickerBody({
  isLoading,
  error,
  parts,
  selectedId,
  onSelect,
  onRetry,
  hasSearchOrFilter,
  onClearFilters,
}: {
  isLoading: boolean;
  error: Error | null;
  parts: import("../api/types").PartSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onRetry: () => void;
  hasSearchOrFilter: boolean;
  onClearFilters: () => void;
}) {
  if (isLoading) {
    return (
      <div className="px-3 py-8 text-center text-sm text-t3">
        Loading Parts...
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
      <div className="flex flex-col items-center gap-2.5 px-4 py-10 text-center">
        <span className="text-t3">
          <UploadIcon />
        </span>
        <div className="text-sm font-medium text-t2">
          Your Library Is Empty
        </div>
        <div className="text-xs text-t3">
          Drop a vendor ZIP to add your first part.
        </div>
      </div>
    );
  }
  return <PartsList parts={parts} selectedId={selectedId} onSelect={onSelect} />;
}
