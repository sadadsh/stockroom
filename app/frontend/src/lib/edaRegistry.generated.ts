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
  /**
   * Record data this tool RECEIVES when a part is placed from the library, in the order
   * the tool's own artifact declares it. This is what the detail sheet's handoff band
   * renders, and it differs per tool: an Altium DbLib row carries price and stock
   * columns a KiCad schematic has no property for.
   */
  dataFields: DataFieldSpec[];
}

// One piece of record data a tool receives (mirrors stockroom.eda.registry.DataField).
export interface DataFieldSpec {
  /** The record-derived value this carries. The stable key to join on. */
  key: string;
  /** What a person calls it. */
  label: string;
  /** What THIS tool calls it: a KiCad property name, or an Altium Design Parameter. */
  toolField: string;
  /** Whether the tool shows this on the placed component by default. */
  visible: boolean;
  /**
   * Whether a placed component can be measured as MISSING this. False for a field the
   * tool receives structurally rather than as a fillable property (a KiCad symbol
   * arrives as the component's lib_id, and no component can exist without one).
   */
  passport: boolean;
}

// One row of the handoff band: a field, and every tool that receives it.
export interface UnionFieldSpec {
  key: string;
  label: string;
  /** Registry declaration order, so the tools read in a stable order. */
  tools: string[];
  /**
   * Who owns this value:
   *  - "curated": a PERSON maintains it. The handoff band shows exactly these.
   *  - "vendor": a distributor refresh supplies it; it is the Sourcing column's
   *    subject, carries a vendor attribution there, and changes on its own.
   *  - "derived": computed from other fields when the artifact is emitted and never
   *    stored, so there is no value to show and re-deriving it here would fork the rule.
   */
  origin: "curated" | "vendor" | "derived";
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
    dataFields: [
      { key: "mpn", label: "MPN", toolField: "MPN", visible: true, passport: true },
      { key: "manufacturer", label: "Manufacturer", toolField: "Manufacturer", visible: false, passport: true },
      { key: "datasheet", label: "Datasheet", toolField: "Datasheet", visible: false, passport: true },
      { key: "description", label: "Description", toolField: "Description", visible: false, passport: true },
      { key: "footprint", label: "Footprint", toolField: "Footprint", visible: false, passport: true },
      { key: "symbol", label: "Symbol", toolField: "lib_id", visible: false, passport: false },
    ],
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
    dataFields: [
      { key: "mpn", label: "MPN", toolField: "MPN", visible: true, passport: true },
      { key: "value", label: "Value", toolField: "Value", visible: true, passport: true },
      { key: "manufacturer", label: "Manufacturer", toolField: "Manufacturer", visible: true, passport: true },
      { key: "description", label: "Description", toolField: "[Description]", visible: true, passport: true },
      { key: "datasheet", label: "Datasheet", toolField: "ComponentLink1URL", visible: false, passport: true },
      { key: "supplier", label: "Supplier", toolField: "Supplier", visible: false, passport: true },
      { key: "supplier_part_number", label: "Supplier Part Number", toolField: "SupplierPartNumber", visible: false, passport: true },
      { key: "supplier_url", label: "Supplier Link", toolField: "SupplierURL", visible: false, passport: true },
      { key: "price", label: "Price", toolField: "Price", visible: false, passport: true },
      { key: "stock", label: "Stock", toolField: "Stock", visible: false, passport: true },
      { key: "lifecycle", label: "Lifecycle", toolField: "Lifecycle", visible: false, passport: true },
      { key: "category", label: "Category", toolField: "Category", visible: false, passport: true },
      { key: "symbol", label: "Symbol", toolField: "[Library Ref]", visible: false, passport: true },
      { key: "footprint", label: "Footprint", toolField: "[Footprint Ref]", visible: false, passport: true },
    ],
  },
];

/**
 * Every record field ANY registered tool consumes, deduplicated, each naming its
 * consumers. The handoff band renders exactly this, so a third EDA tool joins that band
 * by declaring `data_fields` in the Python registry - with no edit here and none in the
 * component. Order is registry declaration order, never alphabetical: the band must open
 * on the part number, not on "Category".
 */
export const EDA_DATA_FIELDS: UnionFieldSpec[] = [
  { key: "mpn", label: "MPN", tools: ["kicad", "altium"], origin: "curated" },
  { key: "manufacturer", label: "Manufacturer", tools: ["kicad", "altium"], origin: "curated" },
  { key: "datasheet", label: "Datasheet", tools: ["kicad", "altium"], origin: "curated" },
  { key: "description", label: "Description", tools: ["kicad", "altium"], origin: "curated" },
  { key: "footprint", label: "Footprint", tools: ["kicad", "altium"], origin: "curated" },
  { key: "symbol", label: "Symbol", tools: ["kicad", "altium"], origin: "curated" },
  { key: "value", label: "Value", tools: ["altium"], origin: "derived" },
  { key: "supplier", label: "Supplier", tools: ["altium"], origin: "vendor" },
  { key: "supplier_part_number", label: "Supplier Part Number", tools: ["altium"], origin: "vendor" },
  { key: "supplier_url", label: "Supplier Link", tools: ["altium"], origin: "vendor" },
  { key: "price", label: "Price", tools: ["altium"], origin: "vendor" },
  { key: "stock", label: "Stock", tools: ["altium"], origin: "vendor" },
  { key: "lifecycle", label: "Lifecycle", tools: ["altium"], origin: "vendor" },
  { key: "category", label: "Category", tools: ["altium"], origin: "curated" },
];

// The default tool the UI targets when the user has not chosen one.
export const DEFAULT_EDA_TOOL = "kicad";

export function edaTool(key: string): EdaToolSpec | undefined {
  return EDA_TOOLS.find((t) => t.key === key);
}
