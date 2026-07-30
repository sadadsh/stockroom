/**
 * EDA-target readiness model. Settings picks a target EDA tool; the library then flags parts
 * that are not ready for THAT tool. Pure functions, no React: the panel and the Settings
 * rollup read readiness through this one module instead of each re-deriving it.
 *
 * Readiness is GENERIC IN BOTH ARGUMENTS: it is `f(part_class, tool)`, and neither half is a
 * branch. A part carries one symmetric asset bundle per tool (`detail.assets[tool]`, matching
 * `stockroom.model.asset.EdaAssets`); the tool's facts and the class's needs BOTH come from
 * `edaRegistry.generated.ts`, which is generated from the Python registry and gated by a
 * pytest. So adding a third EDA tool, or a fifth part class, changes nothing in this file.
 *
 * That symmetry is the fix, not a refactor, and it has been paid for twice:
 *
 *  - PER TOOL: this module used to branch `if (tool === "altium")` to read `part.altium_symbol`
 *    while the KiCad path read `part.symbol` -- and because Altium had no 3D-model slot at all,
 *    the branch simply asserted `model = true`. Any part whose Altium assets were attached
 *    still read "CAD Incomplete" forever (live 2026-07-24, reported ~10 times).
 *  - PER CLASS: it then branched `if (part.passive)` to excuse the 3D model. `passive` became a
 *    four-valued `part_class` on 2026-07-27, and the naive port of that branch
 *    (`part_class === "passive"`) would have reported every `mechanical` part as missing a
 *    symbol forever -- a class that has no symbol BY DEFINITION. Same defect, same shape.
 *
 * A branch per tool, or per class, is how that happens; a table lookup is how it cannot.
 */
import {
  ASSET_LABELS,
  DEFAULT_EDA_TOOL,
  EDA_TOOLS,
  edaTool,
  partClass,
} from "./edaRegistry.generated";
import type { EdaToolSpec, EmbeddedAssetSpec, PartClassSpec } from "./edaRegistry.generated";
import type { Asset, AssetRef, EdaAssets, PartDetail, PartSummary } from "../api/types";

export type EdaTool = string;

export { DEFAULT_EDA_TOOL };

// The selectable tools with their display labels, in the registry's own order (KiCad first:
// it is the default and the library Stockroom itself writes).
export const EDA_TOOL_OPTIONS: readonly { tool: EdaTool; label: string }[] = EDA_TOOLS.map(
  (t) => ({ tool: t.key, label: t.label }),
);

// Title Case labels for the readiness UI (the design contract: Title Case for interactive
// labels and headings). The registry's lower-case kind labels are the record-level wording.
const TITLE_LABELS: Record<string, string> = {
  symbol: "Symbol",
  footprint: "Footprint",
  model: "3D Model",
};

/** The Title Case name of an asset kind, for interactive labels and headings (the
 * design contract: Title Case for controls, sentence case for body prose). */
export function assetTitleLabel(kind: string): string {
  return TITLE_LABELS[kind] ?? ASSET_LABELS[kind] ?? kind;
}

const EMPTY_ASSETS: EdaAssets = { symbol: null, footprint: null, model: null };

/** A part's asset bundle for one tool. Absent tools read as an empty bundle, never as
 * another tool's assets. */
export function assetsFor(part: Pick<PartDetail, "assets">, tool: EdaTool): EdaAssets {
  return part.assets?.[tool] ?? EMPTY_ASSETS;
}

/**
 * Just the REFERENCE out of an asset slot, for callers that only need where the asset is.
 *
 * An asset is `{ref, origin?, checks?}`, not a bare `{lib,name,file}` -- that wrapper is what
 * makes "where did this file come from" answerable at all. Reading `slot.name` instead of
 * `slot.ref.name` yields `undefined` and reports the asset ABSENT, silently, which is the
 * 2026-07-27 break this whole module was rewritten for. Going through here means no call site
 * has to remember the wrapper.
 */
export function assetRef(asset: Asset | null | undefined): AssetRef | null {
  return asset?.ref ?? null;
}

/** True when an asset actually resolves: an entry-shaped one by `name`, a file-shaped one
 * (a 3D model) by `file`. A container with no entry is NOT present. Mirrors
 * `stockroom.model.part.asset_present`. */
export function assetPresent(asset: Asset | null | undefined): boolean {
  const ref = assetRef(asset);
  return !!ref && !!(ref.name || ref.file);
}

export interface AssetReadiness {
  /** Per-kind presence, e.g. `{ symbol: true, footprint: false, model: false }`. */
  present: Record<string, boolean>;
  /** The Title Case labels of the assets absent for `tool`, in the tool's kind order. */
  missing: string[];
  /**
   * Asset kinds this tool cannot be given by reference at all, mapped to why (Altium's 3D
   * model lives inside the footprint's .PcbLib binary). One of these counts as missing ONLY
   * when it also appears in `embedded`, i.e. when there is a real way to close it. Reporting a
   * gap that can never be closed is what "CAD Incomplete forever" looked like; hiding one that
   * CAN be closed is how Altium parts silently shipped with no 3D at all.
   */
  unsupported: Record<string, string>;
  /**
   * Asset kinds obtainable by EMBEDDING, mapped to how. The UI offers the embed action for
   * these, and `reason` is what to show when it is unavailable (embedding runs the real EDA
   * tool, so it needs that tool installed on this machine).
   */
  embedded: Record<string, EmbeddedAssetSpec>;
  /** Ready when every BLOCKING asset the part's class needs from this tool is present. A 3D
   * model is reported when absent but never blocks (a footprint places fine without one), and
   * a class that needs nothing -- a passive, a fiducial -- is ready by definition. */
  ready: boolean;
}

/**
 * The asset kinds worth REPORTING on for a tool: everything except a kind that can never be
 * closed at all. Mirrors `EdaTool.closable_assets` in stockroom/eda/registry.py, and the
 * pytest-gated generated registry is what keeps the two from drifting.
 *
 * Exported because it is the whole rule in one place and the rule is what needs testing. Asserted
 * against the live registry it would be VACUOUS today (KiCad has no unsupported kinds, and
 * Altium's only unsupported kind is embeddable), so a test must hand it a synthetic spec. A test
 * that cannot fail is worse than no test.
 */
export function reportableKinds(
  spec: Pick<EdaToolSpec, "assetKinds" | "unsupportedAssets" | "embeddedAssets">,
): string[] {
  return spec.assetKinds.filter(
    (kind) => !(kind in spec.unsupportedAssets) || kind in spec.embeddedAssets,
  );
}

/**
 * Asset kinds a part of this class NEEDS, before the tool is considered. The per-part
 * `requires_override` REPLACES the class list when it applies, so one odd part never forces a
 * new class. Mirrors `stockroom.model.part_class._wanted`.
 *
 * A null override means "use the class default"; an override with an empty `needs` is somebody
 * stating that this one part needs nothing, and collapsing the two is how an escape hatch
 * silently stops working -- hence the explicit null check rather than a truthiness test.
 */
export function neededKinds(
  part: Pick<PartDetail, "part_class" | "requires_override">,
  tool: EdaTool,
  spec: Pick<PartClassSpec, "assets"> | undefined,
): string[] {
  const override = part.requires_override;
  if (override && (override.tools.length === 0 || override.tools.includes(tool))) {
    return [...override.needs];
  }
  return [...(spec?.assets ?? [])];
}

/**
 * An asset kind that is reported when absent but does NOT hold readiness open: a footprint
 * places fine without a 3D body. Mirrors `stockroom.model.part.tool_assets_ready`, which asks
 * for the symbol and the footprint only.
 *
 * Named rather than inlined because it IS the rule, and because expressing it as "everything
 * the class needs except this" is what lets a `mechanical` part (footprint, no symbol) be
 * ready at all. Hardcoding `symbol && footprint` the way the backend still does cannot.
 */
const NON_BLOCKING_KINDS: ReadonlySet<string> = new Set(["model"]);

// The per-tool asset readiness of one part detail.
export function assetReadiness(part: PartDetail, tool: EdaTool): AssetReadiness {
  const spec = edaTool(tool);
  const assets = assetsFor(part, tool);
  const unsupported = spec?.unsupportedAssets ?? {};
  const embedded = spec?.embeddedAssets ?? {};
  // What the TOOL can hold, intersected with what the CLASS needs. Both are table lookups.
  const reportable = reportableKinds({
    assetKinds: spec?.assetKinds ?? ["symbol", "footprint", "model"],
    unsupportedAssets: unsupported,
    embeddedAssets: embedded,
  });
  const needed = neededKinds(part, tool, partClass(part.part_class));

  // `present` covers every kind the TOOL can hold, because it answers "is this attached" and a
  // passive that happens to carry a stock symbol reference should say so. `missing` and `ready`
  // cover only what the CLASS needs, because they answer "is there work left to do" -- and a
  // gap a part can never have is not work. Reporting one is precisely "CAD Incomplete forever".
  const present: Record<string, boolean> = {};
  for (const kind of reportable) {
    present[kind] = assetPresent(assets[kind as keyof EdaAssets]);
  }

  const missing: string[] = [];
  let ready = true;
  for (const kind of reportable) {
    if (!needed.includes(kind) || present[kind]) continue;
    missing.push(assetTitleLabel(kind));
    if (!NON_BLOCKING_KINDS.has(kind)) ready = false;
  }

  return { present, missing, unsupported, embedded, ready };
}

export interface SummaryReadiness {
  ready: boolean;
  coverageComplete: boolean;
  trust: "pass" | "fail" | "unknown";
  missing: string[];
}

// The readiness of a list-row summary comes entirely from the backend's registry-keyed contract.
// `is_complete` / `missing` are passport-data fields, not CAD facts, and a default-tool branch
// would quietly turn metadata presence into both CAD coverage and trust. A missing/stale tool row
// fails closed without fabricating which asset is absent.
export function summaryReadiness(
  part: Pick<PartSummary, "eda_readiness">,
  tool: EdaTool,
): SummaryReadiness {
  const state = part.eda_readiness?.[tool];
  return {
    // Treat the backend's convenience boolean as a claim that must agree with its
    // underlying evidence. A stale or partially upgraded row can never make the UI
    // say Ready without complete coverage and a passing trust verdict.
    ready:
      state?.ready === true &&
      state.coverage_complete === true &&
      state.trust === "pass",
    coverageComplete: state?.coverage_complete ?? false,
    trust: state?.trust ?? "unknown",
    missing: (state?.missing ?? []).map(assetTitleLabel),
  };
}

export interface LibraryReadiness {
  total: number;
  complete: number;
  incomplete: number;
  // The ids of the parts not ready for the selected tool (the ones the library flags red).
  notReadyIds: string[];
}

// The library-wide readiness rollup the Settings panel shows for the selected tool.
export function libraryReadiness(parts: PartSummary[], tool: EdaTool): LibraryReadiness {
  const notReadyIds: string[] = [];
  for (const part of parts) {
    if (!summaryReadiness(part, tool).ready) notReadyIds.push(part.id);
  }
  return {
    total: parts.length,
    complete: parts.length - notReadyIds.length,
    incomplete: notReadyIds.length,
    notReadyIds,
  };
}
