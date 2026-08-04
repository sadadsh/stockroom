/**
 * The old/new geometry diff overlay: the part's symbol/footprint SVG as of two revisions
 * (fetched with ?rev, so the historical blob is drawn, never the working tree), cross-faded in one
 * shared pan/zoom viewport. Only the asset kinds that actually changed between the two revisions
 * get a tab; a kind is never shown if it did not move.
 *
 * It is opened from INSIDE the Sources & History sheet, which is itself a modal. That nesting is
 * the reason the shared `ModalShell` exists: this window and the sheet under it were both
 * `z-[110]` with their own window-level Escape listener, so one press closed both and neither
 * reliably painted on top. The stack in `lib/useModalDismiss.ts` settles both questions, and this
 * file no longer has an opinion about either.
 */
import { useState } from "react";
import type { DiffAssets } from "../api/types";
import { usePreviewSvg } from "../api/queries";
import { Text, useText } from "../lib/copy";
import { ErrorState, LoadingState, ModalShell, TabStrip, type TabItem } from "./primitives";
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
  const tablistLabel = useText("modal.diff.tablist", "Diff Type");
  const soleKind: DiffKind = changed[0] ?? "symbol";
  const kindTabs: TabItem<DiffKind>[] = changed.map((k) => ({
    id: k,
    label: KIND_LABEL[k],
    copyId: `modal.diff.kind-${k}`,
  }));

  return (
    <ModalShell
      open={open}
      title={partName}
      label={`Visual Diff for ${partName}`}
      onClose={onClose}
      size="stage"
      devId="diff.root"
      headerDevId="diff.header"
      bodyDevId="diff.stage"
      headerExtra={
        changed.length > 1 ? (
          // The app's ONE tab control, rather than a fourth hand-rolled row of pills. It brings
          // the roving tabindex and the arrow keys with it, which the loose buttons here never had.
          <TabStrip
            tabs={kindTabs}
            active={kind}
            onSelect={setKind}
            idBase="diff-kind"
            devIdBase="diff"
            density="compact"
            className="flex-none"
            aria-label={tablistLabel}
          />
        ) : (
          <span className="flex-none text-2xs text-t3">
            <Text id={`modal.diff.kind-${soleKind}`}>{KIND_LABEL[soleKind]}</Text>
          </span>
        )
      }
    >
      <DiffBody kind={kind} partId={partId} a={a} b={b} />
    </ModalShell>
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
    return (
      <Centered>
        <LoadingState dense id="modal.diff.loading">
          Loading this change...
        </LoadingState>
      </Centered>
    );
  }
  if (beforeQ.isError || afterQ.isError || !beforeQ.data || !afterQ.data) {
    return (
      <Centered>
        {/* One written sentence per kind, never the fetch's own exception text. */}
        {kind === "symbol" ? (
          <ErrorState dense id="modal.diff.failed-symbol">
            This symbol could not be drawn for either revision.
          </ErrorState>
        ) : (
          <ErrorState dense id="modal.diff.failed-footprint">
            This footprint could not be drawn for either revision.
          </ErrorState>
        )}
      </Centered>
    );
  }
  return (
    <SvgDiffViewport before={beforeQ.data} after={afterQ.data} label={KIND_LABEL[kind]} />
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-full w-full items-center justify-center px-6 text-center">
      {children}
    </div>
  );
}
