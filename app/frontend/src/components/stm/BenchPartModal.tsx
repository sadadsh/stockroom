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
import { Button } from "../primitives";
import { PinoutTable } from "./PinoutTable";

export function BenchPartModal({ part, onClose }: { part: string; onClose: () => void }) {
  const pinout = useStmPinout(part);
  const [selectedPosition, setSelectedPosition] = useState<string | null>(null);
  const dialogRef = useModalDismiss(true, onClose);

  return (
    <div
      className="fixed inset-0 z-[110] flex items-center justify-center bg-black/50 p-6"
      data-testid="bench-part-modal"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={`Pinout for ${part}`}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        className="flex h-[88vh] w-full max-w-[880px] flex-col overflow-hidden rounded-card border border-line2 bg-popover p-4 shadow-pop outline-none"
      >
        <div className="mb-3 flex flex-none items-center justify-between gap-3">
          <div className="flex items-baseline gap-2">
            <span className="font-mono text-sm font-semibold text-t1">
              {pinout.data?.mpn_example || part}
            </span>
            {pinout.data ? (
              <span className="font-mono text-xs text-t3">{pinout.data.package}</span>
            ) : null}
          </div>
          <Button type="button" small onClick={onClose}>
            Close
          </Button>
        </div>
        <div className="flex min-h-0 flex-1 flex-col">
          {pinout.isLoading ? (
            <p className="py-16 text-center text-sm text-t3">Loading the pinout...</p>
          ) : pinout.error ? (
            <p className="py-16 text-center text-sm text-err">
              {pinout.error instanceof ApiError && pinout.error.status === 409
                ? "Build the index to see this pinout."
                : "Could not load this pinout."}
            </p>
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
