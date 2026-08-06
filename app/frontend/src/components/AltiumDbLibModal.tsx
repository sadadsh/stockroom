/**
 * Read-only Altium Database Library viewer for the active profile.
 *
 * CAD acquisition belongs to the network collection workflow, which activates one verified
 * KiCad/Altium pair atomically. This surface therefore reports DbLib readiness without exposing
 * a second local-file or Altium-only activation lane.
 */
import { useMemo, useState } from "react";
import * as m from "motion/react-m";
import { useAltiumStatus } from "../api/queries";
import { useModalDismiss } from "../lib/useModalDismiss";
import { Badge, Dot, SegmentedControl } from "./primitives";
import { Icon } from "./Icon";
import { Text, useText } from "../lib/copy";

type Filter = "all" | "ready" | "needs";

const TH =
  "sticky top-0 z-[1] whitespace-nowrap border-b border-line bg-raise px-3 py-2.5 text-left " +
  "ui-property-label";
const TD = "whitespace-nowrap px-3 py-2.5 text-sm";

export function AltiumDbLibModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const status = useAltiumStatus();
  const [filter, setFilter] = useState<Filter>("all");
  // Escape + Tab focus-trap + focus-restore (the shared modal idiom); attach the ref to the dialog.
  const { ref: dialogRef, zIndex: modalZ } = useModalDismiss(open, onClose);

  // The empty fallback was a fresh `[]` on every render, so the two memos below re-ran on every
  // render they existed to skip - and the whole catalog was re-filtered whenever anything else on
  // this dialog changed. Memoised here, the row list keeps one identity per response.
  const rows = useMemo(() => status.data?.rows ?? [], [status.data]);
  const readyCount = useMemo(() => rows.filter((r) => r.ready).length, [rows]);
  const shown = useMemo(
    () => rows.filter((r) => (filter === "all" ? true : filter === "ready" ? r.ready : !r.ready)),
    [rows, filter],
  );
  // Copy layer: the filter words carry a live count, so only the word is overridable while the count
  // stays dynamic; the accessible strings resolve here because attributes cannot host <Text>.
  const filterAll = useText("modal.altium.filter-all", "All");
  const filterReady = useText("modal.altium.filter-ready", "Prepared");
  const filterNeeds = useText("modal.altium.filter-needs", "Needs Files");
  const dialogLabel = useText("modal.altium.title", "Altium Database Catalog");
  const closeLabel = useText("modal.altium.close", "Close");
  const filterLabel = useText("modal.altium.filter", "Filter parts");

  if (!open) return null;

  return (
    <div
      style={{ zIndex: modalZ }}
      className="fixed inset-0 flex items-start justify-center bg-black/60 p-4 pt-[7vh]"
      // role="presentation", matching the shared modal frame in components/modalParts: the scrim
      // is a surface, not a control. The press-to-dismiss below is a POINTER convenience whose
      // keyboard equivalent is Escape on the top layer, which useModalDismiss already answers, so
      // the scrim must not enter the accessibility tree as a second way to close the window.
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <m.div
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
              <Text id="modal.altium.title">Altium Database Catalog</Text>
            </h2>
            <span className="text-xs text-t3">
              {readyCount} of {rows.length} mapped
              {status.data ? ` · Library ${status.data.profile}` : ""}
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

        <div className="flex items-center px-5 py-3" data-dev-id="altiumdb.modal-filter">
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
        </div>

        <div className="min-h-0 flex-1 overflow-auto px-5 pb-5">
          {status.isLoading ? (
            <p className="py-6 text-center text-sm text-t3">
              <Text id="modal.altium.loading">Reading the catalog...</Text>
            </p>
          ) : status.isError ? (
            <p className="py-6 text-center text-sm text-err-text">
              <Text id="modal.altium.error">Could not read the Altium catalog.</Text>
            </p>
          ) : shown.length === 0 ? (
            <div className="flex items-center justify-center gap-2.5 py-10">
              <Dot tone="neutral" />
              <span className="text-sm text-t3">
                {rows.length === 0 ? (
                  <Text id="modal.altium.empty-no-parts">This catalog holds no parts so far.</Text>
                ) : filter === "ready" ? (
                  <Text id="modal.altium.empty-none-ready">No parts can be placed so far. Collect the complete source set from Components.</Text>
                ) : (
                  <Text id="modal.altium.empty-all-ready">Each part has its Altium assets.</Text>
                )}
              </span>
            </div>
          ) : (
            <table className="w-full table-fixed border-collapse" data-dev-id="altiumdb.modal-table">
              <thead>
                <tr>
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
                </tr>
              </thead>
              <tbody>
                {shown.map((row) => (
                  <tr key={row.id} className="border-b border-line last:border-b-0 hover:bg-raise2">
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
                            <Text id="modal.altium.status-ready">Prepared</Text>
                          </span>
                        </span>
                      ) : (
                        <Badge tone="warn" size="sm">
                          <Text id="modal.altium.status-needs">Needs Files</Text>
                        </Badge>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </m.div>
    </div>
  );
}
