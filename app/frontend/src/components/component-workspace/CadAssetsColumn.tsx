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
 *
 * THE COLUMN IS FIVE PLACEMENTS NOW (plan Phase 1): a title strip, the preferred-source row, and
 * three placements of ONE module piece parameterised by representation kind. The document decides
 * the order and which kinds are drawn; `CadColumnChrome` supplies what all five need and nothing
 * else. The expansion state stays where it was - it is a per-component UI SESSION fact, a data need
 * of the module, not a per-placement setting - because a person focusing the footprint on one part
 * is not redesigning the workspace.
 */
import { createContext, useContext, useMemo } from "react";
import type { ComponentDossier, RepresentationKind } from "../../api/dossierTypes";
import { useWriteCadPreference } from "../../api/queries";
import { Text, useText } from "../../lib/copy";
import { useToast } from "../../lib/toast";
import type { PiecePartProps, RegionChromeProps } from "../../layout/LayoutRenderer";
import { useWorkspaceRender } from "../../layout/workspaceRenderContext";
import { Button } from "../primitives";
import { CadAssetModule } from "./CadAssetModule";
import { REPRESENTATION_KINDS } from "./cadAssetSet";
import { PreferredSourceControl } from "./PreferredSourceControl";
import {
  WorkspaceColumnFrame,
  WorkspaceColumnScroller,
  WorkspaceColumnTitleStrip,
} from "./WorkspaceColumns";
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

/** What the column derives once and its pieces read. Never a second copy of the dossier. */
interface CadColumnState {
  attached: number;
  pins: number | null;
  pitch: number | null;
  setAssetRef: Record<RepresentationKind, (node: HTMLElement | null) => void>;
  writing: boolean;
  choose: (provider: string) => void;
  clear: () => void;
}

const CadColumnContext = createContext<CadColumnState | null>(null);

/** The column's frame, and the one derivation its pieces share. */
export function CadColumnChrome({ children }: RegionChromeProps) {
  const workspace = useWorkspaceRender();
  const componentId = workspace?.componentId ?? "";
  const write = useWriteCadPreference(componentId);
  const { toast } = useToast();
  const failed = useText(
    "component-browser.cad-source-failed",
    "Could not record the preferred source.",
  );
  const assetRefs = workspace?.cad.assetRefs;
  // Stable per-kind callback refs, so a re-render does not detach and reattach every module.
  const setAssetRef = useMemo(
    () =>
      Object.fromEntries(
        REPRESENTATION_KINDS.map((kind) => [
          kind,
          (node: HTMLElement | null) => {
            if (assetRefs) assetRefs.current[kind] = node;
          },
        ]),
      ) as Record<RepresentationKind, (node: HTMLElement | null) => void>,
    [assetRefs],
  );
  const dossier = workspace?.dossier;
  const state = useMemo<CadColumnState | null>(() => {
    if (!dossier) return null;
    const report = (error: unknown) =>
      toast(error instanceof Error ? error.message : failed, "err");
    return {
      attached: attachedCount(dossier),
      pins: expectedPinCount(dossier),
      pitch: expectedPitch(dossier),
      setAssetRef,
      writing: write.isPending,
      choose: (provider: string) =>
        write.mutate({ kind: "set-set-source", provider }, { onError: report }),
      clear: () => write.mutate({ kind: "clear-set-source" }, { onError: report }),
    };
  }, [dossier, failed, setAssetRef, toast, write]);

  if (!state) return null;
  return (
    <WorkspaceColumnFrame id="cad" devId="component-browser.column-cad">
      <CadColumnContext.Provider value={state}>{children}</CadColumnContext.Provider>
    </WorkspaceColumnFrame>
  );
}

/**
 * `CAD Assets  [Compare Sources]  2/3` - the column's one action, on the title line.
 *
 * It used to sit on a toolbar row of its own ABOVE the preferred source, so a ~300px column spent
 * two full rows on chrome before the first drawing: measured, the two rows plus six rows of layer
 * pills came to 14 bordered controls over the symbol. On the title line it costs no vertical space
 * at all.
 */
export function CadTitleStripPart() {
  const workspace = useWorkspaceRender();
  const state = useContext(CadColumnContext);
  if (!workspace || !state) return null;
  return (
    <WorkspaceColumnTitleStrip
      title={<Text id="component-browser.column-cad">CAD Assets</Text>}
      meta={`${state.attached}/${REPRESENTATION_KINDS.length}`}
      action={
        <Button
          small
          data-dev-id="component-browser.compare-sources"
          onClick={workspace.cad.onCompareSources}
        >
          <Text id="component-browser.compare-sources">Compare Sources</Text>
        </Button>
      }
    />
  );
}

/**
 * ONE row, and the set decision owns it.
 *
 * The preferred source is the only fact here whose VALUE has to be readable, so it gets the elastic
 * width rather than sharing it with a button that has a permanent home on the line above.
 */
export function CadPreferredSourcePart() {
  const workspace = useWorkspaceRender();
  const state = useContext(CadColumnContext);
  if (!workspace || !state) return null;
  const { layout, onLayout } = workspace.cad;
  return (
    <div className="flex min-w-0 flex-none items-center gap-2 border-b border-line px-2 py-1">
      <span className="flex min-w-0 flex-1 items-center">
        <PreferredSourceControl
          preference={workspace.dossier.cadAssets.preference}
          busy={state.writing}
          onChoose={state.choose}
          onClear={state.clear}
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
  );
}

/** The column's one scroller, and the group the three modules are read as. */
export function CadBodyChrome({ children }: RegionChromeProps) {
  const columnTitle = useText("component-browser.column-cad", "CAD Assets");
  return (
    <WorkspaceColumnScroller id="cad">
      <div aria-label={columnTitle} role="group">
        {children}
      </div>
    </WorkspaceColumnScroller>
  );
}

/**
 * One representation module, named by the placement.
 *
 * `params.representation` is what distinguishes three appearances of one piece. A kind the document
 * asks for that the projection does not carry draws nothing rather than an empty module.
 */
export function CadAssetModulePart({ placement }: PiecePartProps) {
  const workspace = useWorkspaceRender();
  const state = useContext(CadColumnContext);
  if (!workspace || !state) return null;
  const kind = placement.params?.representation as RepresentationKind | undefined;
  if (!kind) return null;
  const view = workspace.dossier.cadAssets.kinds[kind];
  if (!view) return null;
  const { layout, onLayout, onOpenFullPreview } = workspace.cad;
  return (
    <CadAssetModule
      componentId={workspace.componentId}
      kind={kind}
      view={view}
      preference={workspace.dossier.cadAssets.preference}
      expectedPins={state.pins}
      expectedPitch={state.pitch}
      expanded={layout === "all" || layout === kind}
      focused={layout === kind}
      onToggle={() => onLayout(layout === kind ? "all" : kind)}
      onOpenFullPreview={() => onOpenFullPreview(kind)}
      focusRef={state.setAssetRef[kind]}
    />
  );
}
