/**
 * The expanded, in-window preview: one asset at full size, pan/zoomed or orbited.
 *
 * Each card opens only its own viewer; switching asset kinds happens in the component workspace,
 * never inside a second combined inspector. The frame, the close control, the Escape handling and
 * the Tab trap are the shared `ModalShell`'s, so this window reads and behaves like every other
 * one instead of carrying its own third of a modal implementation.
 */
import { usePreviewSvg } from "../api/queries";
import { useText } from "../lib/copy";
import { ErrorState, LoadingState, ModalShell } from "./primitives";
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
  const symbolLabel = useText("modal.preview.kind-symbol", "Symbol");
  const footprintLabel = useText("modal.preview.kind-footprint", "Footprint");
  const modelLabel = useText("modal.preview.kind-model", "3D Model");
  const kindLabel =
    initialKind === "model" ? modelLabel : initialKind === "symbol" ? symbolLabel : footprintLabel;

  return (
    <ModalShell
      open={open}
      title={partName}
      label={`Inspect ${partName}`}
      onClose={onClose}
      size="full"
      devId="preview.root"
      headerDevId="preview.header"
      closeDevId="preview.close"
      bodyDevId="preview.stage"
      headerExtra={<span className="flex-none text-2xs font-medium text-t3">{kindLabel}</span>}
    >
      {initialKind === "model" ? (
        <ModelViewer partId={partId} />
      ) : (
        <SvgPreview kind={initialKind} partId={partId} />
      )}
    </ModalShell>
  );
}

// The symbol/footprint body: fetch the ?bw SVG (warm from the thumbnail cache) and hand it to the
// pan/zoom viewport, with honest loading and failure states in the shared vocabulary.
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
        <LoadingState dense id="modal.preview.loading">
          Loading this preview...
        </LoadingState>
      </Centered>
    );
  }
  if (query.isError || !query.data) {
    return (
      <Centered>
        {/* A written sentence per kind. The query's own error text is a transport detail. */}
        {kind === "symbol" ? (
          <ErrorState dense id="modal.preview.failed-symbol" onRetry={() => query.refetch()}>
            This symbol could not be drawn.
          </ErrorState>
        ) : (
          <ErrorState dense id="modal.preview.failed-footprint" onRetry={() => query.refetch()}>
            This footprint could not be drawn.
          </ErrorState>
        )}
      </Centered>
    );
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
    <div className="flex h-full w-full items-center justify-center px-6 text-center">
      {children}
    </div>
  );
}
