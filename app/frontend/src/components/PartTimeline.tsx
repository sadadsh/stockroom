/**
 * The per-part git timeline (M6k): every commit that touched this part's record, newest
 * first. Selecting a commit shows what it changed as a structured field diff (read from
 * the git blobs, no checkout), comparing that commit against the previous version of
 * THIS part (the next-older commit in its own history, so unrelated commits never muddy
 * the diff). When the commit also moved the symbol or footprint geometry, a Visual Diff
 * opens an old/new SVG overlay. Every state degrades honestly: a part with no commits
 * yet reports an empty timeline, never a blank box.
 */
import { useState } from "react";
import { usePartDiff, usePartHistory } from "../api/queries";
import type { DiffField } from "../api/types";
import { Badge, Card } from "./primitives";
import { DiffModal } from "./DiffModal";

// A commit sha is 40 hex chars; show the familiar 7-char short form.
function shortSha(sha: string): string {
  return sha.slice(0, 7);
}

// ISO 8601 (git %aI) -> a compact local date/time; fall back to the raw string if the
// date does not parse (never show "Invalid Date").
function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatValue(v: unknown): string {
  if (v == null || v === "") return "None";
  if (Array.isArray(v)) {
    if (v.length === 0) return "None";
    return `${v.length} ${v.length === 1 ? "entry" : "entries"}`;
  }
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

const STATUS_TONE = {
  added: "ok",
  removed: "err",
  changed: "neutral",
} as const;

// Title Case status tags (the contract: interactive/label text is Title Case, never a
// bare lowercase micro-label).
const STATUS_LABEL = {
  added: "Added",
  removed: "Removed",
  changed: "Changed",
} as const;

export function PartTimeline({ partId }: { partId: string }) {
  const historyQ = usePartHistory(partId);
  // Track the selection by sha, not array index: a write to this part invalidates the
  // history and a new commit lands at the top, so an index would silently point at a
  // different commit after the refetch. A sha still resolves to the intended commit
  // (or to none, if it dropped out of the window).
  const [selectedSha, setSelectedSha] = useState<string | null>(null);
  const [diffOpen, setDiffOpen] = useState(false);

  const commits = historyQ.data?.commits ?? [];
  const selIndex = selectedSha ? commits.findIndex((c) => c.sha === selectedSha) : -1;
  const selCommit = selIndex >= 0 ? commits[selIndex] : null;
  // the previous version of THIS part is the next-older entry in its own history;
  // "" when the selection is the earliest commit (the part was created there).
  const olderSha =
    selIndex >= 0 && selIndex + 1 < commits.length ? commits[selIndex + 1].sha : "";
  const diffQ = usePartDiff(partId, olderSha, selCommit?.sha ?? null);
  const assets = diffQ.data?.assets;
  const canVisualDiff =
    !!olderSha && !!assets && (assets.symbol || assets.footprint);

  if (historyQ.isLoading) {
    return <Message>Loading history...</Message>;
  }
  if (historyQ.isError) {
    return <Message tone="err">Could not load this part's history.</Message>;
  }
  if (commits.length === 0) {
    return <Message>No history yet. This part has not been committed.</Message>;
  }

  return (
    <>
      <Card className="overflow-hidden">
        <ul>
          {commits.map((c) => {
            const active = selectedSha === c.sha;
            return (
              <li key={c.sha} className="border-b border-line last:border-b-0">
                <button
                  type="button"
                  aria-expanded={active}
                  onClick={() => setSelectedSha(active ? null : c.sha)}
                  className={
                    "flex w-full items-start gap-3 px-4 py-2.5 text-left transition-colors " +
                    (active ? "bg-inset" : "hover:bg-inset")
                  }
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm text-t1">{c.subject}</span>
                    <span className="mt-0.5 block text-xs text-t3">
                      {c.author} · {formatDate(c.iso_date)}
                    </span>
                  </span>
                  <span className="tnum flex-none pt-0.5 text-xs text-t3">
                    {shortSha(c.sha)}
                  </span>
                </button>
                {active ? (
                  <div className="border-t border-line bg-field px-4 py-3">
                    <CommitDiff
                      loading={diffQ.isLoading}
                      error={diffQ.isError}
                      fields={diffQ.data?.fields}
                      created={!olderSha}
                      canVisualDiff={canVisualDiff}
                      onVisualDiff={() => setDiffOpen(true)}
                    />
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      </Card>

      {selCommit && assets ? (
        <DiffModal
          open={diffOpen}
          partId={partId}
          partName={selCommit.subject}
          a={olderSha}
          b={selCommit.sha}
          assets={assets}
          onClose={() => setDiffOpen(false)}
        />
      ) : null}
    </>
  );
}

function CommitDiff({
  loading,
  error,
  fields,
  created,
  canVisualDiff,
  onVisualDiff,
}: {
  loading: boolean;
  error: boolean;
  fields: DiffField[] | undefined;
  created: boolean;
  canVisualDiff: boolean;
  onVisualDiff: () => void;
}) {
  if (loading) return <p className="text-xs text-t3">Loading changes...</p>;
  if (error || !fields) {
    return <p className="text-xs text-err">Could not load the changes for this commit.</p>;
  }
  return (
    <div>
      {created ? (
        <p className="mb-2 text-xs text-t2">Part created with these fields.</p>
      ) : null}
      {fields.length === 0 ? (
        <p className="text-xs text-t3">No field changes in this commit.</p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {fields.map((f) => (
            <li key={f.key} className="flex items-baseline gap-2 text-xs">
              <Badge tone={STATUS_TONE[f.status]}>{STATUS_LABEL[f.status]}</Badge>
              <span className="tnum flex-none text-t3">{f.key}</span>
              <span className="min-w-0 flex-1 break-words text-t2">
                {f.status === "added" ? (
                  <span className="text-t1">{formatValue(f.after)}</span>
                ) : f.status === "removed" ? (
                  <span className="text-t3 line-through">{formatValue(f.before)}</span>
                ) : (
                  <>
                    <span className="text-t3 line-through">{formatValue(f.before)}</span>
                    <span className="px-1 text-t3">→</span>
                    <span className="text-t1">{formatValue(f.after)}</span>
                  </>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
      {canVisualDiff ? (
        <button
          type="button"
          onClick={onVisualDiff}
          className="mt-3 rounded-control border border-line2 bg-raise px-2.5 py-1 text-xs font-medium text-t2 hover:text-t1"
        >
          View Visual Diff
        </button>
      ) : null}
    </div>
  );
}

function Message({
  children,
  tone,
}: {
  children: React.ReactNode;
  tone?: "err";
}) {
  return (
    <Card className="px-4 py-3.5">
      <span className={"text-sm " + (tone === "err" ? "text-err" : "text-t2")}>
        {children}
      </span>
    </Card>
  );
}
