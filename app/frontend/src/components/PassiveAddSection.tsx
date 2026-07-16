/**
 * The passive branch of the unified Add-A-Part flow. The pulled product page was
 * determined to be a file-less passive (R/C/L), so this resolves its KiCad stock
 * symbol/footprint/3D, shows the built-in footprint + 3D model (the owner: for a
 * passive show the footprint and model; the symbol matters less), lets the datasheet /
 * category / manufacturer be confirmed, and adds it with no dropped files. A passive
 * whose case did not resolve reveals a package picker rather than dropping the part.
 */
import { useEffect, useRef, useState } from "react";
import { ApiError, api } from "../api/client";
import { useFacetsQuery, usePassiveAdd } from "../api/queries";
import type { EnrichmentResult, PassiveAddPlan, PassivePreviewOk, SourcedField } from "../api/types";
import type { ToastTone } from "../lib/toast";
import { Badge, Button } from "./primitives";
import { StockAssetPreview } from "./StockAssetPreview";
import { ComboField, SelectField, TextField } from "./formFields";

const ASSET_KEYS = new Set(["Symbol", "Footprint", "3D Model"]);
const KIND_OPTIONS: [string, string][] = [
  ["resistor", "Resistor"],
  ["capacitor", "Capacitor"],
  ["inductor", "Inductor"],
];

function sourced(s: SourcedField | null | undefined): string {
  return s == null ? "" : String(s.value ?? "");
}

export function PassiveAddSection({
  result,
  plan,
  input,
  onAdded,
  toast,
}: {
  result: EnrichmentResult;
  plan: PassiveAddPlan;
  input: string;
  onAdded: (name: string) => void;
  toast: (message: string, tone?: ToastTone) => void;
}) {
  const [category, setCategory] = useState("");
  const [manufacturer, setManufacturer] = useState("");
  const [datasheetUrl, setDatasheetUrl] = useState("");
  const [distributorPn, setDistributorPn] = useState("");
  const [preview, setPreview] = useState<PassivePreviewOk | null>(null);
  const [previewing, setPreviewing] = useState(false);
  // The rare manual path: a detected passive whose case did not resolve to a stock
  // footprint. The pickers are revealed pre-filled with what the plan already knew.
  const [manual, setManual] = useState(false);
  const [packages, setPackages] = useState<string[]>([]);
  const [kind, setKind] = useState(plan.kind);
  const [pkg, setPkg] = useState(plan.package);
  const [value, setValue] = useState(plan.value);
  const [tolerance, setTolerance] = useState(plan.tolerance);
  const facets = useFacetsQuery();
  const add = usePassiveAdd();
  const ran = useRef(false);

  const categories = Object.keys(facets.data?.by_category ?? {}).sort();
  const manufacturers = Object.keys(facets.data?.by_manufacturer ?? {}).sort();

  function body() {
    return {
      input,
      kind: kind || undefined,
      package: pkg || undefined,
      value: value.trim() || undefined,
      tolerance: tolerance.trim() || undefined,
      category: category.trim() || undefined,
      manufacturer: manufacturer.trim() || undefined,
    };
  }

  async function doPreview() {
    if (previewing) return;
    setPreviewing(true);
    try {
      const p = await api.passivePreview(body());
      if (p.status === "needs_input") {
        setManual(true);
        setPackages(p.packages);
        setPreview(null);
        if (p.suggested_kind && !kind) setKind(p.suggested_kind);
      } else {
        setPreview(p);
        setCategory((c) => c || p.record.category);
        setManufacturer(
          (m) => m || sourced(result.manufacturer) || p.record.manufacturer,
        );
        setDatasheetUrl(
          (d) => d || sourced(result.datasheet_url) || p.record.datasheet?.source_url || "",
        );
      }
    } catch (err) {
      setPreview(null);
      toast(err instanceof ApiError ? err.message : "Could not resolve that passive.", "err");
    } finally {
      setPreviewing(false);
    }
  }

  // Resolve the stock assets once as soon as the branch mounts (the part was already
  // determined passive), so the footprint + 3D show without a second click.
  useEffect(() => {
    if (ran.current) return;
    ran.current = true;
    void doPreview();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function doAdd() {
    if (!preview || add.isPending) return;
    add.mutate(
      {
        ...body(),
        datasheet_url: datasheetUrl.trim() || undefined,
        purchase_part_number: distributorPn.trim() || undefined,
      },
      {
        onSuccess: (rec) => onAdded(rec.display_name),
        onError: (err) =>
          toast(err instanceof ApiError ? err.message : "Add failed.", "err"),
      },
    );
  }

  const rec = preview?.record;
  const fpLibId = rec?.footprint ? `${rec.footprint.lib}:${rec.footprint.name}` : "";
  const specEntries = rec
    ? Object.entries(rec.specs).filter(([k]) => !ASSET_KEYS.has(k))
    : [];
  // Recompute the datasheet/manufacturer gaps live against what is typed.
  const remaining = (preview?.gaps ?? []).filter((g) => {
    if (g === "datasheet") return !datasheetUrl.trim();
    if (g === "manufacturer") return !manufacturer.trim();
    return true;
  });

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2 text-sm text-t2">
        <Badge tone="ok">Passive</Badge>
        <span>No files needed. It uses KiCad's built-in symbol, footprint and 3D model.</span>
      </div>

      {manual ? (
        <div className="flex flex-col gap-3 rounded-card border border-line2 bg-raise2 p-4">
          <p className="text-xs text-t3">
            We could not match a stock footprint automatically. Choose the kind and
            package and it still adds with no files. Then preview again.
          </p>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <SelectField
              label="Kind"
              value={kind}
              onChange={setKind}
              placeholder="Select kind..."
              options={KIND_OPTIONS}
            />
            <SelectField
              label="Package"
              value={pkg}
              onChange={setPkg}
              placeholder="Select package..."
              options={packages.map((p) => [p, p] as [string, string])}
            />
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <TextField label="Value" value={value} onChange={setValue} placeholder="e.g. 10 kΩ" />
            <TextField label="Tolerance" value={tolerance} onChange={setTolerance} placeholder="e.g. 1%" />
          </div>
          <div>
            <Button variant="accent" onClick={doPreview} disabled={previewing || !kind || !pkg}>
              {previewing ? "Resolving..." : "Preview"}
            </Button>
          </div>
        </div>
      ) : null}

      {rec ? (
        <div className="flex flex-col gap-4 rounded-card border border-line2 bg-raise2 p-4">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="text-base font-medium text-t1">{rec.mpn}</span>
            <span className="text-sm text-t2">{rec.description}</span>
          </div>

          <StockAssetPreview footprintLibId={fpLibId} />

          {specEntries.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {specEntries.map(([k, v]) => (
                <Badge key={k} tone="neutral">
                  {k}: {String(v)}
                </Badge>
              ))}
            </div>
          ) : null}

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <ComboField
              label="Category"
              value={category}
              onChange={setCategory}
              options={categories}
              listId="passive-category-options"
            />
            <ComboField
              label="Manufacturer"
              value={manufacturer}
              onChange={setManufacturer}
              options={manufacturers}
              listId="passive-manufacturer-options"
            />
          </div>

          <TextField
            label="Datasheet URL"
            value={datasheetUrl}
            onChange={setDatasheetUrl}
            placeholder="https://..."
            hint="Required. Paste the datasheet link if it was not pulled."
          />
          <TextField
            label="Distributor Part Number"
            value={distributorPn}
            onChange={setDistributorPn}
            placeholder="Optional"
            hint="The order number, if you have it."
          />

          <div className="flex flex-col gap-1">
            <span className="text-xs text-t3">Buy Link</span>
            <span className="truncate rounded-control border border-line2 bg-field px-3 py-2 text-sm text-t2">
              {rec.purchase[0]?.url}
            </span>
          </div>

          {remaining.length > 0 ? (
            <div className="text-xs text-warn">Still needed to add: {remaining.join(", ")}.</div>
          ) : null}

          <div>
            <Button
              variant="accent"
              onClick={doAdd}
              disabled={add.isPending || remaining.length > 0}
            >
              {add.isPending ? "Adding..." : "Add to Components"}
            </Button>
          </div>
        </div>
      ) : previewing && !manual ? (
        <div className="text-sm text-t3">Resolving the stock footprint and model...</div>
      ) : null}
    </div>
  );
}
