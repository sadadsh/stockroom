/**
 * GENERATED FILE -- do not hand-edit.
 *
 * Mirrors `app/backend/stockroom/eda/registry.py`, the one place an EDA tool's facts
 * live. Regenerate with `uv run python scripts/gen_eda_registry_ts.py`; a pytest
 * (tests/backend/eda/test_registry_ts_parity.py) fails if this file drifts from the
 * Python registry, so the two can never disagree about what a tool can hold.
 */

// One EDA tool's facts, as far as the UI is concerned.
export interface EdaToolSpec {
  /** Registry key, and the key into a part's `eda` map. */
  key: string;
  /** Display label. */
  label: string;
  /** Asset kinds this tool consumes, in report order. */
  assetKinds: string[];
  /**
   * Asset kinds this tool CANNOT be given by reference, mapped to why. Never report
   * one of these as a missing asset: it names a gap that can never be closed.
   */
  unsupportedAssets: Record<string, string>;
  /**
   * Asset kinds this tool takes only by EMBEDDING: the tool itself writes the payload
   * into a binary container the part already owns (an Altium 3D body goes inside the
   * footprint's .PcbLib). A kind may be BOTH unsupported-by-reference and embeddable,
   * and that combination is a real, closable gap that MUST be reported. `reason`
   * explains what embedding needs, so a machine without the tool can say why rather
   * than silently doing nothing.
   */
  embeddedAssets: Record<string, EmbeddedAssetSpec>;
}

// How one asset kind gets embedded (mirrors stockroom.eda.registry.EmbeddedAsset).
export interface EmbeddedAssetSpec {
  /** The asset whose file receives the payload. */
  container: string;
  /** The asset kind that supplies the payload. */
  source: string;
  /** Whether embedding needs the EDA tool installed on this machine. */
  requiresToolInstalled: boolean;
  reason: string;
}

// Human labels for the asset kinds, keyed as the registry keys them.
export const ASSET_LABELS: Record<string, string> = {
  symbol: "symbol",
  footprint: "footprint",
  model: "3D model",
};

// Every registered tool, in the registry's stable order.
export const EDA_TOOLS: EdaToolSpec[] = [
  {
    key: "kicad",
    label: "KiCad",
    assetKinds: ["symbol", "footprint", "model"],
    unsupportedAssets: {},
    embeddedAssets: {},
  },
  {
    key: "altium",
    label: "Altium Designer",
    assetKinds: ["symbol", "footprint", "model"],
    unsupportedAssets: {
      model:
        "Altium stores 3D as a 3D Body inside the footprint's .PcbLib (an OLE2 binary), so it cannot be attached by reference; it must be embedded.",
    },
    embeddedAssets: {
      model: {
        container: "footprint",
        source: "model",
        requiresToolInstalled: true,
        reason: "A 3D body is written into the footprint's .PcbLib by Altium itself, so embedding needs Altium installed on this machine.",
      },
    },
  },
];

// The default tool the UI targets when the user has not chosen one.
export const DEFAULT_EDA_TOOL = "kicad";

export function edaTool(key: string): EdaToolSpec | undefined {
  return EDA_TOOLS.find((t) => t.key === key);
}
