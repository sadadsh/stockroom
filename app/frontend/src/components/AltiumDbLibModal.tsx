/**
 * The Altium Database Library viewer: an in-window modal (the app's scrim idiom) over the active
 * profile's parts. Each row shows what the DbLib maps for that part, and a not-ready row carries
 * an Attach action that opens the host file picker for its .SchLib/.PcbLib (or .IntLib), attaches
 * them, and regenerates so it lands in the library immediately.
 */
import { useEffect, useMemo, useState } from "react";
import { motion } from "motion/react";
import { useAltiumAttach, useAltiumRegenerate, useAltiumStatus } from "../api/queries";
import type { AltiumStatusRow } from "../api/types";
import { matchAltiumFilesToParts } from "../lib/altiumBulk";
import { useModalDismiss } from "../lib/useModalDismiss";
import { useToast } from "../lib/toast";
import { Badge, Button, Dot, SegmentedControl } from "./primitives";
import { Icon } from "./Icon";
import { Text, useText } from "../lib/copy";

type Filter = "all" | "ready" | "needs";

const TH =
  "sticky top-0 z-[1] whitespace-nowrap border-b border-line bg-raise px-3 py-2.5 text-left " +
  "text-2xs font-bold uppercase tracking-[0.06em] text-t3";
const TD = "whitespace-nowrap px-3 py-2.5 text-sm";

function pickAltiumFiles(): Promise<string[]> | null {
  const hostApi = (
    window as unknown as {
      pywebview?: { api?: { pick_altium_files?: () => Promise<string[]> } };
    }
  ).pywebview?.api;
  return hostApi?.pick_altium_files ? hostApi.pick_altium_files() : null;
}

export function AltiumDbLibModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const status = useAltiumStatus();
  const attach = useAltiumAttach();
  const regenerate = useAltiumRegenerate();
  const { toast } = useToast();
  const [filter, setFilter] = useState<Filter>("all");
  const [attachingId, setAttachingId] = useState<string | null>(null);
  // The bulk selection over needs-files rows (by id), plus a lock for the multi-step bulk flow.
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  // Escape + Tab focus-trap + focus-restore (the shared modal idiom); attach the ref to the dialog.
  const dialogRef = useModalDismiss(open, onClose);
  // Any in-flight write serializes the surface: a second attach or a regenerate can collide with the
  // backend's single git repo, so no Attach is offered while one is running (the backend also locks).
  const busy = attach.isPending || regenerate.isPending || bulkBusy;

  const rows = status.data?.rows ?? [];
  const readyCount = useMemo(() => rows.filter((r) => r.ready).length, [rows]);
  const shown = useMemo(
    () => rows.filter((r) => (filter === "all" ? true : filter === "ready" ? r.ready : !r.ready)),
    [rows, filter],
  );
  // The selectable rows (only a not-ready row can be attached); the header select-all + the count
  // are scoped to what is currently shown.
  const needsShown = useMemo(() => shown.filter((r) => !r.ready), [shown]);
  const selectedCount = useMemo(
    () => needsShown.filter((r) => selected.has(r.id)).length,
    [needsShown, selected],
  );
  const allSelected = needsShown.length > 0 && selectedCount === needsShown.length;

  // Drop any selection that is no longer a shown needs-files row (a filter change or a completed
  // attach), so the selection never references a stale/ready part.
  useEffect(() => {
    const valid = new Set(needsShown.map((r) => r.id));
    setSelected((prev) => {
      const next = new Set([...prev].filter((id) => valid.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [needsShown]);

  function toggleRow(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    setSelected(allSelected ? new Set() : new Set(needsShown.map((r) => r.id)));
  }

  // Copy layer: the filter words carry a live count, so only the word is overridable while the count
  // stays dynamic; the aria strings and the two toast strings resolve here so onAttach and the a11y
  // names fire the override, not the literal.
  const filterAll = useText("modal.altium.filter-all", "All");
  const filterReady = useText("modal.altium.filter-ready", "Ready");
  const filterNeeds = useText("modal.altium.filter-needs", "Needs Files");
  const dialogLabel = useText("modal.altium.title", "Altium Database Library");
  const closeLabel = useText("modal.altium.close", "Close");
  const filterLabel = useText("modal.altium.filter", "Filter parts");
  const attachColLabel = useText("modal.altium.attach-col", "Attach");
  const toastNoHost = useText(
    "modal.altium.toast-no-host",
    "Open Stockroom as the app to attach files. A web browser cannot read file paths.",
  );
  const toastPickerFailed = useText("modal.altium.toast-picker-failed", "Could not open the file picker.");

  async function onAttach(row: AltiumStatusRow) {
    const picker = pickAltiumFiles();
    if (!picker) {
      toast(toastNoHost, "neutral");
      return;
    }
    let paths: string[];
    try {
      paths = await picker;
    } catch {
      toast(toastPickerFailed, "err");
      return;
    }
    if (!paths.length) return; // cancelled
    setAttachingId(row.id);
    try {
      // Attach and regenerate are distinct steps: if the attach itself fails, the part is
      // untouched; if only the follow-on regenerate fails, the part IS attached (now Ready) and
      // just needs a Regenerate, so the two must report differently (never "could not attach"
      // for a part that actually attached).
      try {
        await attach.mutateAsync({ id: row.id, paths });
      } catch (err) {
        toast(err instanceof Error ? err.message : "Could not attach the files.", "err");
        return;
      }
      try {
        await regenerate.mutateAsync();
        toast(`Attached ${row.display_name} and added it to the DbLib.`, "ok");
      } catch {
        toast(
          `Attached ${row.display_name}, but the DbLib did not regenerate. Click Regenerate DbLib to finish.`,
          "neutral",
        );
      }
    } finally {
      setAttachingId(null);
    }
  }

  // Bulk attach: ONE file picker for the whole selection, mapped to parts by MPN, each match
  // attached through the existing per-part endpoint (serialized), then the DbLib regenerated ONCE.
  // The result is reported honestly: no part is silently skipped, mis-bound, or fabricated.
  async function onAttachSelected() {
    const targets = needsShown.filter((r) => selected.has(r.id));
    if (!targets.length) return;
    const picker = pickAltiumFiles();
    if (!picker) {
      toast("Open Stockroom as the app to attach files. A web browser cannot read file paths.", "neutral");
      return;
    }
    let paths: string[];
    try {
      paths = await picker;
    } catch {
      toast("Could not open the file picker.", "err");
      return;
    }
    if (!paths.length) return; // cancelled
    const plan = matchAltiumFilesToParts(targets, paths);
    if (!plan.matched.length) {
      toast(
        `No picked files matched the ${targets.length} selected part${targets.length === 1 ? "" : "s"} by MPN.`,
        "neutral",
      );
      return;
    }
    setBulkBusy(true);
    let attached = 0;
    const failed: string[] = [];
    try {
      for (const match of plan.matched) {
        setAttachingId(match.row.id);
        try {
          await attach.mutateAsync({ id: match.row.id, paths: match.paths });
          attached += 1;
        } catch {
          failed.push(match.row.display_name);
        }
      }
      setAttachingId(null);
      let regenOk = true;
      if (attached > 0) {
        try {
          await regenerate.mutateAsync();
        } catch {
          regenOk = false;
        }
      }
      const pieces = [`Attached ${attached} part${attached === 1 ? "" : "s"}`];
      if (plan.unmatched.length) pieces.push(`${plan.unmatched.length} had no matching file`);
      if (failed.length) pieces.push(`${failed.length} failed`);
      let message = `${pieces.join("; ")}.`;
      if (attached > 0 && !regenOk)
        message += " The DbLib did not regenerate; click Regenerate DbLib to finish.";
      toast(message, failed.length ? "err" : plan.unmatched.length ? "neutral" : "ok");
      setSelected(new Set());
    } finally {
      setBulkBusy(false);
      setAttachingId(null);
    }
  }

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[95] flex items-start justify-center bg-black/60 p-4 pt-[7vh]"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <motion.div
        ref={dialogRef}
        tabIndex={-1}
        initial={{ opacity: 0, y: 8, scale: 0.99 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ type: "spring", stiffness: 420, damping: 32 }}
        role="dialog"
        aria-modal="true"
        aria-label={dialogLabel}
        data-dev-id="altiumdb.modal"
        className="flex max-h-[86vh] w-full max-w-[960px] flex-col overflow-hidden rounded-card border border-line bg-raise shadow-raise focus:outline-none"
      >
        <div className="flex h-[38px] flex-none items-center justify-between gap-4 border-b border-line bg-band px-4">
          <div className="flex items-baseline gap-2.5">
            <h2 className="text-sm font-semibold text-t1">
              <Text id="modal.altium.title">Altium Database Library</Text>
            </h2>
            <span className="text-xs text-t3">
              {readyCount} of {rows.length} mapped
              {status.data ? ` · ${status.data.profile}` : ""}
            </span>
          </div>
          <button
            type="button"
            aria-label={closeLabel}
            onClick={onClose}
            className="flex h-[26px] w-[26px] flex-none items-center justify-center rounded-control text-t3 hover:bg-raise2 hover:text-t1"
          >
            <Icon id="action.close" className="h-4 w-4" />
          </button>
        </div>

        <div className="flex items-center justify-between gap-4 px-5 py-3" data-dev-id="altiumdb.modal-filter">
          <SegmentedControl<Filter>
            aria-label={filterLabel}
            value={filter}
            onChange={setFilter}
            size="small"
            options={[
              { id: "all", label: `${filterAll} (${rows.length})` },
              { id: "ready", label: `${filterReady} (${readyCount})` },
              { id: "needs", label: `${filterNeeds} (${rows.length - readyCount})` },
            ]}
          />
          {selectedCount > 0 ? (
            <div className="flex items-center gap-2.5">
              <span className="text-xs text-t3">{selectedCount} selected</span>
              <Button
                small
                variant="soft"
                onClick={onAttachSelected}
                disabled={busy}
                icon={<Icon id="action.upload" className="h-3.5 w-3.5" />}
              >
                {bulkBusy ? "Attaching..." : "Attach Selected"}
              </Button>
            </div>
          ) : null}
        </div>

        <div className="min-h-0 flex-1 overflow-auto px-5 pb-5">
          {status.isLoading ? (
            <p className="py-6 text-center text-sm text-t3">
              <Text id="modal.altium.loading">Reading the library...</Text>
            </p>
          ) : status.isError ? (
            <p className="py-6 text-center text-sm text-err">
              <Text id="modal.altium.error">Could not read the Altium library.</Text>
            </p>
          ) : shown.length === 0 ? (
            <div className="flex items-center justify-center gap-2.5 py-10">
              <Dot tone="neutral" />
              <span className="text-sm text-t3">
                {rows.length === 0 ? (
                  <Text id="modal.altium.empty-no-parts">This profile has no parts yet.</Text>
                ) : filter === "ready" ? (
                  <Text id="modal.altium.empty-none-ready">
                    No parts are ready to place yet. Attach a part's Altium assets to get started.
                  </Text>
                ) : (
                  <Text id="modal.altium.empty-all-ready">Every part has its Altium assets.</Text>
                )}
              </span>
            </div>
          ) : (
            <table className="w-full table-fixed border-collapse" data-dev-id="altiumdb.modal-table">
              <thead>
                <tr>
                  <th className={`${TH} w-[40px]`}>
                    <input
                      type="checkbox"
                      aria-label="Select All"
                      checked={allSelected}
                      ref={(el) => {
                        if (el) el.indeterminate = selectedCount > 0 && !allSelected;
                      }}
                      onChange={toggleAll}
                      disabled={busy || needsShown.length === 0}
                      className="h-4 w-4 cursor-pointer rounded-[4px] accent-[var(--c-acc)] disabled:cursor-not-allowed disabled:opacity-50"
                    />
                  </th>
                  <th className={TH}>
                    <Text id="modal.altium.th-part">Part</Text>
                  </th>
                  <th className={`${TH} w-[164px]`}>
                    <Text id="modal.altium.th-mpn">MPN</Text>
                  </th>
                  <th className={`${TH} w-[76px]`}>
                    <Text id="modal.altium.th-value">Value</Text>
                  </th>
                  <th className={`${TH} w-[108px]`}>
                    <Text id="modal.altium.th-symbol">Symbol</Text>
                  </th>
                  <th className={`${TH} w-[120px]`}>
                    <Text id="modal.altium.th-footprint">Footprint</Text>
                  </th>
                  <th className={`${TH} w-[104px]`}>
                    <Text id="modal.altium.th-status">Status</Text>
                  </th>
                  <th className={`${TH} w-[132px]`} aria-label={attachColLabel} />
                </tr>
              </thead>
              <tbody>
                {shown.map((row) => (
                  <tr key={row.id} className="border-b border-line last:border-b-0 hover:bg-raise2">
                    <td className={TD}>
                      {row.ready ? null : (
                        <input
                          type="checkbox"
                          aria-label={`Select ${row.display_name}`}
                          checked={selected.has(row.id)}
                          onChange={() => toggleRow(row.id)}
                          disabled={busy}
                          className="h-4 w-4 cursor-pointer rounded-[4px] accent-[var(--c-acc)] disabled:cursor-not-allowed disabled:opacity-50"
                        />
                      )}
                    </td>
                    <td className={`${TD} truncate text-t2`} title={row.display_name}>
                      {row.display_name}
                    </td>
                    <td className={`${TD} truncate font-mono text-t1`} title={row.mpn}>
                      {row.mpn || "—"}
                    </td>
                    <td className={`${TD} truncate font-mono text-t2`}>{row.value || "—"}</td>
                    <td className={`${TD} truncate font-mono text-t3`} title={row.symbol}>
                      {row.symbol || "—"}
                    </td>
                    <td className={`${TD} truncate font-mono text-t3`} title={row.footprint}>
                      {row.footprint || "—"}
                    </td>
                    <td className={`${TD} whitespace-nowrap`}>
                      {row.ready ? (
                        <span className="inline-flex items-center gap-1.5">
                          <Dot tone="ok" />
                          <span className="text-t2">
                            <Text id="modal.altium.status-ready">Ready</Text>
                          </span>
                        </span>
                      ) : (
                        <Badge tone="warn" size="sm">
                          <Text id="modal.altium.status-needs">Needs Files</Text>
                        </Badge>
                      )}
                    </td>
                    <td className={`${TD} whitespace-nowrap text-right`}>
                      {row.ready ? null : (
                        <Button
                          small
                          onClick={() => onAttach(row)}
                          disabled={busy}
                          icon={<Icon id="action.upload" className="h-3.5 w-3.5" />}
                          data-dev-id="altiumdb.modal-attach"
                        >
                          {attachingId === row.id ? (
                            <Text id="modal.altium.attaching">Attaching...</Text>
                          ) : (
                            <Text id="modal.altium.attach-files">Attach Files</Text>
                          )}
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </motion.div>
    </div>
  );
}
