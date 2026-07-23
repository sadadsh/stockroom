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
import { Text, useText } from "../lib/copy";
import { applySign, prettifyValue } from "../lib/specSchema";
import { Badge, Button } from "./primitives";
import { PulledDepth } from "./PulledDepth";
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
  // Seed the order number from the pulled distributor P/N (a Mouser link -> its 667-... number),
  // so a Mouser passive commits with its order number already filled instead of hand-typed.
  const [distributorPn, setDistributorPn] = useState(
    () => Object.values(result.dist_pns ?? {})[0] ?? "",
  );
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
  // Copy layer: attribute/callback strings resolve here; the visible copy below is <Text>.
  const toastNoResolve = useText("ingest.toast-no-resolve", "Could not resolve that passive.");
  const toastAddFailed = useText("ingest.toast-add-failed", "Add failed.");
  const kindPlaceholder = useText("ingest.kind-placeholder", "Select kind...");
  const pkgPlaceholder = useText("ingest.package-placeholder", "Select package...");
  const valuePlaceholder = useText("ingest.value-placeholder", "e.g. 10 k\u03a9");
  const tolerancePlaceholder = useText("ingest.tolerance-placeholder", "e.g. 1%");
  const datasheetHint = useText(
    "ingest.datasheet-hint",
    "Required. Paste the datasheet link if it was not pulled.",
  );
  const distPnPlaceholder = useText("ingest.distpn-placeholder", "Optional");
  const distPnHint = useText("ingest.distpn-hint", "The order number, if you have it.");

  const categories = Object.keys(facets.data?.by_category ?? {}).sort();
  const manufacturers = Object.keys(facets.data?.by_manufacturer ?? {}).sort();

  function body() {
    // A7: carry the FULL pulled result onto the passive commit (every spec, the price ladder, live
    // stock), the same enrichment result the non-passive path keeps - so the two branches no longer
    // diverge and a passive from a Mouser link keeps its depth, not just the offline decode.
    const specs: Record<string, string> = {};
    for (const [k, v] of Object.entries(result.specs)) {
      if (k === "product_url" || v == null) continue;
      specs[k] = String(v.value ?? "");
    }
    const stockNum =
      result.stock != null && Number.isFinite(Number(result.stock.value))
        ? Number(result.stock.value)
        : undefined;
    return {
      input,
      kind: kind || undefined,
      package: pkg || undefined,
      value: value.trim() || undefined,
      tolerance: tolerance.trim() || undefined,
      category: category.trim() || undefined,
      manufacturer: manufacturer.trim() || undefined,
      specs: Object.keys(specs).length ? specs : undefined,
      price_breaks: result.price_breaks?.length
        ? result.price_breaks.map((b) => ({ qty: b.qty, price: b.price }))
        : undefined,
      stock: stockNum,
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
      toast(err instanceof ApiError ? err.message : toastNoResolve, "err");
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
          toast(err instanceof ApiError ? err.message : toastAddFailed, "err"),
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
        <Badge tone="ok">
          <Text id="ingest.passive-badge">Passive</Text>
        </Badge>
        <span>
          <Text id="ingest.passive-msg">
            No files needed. It uses KiCad's built-in symbol, footprint and 3D model.
          </Text>
        </span>
      </div>

      {manual ? (
        <div className="flex flex-col gap-3 rounded-card border border-line2 bg-raise2 p-4">
          <p className="text-xs text-t3">
            <Text id="ingest.manual-hint">
              We could not match a stock footprint automatically. Choose the kind and package and it still adds with no files. Then preview again.
            </Text>
          </p>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <SelectField
              label="Kind"
              copyId="ingest.field-kind"
              value={kind}
              onChange={setKind}
              placeholder={kindPlaceholder}
              options={KIND_OPTIONS}
            />
            <SelectField
              label="Package"
              copyId="ingest.field-package"
              value={pkg}
              onChange={setPkg}
              placeholder={pkgPlaceholder}
              options={packages.map((p) => [p, p] as [string, string])}
            />
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <TextField label="Value" copyId="ingest.field-value" value={value} onChange={setValue} placeholder={valuePlaceholder} />
            <TextField label="Tolerance" copyId="ingest.field-tolerance" value={tolerance} onChange={setTolerance} placeholder={tolerancePlaceholder} />
          </div>
          <div>
            <Button variant="accent" onClick={doPreview} disabled={previewing || !kind || !pkg}>
              {previewing ? (
                <Text id="ingest.preview-busy">Resolving...</Text>
              ) : (
                <Text id="ingest.preview">Preview</Text>
              )}
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
                  {k}: {prettifyValue(applySign(k, String(v)))}
                </Badge>
              ))}
            </div>
          ) : null}

          <PulledDepth result={result} />

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <ComboField
              label="Category"
              copyId="ingest.field-category"
              value={category}
              onChange={setCategory}
              options={categories}
              listId="passive-category-options"
            />
            <ComboField
              label="Manufacturer"
              copyId="ingest.field-manufacturer"
              value={manufacturer}
              onChange={setManufacturer}
              options={manufacturers}
              listId="passive-manufacturer-options"
            />
          </div>

          <TextField
            label="Datasheet URL"
            copyId="ingest.field-datasheet-url"
            value={datasheetUrl}
            onChange={setDatasheetUrl}
            placeholder="https://..."
            hint={datasheetHint}
          />
          <TextField
            label="Distributor Part Number"
            copyId="ingest.field-distpn"
            value={distributorPn}
            onChange={setDistributorPn}
            placeholder={distPnPlaceholder}
            hint={distPnHint}
          />

          <div className="flex flex-col gap-1">
            <span className="text-xs text-t3">
              <Text id="ingest.buy-link">Buy Link</Text>
            </span>
            <span className="truncate rounded-control border border-line2 bg-field px-3 py-2 text-sm text-t2">
              {rec.purchase[0]?.url}
            </span>
          </div>

          {remaining.length > 0 ? (
            <div className="text-xs text-warn">
              <Text id="ingest.still-needed">Still needed to add:</Text> {remaining.join(", ")}.
            </div>
          ) : null}

          <div>
            <Button
              variant="accent"
              onClick={doAdd}
              disabled={add.isPending || remaining.length > 0}
            >
              {add.isPending ? (
                <Text id="ingest.commit-busy">Adding...</Text>
              ) : (
                <Text id="ingest.commit">Add to Components</Text>
              )}
            </Button>
          </div>
        </div>
      ) : previewing && !manual ? (
        <div className="text-sm text-t3">
          <Text id="ingest.resolving">Resolving the stock footprint and model...</Text>
        </div>
      ) : null}
    </div>
  );
}
