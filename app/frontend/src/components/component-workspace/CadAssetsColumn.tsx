/**
 * The left column: CAD Assets.
 *
 * Three stacked modules whose headers are ALWAYS visible, a column toolbar that names the source
 * the whole coherent set comes from, and one way into the provider comparison. The column's job
 * is to answer "does this component have the drawings, and can they be trusted" without ever
 * naming an EDA application - which is what `Preferred Source` is for: one statement at column
 * level about where the set comes from, instead of the same provider sentence repeated under all
 * three assets.
 *
 * `Preferred Source` is a CONTROL, not a caption. It used to be inferred from the three attached
 * files and to say "Mixed" when they disagreed, which described the past and gave a person
 * looking at a mixed set nothing to do about it. It now records a decision, and the decision is
 * shown before it is taken.
 *
 * Expansion state persists per component in the ui session. `all` is the three expanded together,
 * which is the reading state: the whole point of the column is that a symbol and a footprint are
 * checked against each other. Focusing one asset compacts the other two and never removes them.
 */
import { useMemo, type MutableRefObject } from "react";
import type { ComponentDossier, RepresentationKind } from "../../api/dossierTypes";
import { useWriteCadPreference } from "../../api/queries";
import type { RepresentationLayout } from "../../lib/uiSession";
import { Text, useText } from "../../lib/copy";
import { useToast } from "../../lib/toast";
import { Button } from "../primitives";
import { CadAssetModule } from "./CadAssetModule";
import { REPRESENTATION_KINDS } from "./cadAssetSet";
import { PreferredSourceControl } from "./PreferredSourceControl";
import { WorkspaceColumn } from "./WorkspaceColumns";
import { cadAssetStatus } from "./workspaceStatus";

/** How many of the three assets are actually attached. The column strip's right-hand count. */
function attachedCount(dossier: ComponentDossier): number {
  const representations = dossier.cadAssets.kinds;
  return REPRESENTATION_KINDS.filter((kind) => {
    const status = cadAssetStatus(representations[kind]);
    return status === "Validated" || status === "Available" || status === "Package Matched";
  }).length;
}

/**
 * The component's own pin count, so a drawn terminal count has a second side to compare against.
 *
 * Read from the projected key specifications rather than from the raw spec bag, because that is
 * where the category schema has already decided which field means "how many terminals does this
 * part have" - and a comparison against a field nobody normalized is not a comparison.
 */
function expectedPinCount(dossier: ComponentDossier): number | null {
  return numericSpecification(dossier, ["pin_count", "number_of_pins", "positions"]);
}

/** The package pitch the specification states, in millimetres, when it states one. */
function expectedPitch(dossier: ComponentDossier): number | null {
  return numericSpecification(dossier, ["pitch"]);
}

function numericSpecification(dossier: ComponentDossier, keys: string[]): number | null {
  const rows = [
    ...dossier.keySpecifications,
    ...dossier.specificationGroups.flatMap((group) => group.specifications),
  ];
  for (const key of keys) {
    const row = rows.find((record) => record.key === key);
    const value = row?.normalizedValue;
    if (typeof value === "number" && Number.isFinite(value)) return value;
    const parsed = Number.parseFloat(String(row?.displayValue ?? ""));
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

export function CadAssetsColumn({
  componentId,
  dossier,
  layout,
  onLayout,
  onCompareSources,
  onOpenFullPreview,
  assetRefs,
}: {
  componentId: string;
  dossier: ComponentDossier;
  /** `all` expands the three; a kind expands that one and compacts the other two. */
  layout: RepresentationLayout;
  onLayout: (layout: RepresentationLayout) => void;
  onCompareSources: () => void;
  onOpenFullPreview: (kind: RepresentationKind) => void;
  /** Where each module's element is kept, so the quality summary can scroll one into view. */
  assetRefs: MutableRefObject<Partial<Record<RepresentationKind, HTMLElement | null>>>;
}) {
  const representations = dossier.cadAssets.kinds;
  const preference = dossier.cadAssets.preference;
  const columnTitle = useText("component-browser.column-cad", "CAD Assets");
  const attached = attachedCount(dossier);
  const pins = expectedPinCount(dossier);
  const pitch = expectedPitch(dossier);
  const write = useWriteCadPreference(componentId);
  const { toast } = useToast();
  const failed = useText(
    "component-browser.cad-source-failed",
    "Could not record the preferred source.",
  );

  // Stable per-kind callback refs, so a re-render does not detach and reattach every module.
  const setAssetRef = useMemo(
    () =>
      Object.fromEntries(
        REPRESENTATION_KINDS.map((kind) => [
          kind,
          (node: HTMLElement | null) => {
            assetRefs.current[kind] = node;
          },
        ]),
      ) as Record<RepresentationKind, (node: HTMLElement | null) => void>,
    [assetRefs],
  );

  const report = (error: unknown) =>
    toast(error instanceof Error ? error.message : failed, "err");

  return (
    <WorkspaceColumn
      id="cad"
      devId="component-browser.column-cad"
      title={<Text id="component-browser.column-cad">CAD Assets</Text>}
      meta={`${attached}/${REPRESENTATION_KINDS.length}`}
      // `CAD Assets  [Compare Sources]  2/3` - the column's one action, on the title line, which is
      // where the layout has always put it. It used to sit on a toolbar row of its own ABOVE the
      // preferred source, so a ~300px column spent two full rows on chrome before the first
      // drawing: measured, the two rows plus six rows of layer pills came to 14 bordered controls
      // over the symbol. On the title line it costs no vertical space at all.
      action={
        <Button small data-dev-id="component-browser.compare-sources" onClick={onCompareSources}>
          <Text id="component-browser.compare-sources">Compare Sources</Text>
        </Button>
      }
      toolbar={
        // ONE row, and the set decision owns it: the preferred source is the only fact here whose
        // VALUE has to be readable, so it gets the elastic width rather than sharing it with a
        // button that has a permanent home on the line above.
        <div className="flex min-w-0 flex-none items-center gap-2 border-b border-line px-2 py-1">
          <span className="flex min-w-0 flex-1 items-center">
            <PreferredSourceControl
              preference={preference}
              busy={write.isPending}
              onChoose={(provider) =>
                write.mutate({ kind: "set-set-source", provider }, { onError: report })
              }
              onClear={() => write.mutate({ kind: "clear-set-source" }, { onError: report })}
            />
          </span>
          {/* The way back to the reading state. Offered only when one module is focused, because
              a control that puts the column into the state it is already in is a dead click. */}
          {layout === "all" ? null : (
            <Button
              small
              data-dev-id="component-browser.show-all-assets"
              onClick={() => onLayout("all")}
              className="flex-none"
            >
              <Text id="component-browser.show-all-assets">Show All Three</Text>
            </Button>
          )}
        </div>
      }
    >
      <div aria-label={columnTitle} role="group">
        {REPRESENTATION_KINDS.map((kind) => (
          <CadAssetModule
            key={kind}
            componentId={componentId}
            kind={kind}
            view={representations[kind]}
            preference={preference}
            expectedPins={pins}
            expectedPitch={pitch}
            expanded={layout === "all" || layout === kind}
            focused={layout === kind}
            onToggle={() => onLayout(layout === kind ? "all" : kind)}
            onOpenFullPreview={() => onOpenFullPreview(kind)}
            focusRef={setAssetRef[kind]}
          />
        ))}
      </div>
    </WorkspaceColumn>
  );
}
