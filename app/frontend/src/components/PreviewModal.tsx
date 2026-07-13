/**
 * The expanded, in-window preview (M6d) — the ConfirmDialog/CommandPalette scrim idiom,
 * no OS window. Tabs switch between the 3D model, the symbol and the footprint (only the
 * ones the part actually has are enabled); the body pan/zooms the SVG or orbits the 3D
 * model. Escape or a scrim click closes, Tab is trapped, and focus returns to where it
 * was so the modal never strands focus on inert background.
 */
import { useEffect, useState } from "react";
import { usePreviewSvg } from "../api/queries";
import { useModalDismiss } from "../lib/useModalDismiss";
import { ModelViewer } from "./ModelViewer";
import { SvgViewport } from "./SvgViewport";

export type PreviewKind = "model" | "symbol" | "footprint";

const TABS: { kind: PreviewKind; label: string }[] = [
  { kind: "model", label: "3D Model" },
  { kind: "symbol", label: "Symbol" },
  { kind: "footprint", label: "Footprint" },
];

interface Props {
  open: boolean;
  partId: string;
  partName: string;
  available: Record<PreviewKind, boolean>;
  initialKind: PreviewKind;
  onClose: () => void;
}

export function PreviewModal({
  open,
  partId,
  partName,
  available,
  initialKind,
  onClose,
}: Props) {
  const [kind, setKind] = useState<PreviewKind>(initialKind);
  // Every open starts on the card the user clicked; the shared hook handles focus
  // capture/restore and Escape + Tab trapping.
  useEffect(() => {
    if (open) setKind(initialKind);
  }, [open, initialKind]);
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
        aria-label={`Previews for ${partName}`}
        tabIndex={-1}
        className="flex h-[80vh] max-h-[680px] w-full max-w-[860px] flex-col overflow-hidden rounded-card border border-line2 bg-popover shadow-pop outline-none"
      >
        <div className="flex items-center gap-3 border-b border-line px-4 py-3">
          <span className="min-w-0 flex-none truncate text-sm font-semibold text-t1">
            {partName}
          </span>
          <div className="flex gap-1" role="tablist" aria-label="Preview Type">
            {TABS.map((t) => {
              const enabled = available[t.kind];
              const active = kind === t.kind;
              return (
                <button
                  key={t.kind}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  disabled={!enabled}
                  onClick={() => setKind(t.kind)}
                  className={
                    "rounded-control px-2.5 py-1 text-xs font-medium transition-colors " +
                    (active
                      ? "bg-raise2 text-t1"
                      : enabled
                        ? "text-t2 hover:bg-raise hover:text-t1"
                        : "cursor-not-allowed text-t3 opacity-50")
                  }
                >
                  {t.label}
                </button>
              );
            })}
          </div>
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
          {kind === "model" ? (
            <ModelViewer partId={partId} />
          ) : (
            <SvgPreview kind={kind} partId={partId} />
          )}
        </div>
      </div>
    </div>
  );
}

// The symbol/footprint tab body: fetch the ?bw SVG (warm from the thumbnail cache) and
// hand it to the pan/zoom viewport, with honest loading/error states.
function SvgPreview({
  kind,
  partId,
}: {
  kind: "symbol" | "footprint";
  partId: string;
}) {
  const query = usePreviewSvg(kind, partId);
  if (query.isLoading) {
    return <Centered>Loading preview...</Centered>;
  }
  if (query.isError || !query.data) {
    return <Centered>Could not render this {kind}.</Centered>;
  }
  return <SvgViewport blob={query.data} alt={`${kind} preview`} />;
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-full w-full items-center justify-center px-6 text-center text-sm text-t3">
      {children}
    </div>
  );
}
