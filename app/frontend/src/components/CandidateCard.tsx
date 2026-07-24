/**
 * One staged part in the Add A Part flow: a candidate produced by inspecting a vendor
 * ZIP (its symbol/footprint/3D), edited until the complete-to-add gate passes, then
 * committed. When it was seeded from a pulled purchase link (the non-passive branch),
 * the pulled identity/specs/purchase already ride on the candidate and the datasheet
 * link is pre-filled, so the only thing the user still supplies is the asset files.
 * A known datasheet link counts as the datasheet, so nothing more is needed for it.
 */
import { useState } from "react";
import { ApiError } from "../api/client";
import { useIngestCommit } from "../api/queries";
import type { PartDetail, StagingCandidate } from "../api/types";
import type { ToastTone } from "../lib/toast";
import { Text, useText } from "../lib/copy";
import { Badge, Button, Card, Dot } from "./primitives";
import { ProductPhoto, productPhotoUrl } from "./ProductPhoto";

const EMPTY_PROVENANCE = {
  source: "manual",
  source_url: "",
  original_zip_sha256: "",
  ingested_at: "",
};

// Seed the candidate's datasheet link from the pulled result so editing the field
// writes straight onto the candidate that gets committed (the link rides provenance).
function seedDatasheet(candidate: StagingCandidate, url: string): StagingCandidate {
  if (!url || candidate.provenance?.source_url) return candidate;
  return {
    ...candidate,
    provenance: { ...(candidate.provenance ?? EMPTY_PROVENANCE), source_url: url },
  };
}

// Sentence case for a status phrase; Title Case for a required-field label.
const sentence = (s: string) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);
const titleCase = (s: string) =>
  s.replace(/\b\w/g, (ch) => ch.toUpperCase());

export function CandidateCard({
  candidate,
  initialDatasheetUrl,
  onCommitted,
  toast,
}: {
  candidate: StagingCandidate;
  initialDatasheetUrl?: string;
  // Fires with the CREATED part so the Add flow can continue into its Complete Part
  // window (the guided both-format capture) instead of dead-ending on a toast.
  onCommitted: (created: PartDetail) => void;
  toast: (message: string, tone?: ToastTone) => void;
}) {
  const [c, setC] = useState<StagingCandidate>(() =>
    seedDatasheet(candidate, initialDatasheetUrl ?? ""),
  );
  const [missing, setMissing] = useState<string[]>([]);
  const commit = useIngestCommit();
  // Copy layer: toast strings resolve here so the callbacks fire the override, not the literal.
  const toastAdded = useText("ingest.toast-added", "Added");
  const toastIncomplete = useText("ingest.toast-incomplete", "Still incomplete");
  const toastCouldNotAdd = useText("ingest.toast-could-not-add", "Could not add");

  function set<K extends keyof StagingCandidate>(key: K, value: StagingCandidate[K]) {
    setC((prev) => ({ ...prev, [key]: value }));
  }

  function setDatasheetUrl(url: string) {
    setC((prev) => ({
      ...prev,
      provenance: { ...(prev.provenance ?? EMPTY_PROVENANCE), source_url: url },
    }));
  }

  function handleCommit() {
    setMissing([]);
    commit.mutate(c, {
      onSuccess: (created) => {
        toast(`${toastAdded} ${c.display_name || "part"}`, "ok");
        onCommitted(created);
      },
      onError: (err) => {
        if (err instanceof ApiError && err.missing && err.missing.length > 0) {
          setMissing(err.missing);
          toast(toastIncomplete, "err");
        } else {
          toast(err instanceof ApiError ? err.message : toastCouldNotAdd, "err");
        }
      },
    });
  }

  // Guard the array itself: a candidate may arrive without a purchase field.
  const purchaseUrl = c.purchase?.[0]?.url ?? "";
  // the pulled product photo rides the candidate's specs (rendered, never a URL row)
  const photoUrl = productPhotoUrl(c.specs);
  const datasheetUrl = c.provenance?.source_url ?? "";
  const chosenFootprint = c.footprint_variants[c.chosen_footprint_index] ?? "";
  // A datasheet is satisfied by a stored PDF OR a known link (mirrors the backend gate).
  const datasheetPresent = !!c.datasheet_path || !!datasheetUrl;

  // Only surface a gap the candidate has not already resolved (a footprint chosen,
  // a model present, a datasheet linked), and read it as a sentence, not lowercase.
  const shownGaps = c.gaps.filter((g) => {
    if (g.includes("datasheet") && datasheetPresent) return false;
    if (g.includes("3D model") && c.model_path) return false;
    if (g.includes("footprint") && chosenFootprint) return false;
    return true;
  });

  return (
    <Card data-dev-id="ingest.candidate" data-candidate className="px-4 py-4">
      {/* the action leads (owner 2026-07-24: burying Add at the bottom of a long card
          among the info made the flow confusing): the part's name + the ONE accent
          button on top, the editable review fields below it */}
      <div className="mb-3.5 flex items-center justify-between gap-3 border-b border-line pb-3">
        {photoUrl ? (
          <div
            data-dev-id="ingest.candidate-photo"
            className="h-[42px] w-[42px] flex-none overflow-hidden rounded-control border border-line bg-stage p-0.5"
          >
            <ProductPhoto key={photoUrl} url={photoUrl} alt="Product photo" />
          </div>
        ) : null}
        <span className="min-w-0 truncate text-sm font-semibold text-t1">
          {c.display_name || c.mpn || "New Part"}
        </span>
        <Button
          variant="accent"
          onClick={handleCommit}
          disabled={commit.isPending}
          className="flex-none"
        >
          {commit.isPending ? (
            <Text id="ingest.commit-busy">Adding...</Text>
          ) : (
            <Text id="ingest.commit">Add to Components</Text>
          )}
        </Button>
      </div>
      <div className="grid gap-2.5">
        <Field label="Name" copyId="ingest.field-name" value={c.display_name} onChange={(v) => set("display_name", v)} />
        <Field label="Part Number" copyId="ingest.field-mpn" value={c.mpn} onChange={(v) => set("mpn", v)} mono />
        <Field
          label="Manufacturer"
          copyId="ingest.field-manufacturer"
          value={c.manufacturer}
          onChange={(v) => set("manufacturer", v)}
        />
        <Field label="Category" copyId="ingest.field-category" value={c.category} onChange={(v) => set("category", v)} />
        <Field
          label="Description"
          copyId="ingest.field-description"
          value={c.description}
          onChange={(v) => set("description", v)}
        />
        <Field
          label="Purchase URL"
          copyId="ingest.field-purchase-url"
          value={purchaseUrl}
          mono
          onChange={(v) =>
            set("purchase", v.trim() ? [{ vendor: "manual", url: v.trim() }] : [])
          }
        />
        <Field label="Datasheet URL" copyId="ingest.field-datasheet-url" value={datasheetUrl} mono onChange={setDatasheetUrl} />
        {c.footprint_variants.length > 1 ? (
          <div className="flex items-center gap-3">
            <span className="w-[116px] flex-none text-xs text-t3">
              <Text id="ingest.field-footprint">Footprint</Text>
            </span>
            <select
              aria-label="Footprint"
              value={c.chosen_footprint_index}
              onChange={(e) => set("chosen_footprint_index", Number(e.target.value))}
              className="rounded-control border border-line2 bg-field px-2 py-1 text-base text-t1 outline-none focus:border-acc"
            >
              {c.footprint_variants.map((fp, i) => (
                <option key={fp} value={i}>
                  {baseName(fp)}
                </option>
              ))}
            </select>
          </div>
        ) : null}
      </div>

      {/* asset presence */}
      <div className="mt-3.5 flex flex-wrap gap-2">
        <Asset label="Symbol" copyId="ingest.asset-symbol" present={!!c.symbol_name} />
        <Asset label="Footprint" copyId="ingest.asset-footprint" present={!!chosenFootprint} />
        <Asset label="3D Model" copyId="ingest.asset-model" present={!!c.model_path} />
        <Asset label="Datasheet" copyId="ingest.asset-datasheet" present={datasheetPresent} />
      </div>

      {shownGaps.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {shownGaps.map((g) => (
            <Badge key={g} tone="warn">
              {sentence(g)}
            </Badge>
          ))}
        </div>
      ) : null}

      {missing.length > 0 ? (
        <div className="mt-3">
          <div className="mb-1.5 text-xs text-err">
            <Text id="ingest.still-needs">This part still needs:</Text>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {missing.map((m) => (
              <Badge key={m} tone="err">
                {titleCase(m)}
              </Badge>
            ))}
          </div>
        </div>
      ) : null}

    </Card>
  );
}

function Field({
  label,
  copyId,
  value,
  onChange,
  mono,
}: {
  label: string;
  copyId: string;
  value: string;
  onChange: (value: string) => void;
  mono?: boolean;
}) {
  return (
    <div className="flex items-center gap-3">
      <span className="w-[116px] flex-none text-xs text-t3">
        <Text id={copyId}>{label}</Text>
      </span>
      <input
        aria-label={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={
          "min-w-0 flex-1 rounded-control border border-line2 bg-field px-3 py-1.5 text-base text-t1 outline-none focus:border-acc " +
          (mono ? "tnum" : "")
        }
      />
    </div>
  );
}

function Asset({ label, copyId, present }: { label: string; copyId: string; present: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-control bg-raise px-2.5 py-1 text-2xs text-t2">
      <Dot tone={present ? "ok" : "warn"} />
      <Text id={copyId}>{label}</Text>
    </span>
  );
}

function baseName(path: string): string {
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1] || path;
}
