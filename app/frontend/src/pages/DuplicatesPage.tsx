/**
 * Duplicates (M6e). Two honest surfaces over GET /api/duplicates:
 *  - Same Part Number: parts recorded under one MPN. Almost always a real
 *    accidental duplicate, so the most-complete member is marked Keep and the
 *    rest can be deleted through the existing atomic delete.
 *  - Shared Footprint: parts that use one footprint name. Sharing a standard
 *    footprint (R_0402, SOT-23) is normal, so this half is framed as a review,
 *    not a delete prompt.
 * Delete resolves in-window (a scrim-and-card confirm, never an OS dialog) and
 * invalidates the parts list, facets, and this surface so it refreshes itself.
 */
import { useState } from "react";
import { ApiError } from "../api/client";
import { useDeletePart, useDuplicates } from "../api/queries";
import type { DuplicateGroup, PartSummary } from "../api/types";
import { useToast } from "../lib/toast";
import { Badge, Card, Eyebrow } from "../components/primitives";
import { ConfirmDialog } from "../components/ConfirmDialog";

function errMsg(err: unknown): string {
  return err instanceof ApiError ? err.message : "Something went wrong.";
}

export function DuplicatesPage() {
  const dups = useDuplicates();
  const del = useDeletePart();
  const { toast } = useToast();
  const [pending, setPending] = useState<PartSummary | null>(null);

  function onConfirmDelete() {
    const part = pending;
    if (!part) return;
    del.mutate(part.id, {
      onSuccess: () => {
        setPending(null);
        toast(`Deleted ${part.display_name}.`, "ok");
      },
      onError: (e) => {
        setPending(null);
        toast(errMsg(e), "err");
      },
    });
  }

  return (
    <>
      <div className="flex h-14 flex-none items-center px-[18px]">
        <div className="text-lg font-semibold text-t1">Duplicates</div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-[30px] pt-[22px]">
        <div className="max-w-[880px] pb-12">
          {dups.isLoading ? (
            <p className="py-1 text-sm text-t3">Scanning the library for duplicates...</p>
          ) : dups.isError ? (
            <p className="py-1 text-sm text-err">Could not load duplicates.</p>
          ) : dups.data ? (
            <>
              <DupSection
                title="Same Part Number"
                hint="These parts are recorded under the same MPN. That is usually the same part added twice: keep the most complete one and delete the rest."
                groups={dups.data.by_mpn}
                emptyLabel="No parts share an MPN."
                onDelete={setPending}
              />
              <DupSection
                title="Shared Footprint"
                hint="These parts use the same footprint name. Sharing a standard footprint is normal; review only if the same footprint was imported more than once."
                groups={dups.data.by_footprint}
                emptyLabel="No parts share a footprint."
                onDelete={setPending}
              />
            </>
          ) : null}
        </div>
      </div>

      <ConfirmDialog
        open={pending !== null}
        title="Delete Part"
        body={
          <>
            Delete <b>{pending?.display_name}</b> from the library? Its symbol,
            footprint and files are removed and the change is committed.
          </>
        }
        confirmLabel="Delete"
        danger
        busy={del.isPending}
        onConfirm={onConfirmDelete}
        onCancel={() => setPending(null)}
      />
    </>
  );
}

function DupSection({
  title,
  hint,
  groups,
  emptyLabel,
  onDelete,
}: {
  title: string;
  hint: string;
  groups: DuplicateGroup[];
  emptyLabel: string;
  onDelete: (part: PartSummary) => void;
}) {
  return (
    <section className="mb-8">
      <Eyebrow className="mb-1">{title}</Eyebrow>
      <p className="mb-3 text-xs text-t3">{hint}</p>
      {groups.length === 0 ? (
        <p className="py-1 text-sm text-t2">{emptyLabel}</p>
      ) : (
        <div className="flex flex-col gap-3">
          {groups.map((group) => (
            <GroupCard key={group.key} group={group} onDelete={onDelete} />
          ))}
        </div>
      )}
    </section>
  );
}

function GroupCard({
  group,
  onDelete,
}: {
  group: DuplicateGroup;
  onDelete: (part: PartSummary) => void;
}) {
  return (
    <Card className="px-4 py-3.5">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <span className="min-w-0 truncate font-mono text-sm text-t1">{group.key}</span>
        <span className="flex-none text-xs text-t3">{group.parts.length} parts</span>
      </div>
      <div className="grid gap-2.5 sm:grid-cols-2">
        {group.parts.map((part, i) => (
          <PartCompareCard
            key={part.id}
            part={part}
            keepCandidate={i === 0}
            onDelete={onDelete}
          />
        ))}
      </div>
    </Card>
  );
}

function PartCompareCard({
  part,
  keepCandidate,
  onDelete,
}: {
  part: PartSummary;
  keepCandidate: boolean;
  onDelete: (part: PartSummary) => void;
}) {
  return (
    <div
      data-testid={`dup-part-${part.id}`}
      className="flex flex-col gap-2 rounded-control border border-line bg-raise2 p-3"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium text-t1">{part.display_name}</div>
          <div className="truncate text-xs text-t3">
            {[part.category, part.manufacturer].filter(Boolean).join(" · ")}
          </div>
        </div>
        {keepCandidate ? (
          <Badge tone="neutral" title="The most complete member: keep this one">
            Keep
          </Badge>
        ) : null}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {part.is_complete ? (
          <Badge tone="ok">Complete</Badge>
        ) : (
          <Badge tone="warn">Incomplete</Badge>
        )}
        <button
          type="button"
          onClick={() => onDelete(part)}
          className="ml-auto rounded-control border border-line px-2.5 py-1 text-xs text-err transition-colors hover:bg-err hover:text-white"
        >
          Delete
        </button>
      </div>
      {!part.is_complete && part.missing.length > 0 ? (
        <div className="text-xs text-t3">Missing: {part.missing.join(", ")}</div>
      ) : null}
    </div>
  );
}
