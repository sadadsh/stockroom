/**
 * The expanded, in-window preview (M6d) — the ConfirmDialog/CommandPalette scrim idiom,
 * no OS window. Each card opens only its own viewer; switching asset kinds happens in the
 * component workspace, never inside a second combined inspector. The body pan/zooms the SVG
 * or orbits the 3D model. Escape or a scrim click closes, Tab is trapped, and focus returns to where it
 * was so the modal never strands focus on inert background.
 */
import { usePreviewSvg } from "../api/queries";
import { useModalDismiss } from "../lib/useModalDismiss";
import { Text, useText } from "../lib/copy";
import { ModelViewer } from "./ModelViewer";
import { SvgViewport } from "./SvgViewport";

export type PreviewKind = "model" | "symbol" | "footprint";

interface Props {
  open: boolean;
  partId: string;
  partName: string;
  initialKind: PreviewKind;
  onClose: () => void;
}

export function PreviewModal({
  open,
  partId,
  partName,
  initialKind,
  onClose,
}: Props) {
  const dialogRef = useModalDismiss(open, onClose);
  const closeLabel = useText("modal.preview.close", "Close");
  const kindLabel =
    initialKind === "model" ? "3D Model" : initialKind === "symbol" ? "Symbol" : "Footprint";

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[110] flex items-center justify-center bg-black/50 p-3"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        data-dev-id="preview.root"
        role="dialog"
        aria-modal="true"
        aria-label={`Inspect ${partName}`}
        tabIndex={-1}
        className="flex h-[calc(100vh-24px)] max-h-[1100px] w-[calc(100vw-24px)] max-w-[1600px] flex-col overflow-hidden rounded-card border border-line2 bg-popover shadow-pop outline-none"
      >
        <div
          data-dev-id="preview.header"
          className="flex h-[38px] flex-none items-center gap-3 border-b border-line bg-band px-4"
        >
          <span className="min-w-0 flex-none truncate text-xs font-semibold text-t1">
            {partName}
          </span>
          <span className="flex-none text-2xs font-medium uppercase tracking-[0.08em] text-t3">
            {kindLabel}
          </span>
          <button
            type="button"
            data-dev-id="preview.close"
            onClick={onClose}
            aria-label={closeLabel}
            className="ml-auto flex-none rounded-control border border-line2 bg-raise px-2.5 py-1 text-xs font-medium text-t2 hover:text-t1"
          >
            <Text id="modal.preview.close-btn">Close</Text>
          </button>
        </div>

        <div data-dev-id="preview.stage" className="relative flex-1 bg-field">
          {initialKind === "model" ? (
            <ModelViewer partId={partId} />
          ) : (
            <SvgPreview kind={initialKind} partId={partId} />
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
    return (
      <Centered>
        <Text id="modal.preview.loading">Loading preview...</Text>
      </Centered>
    );
  }
  if (query.isError || !query.data) {
    return <Centered>Could not render this {kind}.</Centered>;
  }
  const safePartName = partId.replace(/[^a-z0-9._-]+/gi, "-");
  return (
    <SvgViewport
      blob={query.data}
      alt={`${kind} preview`}
      downloadName={`${safePartName}-${kind}.svg`}
    />
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-full w-full items-center justify-center px-6 text-center text-sm text-t3">
      {children}
    </div>
  );
}
