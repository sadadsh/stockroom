/**
 * The old/new geometry diff modal (M6k) — the same in-window scrim idiom as the preview
 * modal, no OS window. It renders the part's symbol/footprint SVG as of two revisions
 * (fetched with ?rev, so the historical blob is drawn, never the working tree) and
 * cross-fades them in one shared pan/zoom viewport. Only the asset kinds that actually
 * changed between the two revisions get a tab; a kind is never shown if it did not move.
 */
import { useState } from "react";
import type { DiffAssets } from "../api/types";
import { usePreviewSvg } from "../api/queries";
import { useModalDismiss } from "../lib/useModalDismiss";
import { SvgDiffViewport } from "./SvgDiffViewport";

type DiffKind = "symbol" | "footprint";
const KIND_LABEL: Record<DiffKind, string> = { symbol: "Symbol", footprint: "Footprint" };

interface Props {
  open: boolean;
  partId: string;
  partName: string;
  a: string; // the older revision
  b: string; // the newer revision
  assets: DiffAssets;
  onClose: () => void;
}

export function DiffModal({ open, partId, partName, a, b, assets, onClose }: Props) {
  const changed = (["symbol", "footprint"] as const).filter((k) => assets[k]);
  const [kind, setKind] = useState<DiffKind>(changed[0] ?? "symbol");
  const dialogRef = useModalDismiss(open, onClose);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[110] flex items-center justify-center bg-black/50 p-4"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={`Visual Diff for ${partName}`}
        tabIndex={-1}
        className="flex h-[80vh] max-h-[680px] w-full max-w-[860px] flex-col overflow-hidden rounded-card border border-line2 bg-popover shadow-pop outline-none"
      >
        <div className="flex items-center gap-3 border-b border-line px-4 py-3">
          <span className="min-w-0 flex-none truncate text-sm font-semibold text-t1">
            {partName}
          </span>
          {changed.length > 1 ? (
            <div className="flex gap-1" role="tablist" aria-label="Diff Type">
              {changed.map((k) => {
                const active = kind === k;
                return (
                  <button
                    key={k}
                    type="button"
                    role="tab"
                    aria-selected={active}
                    onClick={() => setKind(k)}
                    className={
                      "rounded-control px-2.5 py-1 text-xs font-medium transition-colors " +
                      (active
                        ? "bg-raise2 text-t1"
                        : "text-t2 hover:bg-raise hover:text-t1")
                    }
                  >
                    {KIND_LABEL[k]}
                  </button>
                );
              })}
            </div>
          ) : (
            <span className="text-xs text-t3">{KIND_LABEL[changed[0] ?? "symbol"]}</span>
          )}
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="ml-auto flex-none rounded-control border border-line2 bg-raise px-2.5 py-1 text-xs font-medium text-t2 hover:text-t1"
          >
            Close
          </button>
        </div>

        <div className="relative flex-1 bg-field">
          <DiffBody kind={kind} partId={partId} a={a} b={b} />
        </div>
      </div>
    </div>
  );
}

function DiffBody({
  kind,
  partId,
  a,
  b,
}: {
  kind: DiffKind;
  partId: string;
  a: string;
  b: string;
}) {
  const beforeQ = usePreviewSvg(kind, partId, { rev: a });
  const afterQ = usePreviewSvg(kind, partId, { rev: b });
  if (beforeQ.isLoading || afterQ.isLoading) {
    return <Centered>Loading diff...</Centered>;
  }
  if (beforeQ.isError || afterQ.isError || !beforeQ.data || !afterQ.data) {
    return <Centered>Could not render this {kind} diff.</Centered>;
  }
  return (
    <SvgDiffViewport before={beforeQ.data} after={afterQ.data} label={KIND_LABEL[kind]} />
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-full w-full items-center justify-center px-6 text-center text-sm text-t3">
      {children}
    </div>
  );
}
