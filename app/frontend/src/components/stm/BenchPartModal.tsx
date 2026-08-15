/**
 * BenchPartModal: one part of a Bench set, opened from its chip - the full pinout table for that
 * exact part (owner ask 2026-07-23: the pinout tables must be readable from the Bench too). The
 * same scrim/dialog idiom as the explorer's maximize modal; the table is the same PinoutTable the
 * explorer uses, fed by its own useStmPinout fetch for the clicked ref.
 */
import { useState } from "react";
import { useStmPinout } from "../../api/stmQueries";
import { ApiError } from "../../api/client";
import { useModalDismiss } from "../../lib/useModalDismiss";
import { ErrorState, LoadingState, ModalHeader } from "../primitives";
import { useText } from "../../lib/copy";
import { PinoutTable } from "./PinoutTable";

export function BenchPartModal({ part, onClose }: { part: string; onClose: () => void }) {
  const pinout = useStmPinout(part);
  const [selectedPosition, setSelectedPosition] = useState<string | null>(null);
  const { ref: dialogRef, zIndex: modalZ } = useModalDismiss(true, onClose);
  const dialogLabel = useText("stm.bench.dialog.aria", "Pinout for {part}", { part });
  const notBuiltLabel = useText("stm.bench.not-built", "Build the index to see this pinout.");
  const failedLabel = useText("stm.bench.failed", "Could not load this pinout.");

  return (
    <div
      style={{ zIndex: modalZ }}
      className="fixed inset-0 flex items-center justify-center bg-scrim p-6"
      data-testid="bench-part-modal"
      // role="presentation", matching the shared modal frame in components/modalParts: the scrim
      // is a surface, not a control. The press-to-dismiss is a POINTER convenience whose keyboard
      // equivalent is Escape on the top layer, which useModalDismiss already answers, so the scrim
      // must not enter the accessibility tree as a second way to close the window.
      role="presentation"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={dialogLabel}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        className="flex h-[88vh] w-full max-w-[880px] flex-col overflow-hidden rounded-card border border-line2 bg-popover shadow-pop outline-none"
      >
        <ModalHeader
          title={<span className="font-mono">{pinout.data?.mpn_example || part}</span>}
          onClose={onClose}
        >
          {pinout.data ? (
            <span className="font-mono text-xs text-t3">{pinout.data.package}</span>
          ) : null}
        </ModalHeader>
        <div className="flex min-h-0 flex-1 flex-col p-4">
          {pinout.isLoading ? (
            <LoadingState dense id="stm.bench.loading">Loading the pinout...</LoadingState>
          ) : pinout.error ? (
            <ErrorState
              dense
              id="stm.bench.failed"
              onRetry={pinout.error instanceof ApiError && pinout.error.status === 409 ? undefined : () => pinout.refetch()}
            >
              {pinout.error instanceof ApiError && pinout.error.status === 409
                ? notBuiltLabel
                : failedLabel}
            </ErrorState>
          ) : pinout.data ? (
            <PinoutTable
              pinout={pinout.data}
              selectedPosition={selectedPosition}
              onSelectPosition={setSelectedPosition}
            />
          ) : null}
        </div>
      </div>
    </div>
  );
}
