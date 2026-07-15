/**
 * Add a passive (R/C/L) with NO files. Paste an MPN or a Mouser product link and
 * the backend decodes value/tolerance/package/power offline and references KiCad's
 * stock symbol/footprint/3D, so nothing is downloaded or dropped. The only fields a
 * passive needs are a datasheet URL and a purchase link (Mouser); the category and
 * manufacturer are existing-or-add-new comboboxes fed by the library facets.
 */
import { useState } from "react";
import { ApiError, api } from "../api/client";
import { useFacetsQuery, usePassiveAdd } from "../api/queries";
import type { PassivePreview } from "../api/types";
import type { ToastTone } from "../lib/toast";
import { Badge, Button, Card, Dot, Eyebrow } from "./primitives";

const ASSET_KEYS = new Set(["Symbol", "Footprint", "3D Model"]);

export function PassiveAddCard({
  toast,
}: {
  toast: (message: string, tone?: ToastTone) => void;
}) {
  const [input, setInput] = useState("");
  const [preview, setPreview] = useState<PassivePreview | null>(null);
  const [category, setCategory] = useState("");
  const [manufacturer, setManufacturer] = useState("");
  const [datasheetUrl, setDatasheetUrl] = useState("");
  const [previewing, setPreviewing] = useState(false);
  const facets = useFacetsQuery();
  const add = usePassiveAdd();

  const categories = Object.keys(facets.data?.by_category ?? {}).sort();
  const manufacturers = Object.keys(facets.data?.by_manufacturer ?? {}).sort();

  async function doPreview() {
    const value = input.trim();
    if (!value || previewing) return;
    setPreviewing(true);
    try {
      const p = await api.passivePreview({ input: value });
      setPreview(p);
      setCategory(p.record.category);
      setManufacturer(p.record.manufacturer);
      setDatasheetUrl(p.record.datasheet?.source_url ?? "");
    } catch (err) {
      setPreview(null);
      toast(
        err instanceof ApiError ? err.message : "Could not decode that passive.",
        "err",
      );
    } finally {
      setPreviewing(false);
    }
  }

  function reset() {
    setInput("");
    setPreview(null);
    setCategory("");
    setManufacturer("");
    setDatasheetUrl("");
  }

  function doAdd() {
    if (!preview || add.isPending) return;
    add.mutate(
      {
        input: input.trim(),
        category: category.trim() || undefined,
        manufacturer: manufacturer.trim() || undefined,
        datasheet_url: datasheetUrl.trim() || undefined,
      },
      {
        onSuccess: (rec) => {
          toast(`Added ${rec.display_name}`, "ok");
          reset();
        },
        onError: (err) =>
          toast(err instanceof ApiError ? err.message : "Add failed.", "err"),
      },
    );
  }

  const rec = preview?.record;
  // The backend computed gaps for the un-filled record; recompute the datasheet gap
  // live against what the user has typed so the hint stays honest.
  const remaining = (preview?.gaps ?? []).filter((g) =>
    g === "datasheet" ? !datasheetUrl.trim() : true,
  );
  const specEntries = rec
    ? Object.entries(rec.specs).filter(([k]) => !ASSET_KEYS.has(k))
    : [];

  return (
    <Card className="px-4 py-3.5">
      <Eyebrow>Add Passive (No Files)</Eyebrow>
      <p className="mb-3 mt-1 text-xs text-t3">
        Paste an MPN or a Mouser product link. Resistors, capacitors and inductors
        add with no files: the symbol, footprint and 3D come from KiCad's stock
        libraries.
      </p>
      <div className="flex items-center gap-3">
        <input
          aria-label="Passive MPN or Mouser URL"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") doPreview();
          }}
          placeholder="ERJ-P03F1101V or a Mouser product link"
          disabled={previewing}
          className="min-w-0 flex-1 rounded-control border border-line2 bg-field px-3 py-2 text-base text-t1 outline-none focus:border-acc disabled:opacity-50"
        />
        <Button
          variant="accent"
          onClick={doPreview}
          disabled={previewing || !input.trim()}
          className="flex-none"
        >
          {previewing ? "Decoding..." : "Preview"}
        </Button>
      </div>

      {rec ? (
        <div className="mt-4 flex flex-col gap-4 rounded-card border border-line2 bg-raise2 p-4">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="text-base font-medium text-t1">{rec.mpn}</span>
            <span className="text-sm text-t2">{rec.description}</span>
          </div>

          {specEntries.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {specEntries.map(([k, v]) => (
                <Badge key={k} tone="neutral">
                  {k}: {String(v)}
                </Badge>
              ))}
            </div>
          ) : null}

          <div className="grid grid-cols-1 gap-1.5 text-xs sm:grid-cols-[max-content_1fr] sm:gap-x-4">
            <AssetRow label="Symbol" value={`${rec.symbol?.lib}:${rec.symbol?.name}`} present={preview?.stock_present ?? false} />
            <AssetRow label="Footprint" value={`${rec.footprint?.lib}:${rec.footprint?.name}`} present={preview?.stock_present ?? false} />
            <AssetRow label="3D Model" value={String(rec.specs["3D Model"] ?? "")} present={preview?.stock_present ?? false} />
          </div>

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
            hint="Required. Paste the datasheet link (Mouser blocks auto-fetch)."
          />

          <div className="flex flex-col gap-1">
            <span className="text-xs text-t3">Buy Link</span>
            <span className="truncate rounded-control border border-line2 bg-field px-3 py-2 text-sm text-t2">
              {rec.purchase[0]?.url}
            </span>
          </div>

          {remaining.length > 0 ? (
            <div className="text-xs text-warn">
              Still needed to add: {remaining.join(", ")}.
            </div>
          ) : null}

          <div className="flex items-center gap-3">
            <Button
              variant="accent"
              onClick={doAdd}
              disabled={add.isPending}
              className="flex-none"
            >
              {add.isPending ? "Adding..." : "Add To Library"}
            </Button>
            <Button onClick={reset} disabled={add.isPending} className="flex-none">
              Cancel
            </Button>
          </div>
        </div>
      ) : null}
    </Card>
  );
}

function AssetRow({
  label,
  value,
  present,
}: {
  label: string;
  value: string;
  present: boolean;
}) {
  return (
    <>
      <span className="text-t3">{label}</span>
      <span className="flex items-center gap-2 text-t2">
        <Dot tone={present ? "ok" : "neutral"} />
        <span className="truncate font-mono">{value}</span>
      </span>
    </>
  );
}

function ComboField({
  label,
  value,
  onChange,
  options,
  listId,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
  listId: string;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-t3">{label}</span>
      <input
        list={listId}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-control border border-line2 bg-field px-3 py-2 text-base text-t1 outline-none focus:border-acc"
      />
      <datalist id={listId}>
        {options.map((o) => (
          <option key={o} value={o} />
        ))}
      </datalist>
    </label>
  );
}

function TextField({
  label,
  value,
  onChange,
  placeholder,
  hint,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  hint?: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="flex flex-col gap-1">
        <span className="text-xs text-t3">{label}</span>
        <input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className="rounded-control border border-line2 bg-field px-3 py-2 text-base text-t1 outline-none focus:border-acc"
        />
      </label>
      {hint ? <span className="text-xs text-t3">{hint}</span> : null}
    </div>
  );
}
