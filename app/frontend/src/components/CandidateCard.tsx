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
import type { StagingCandidate } from "../api/types";
import type { ToastTone } from "../lib/toast";
import { Badge, Button, Card, Dot } from "./primitives";

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
  onCommitted: () => void;
  toast: (message: string, tone?: ToastTone) => void;
}) {
  const [c, setC] = useState<StagingCandidate>(() =>
    seedDatasheet(candidate, initialDatasheetUrl ?? ""),
  );
  const [missing, setMissing] = useState<string[]>([]);
  const commit = useIngestCommit();

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
      onSuccess: () => {
        toast(`Added ${c.display_name || "part"}`, "ok");
        onCommitted();
      },
      onError: (err) => {
        if (err instanceof ApiError && err.missing && err.missing.length > 0) {
          setMissing(err.missing);
          toast("Still Incomplete", "err");
        } else {
          toast(err instanceof ApiError ? err.message : "Could not add", "err");
        }
      },
    });
  }

  // Guard the array itself: a candidate may arrive without a purchase field.
  const purchaseUrl = c.purchase?.[0]?.url ?? "";
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
    <Card data-candidate className="px-4 py-4">
      <div className="grid gap-2.5">
        <Field label="Name" value={c.display_name} onChange={(v) => set("display_name", v)} />
        <Field label="Part Number" value={c.mpn} onChange={(v) => set("mpn", v)} mono />
        <Field
          label="Manufacturer"
          value={c.manufacturer}
          onChange={(v) => set("manufacturer", v)}
        />
        <Field label="Category" value={c.category} onChange={(v) => set("category", v)} />
        <Field
          label="Description"
          value={c.description}
          onChange={(v) => set("description", v)}
        />
        <Field
          label="Purchase URL"
          value={purchaseUrl}
          mono
          onChange={(v) =>
            set("purchase", v.trim() ? [{ vendor: "manual", url: v.trim() }] : [])
          }
        />
        <Field label="Datasheet URL" value={datasheetUrl} mono onChange={setDatasheetUrl} />
        {c.footprint_variants.length > 1 ? (
          <div className="flex items-center gap-3">
            <span className="w-[116px] flex-none text-xs text-t3">Footprint</span>
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
        <Asset label="Symbol" present={!!c.symbol_name} />
        <Asset label="Footprint" present={!!chosenFootprint} />
        <Asset label="3D Model" present={!!c.model_path} />
        <Asset label="Datasheet" present={datasheetPresent} />
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
            This part still needs:
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

      <div className="mt-4 flex items-center justify-end">
        <Button
          variant="accent"
          onClick={handleCommit}
          disabled={commit.isPending}
        >
          {commit.isPending ? "Adding..." : "Add to Components"}
        </Button>
      </div>
    </Card>
  );
}

function Field({
  label,
  value,
  onChange,
  mono,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  mono?: boolean;
}) {
  return (
    <div className="flex items-center gap-3">
      <span className="w-[116px] flex-none text-xs text-t3">{label}</span>
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

function Asset({ label, present }: { label: string; present: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-control bg-raise px-2.5 py-1 text-2xs text-t2">
      <Dot tone={present ? "ok" : "warn"} />
      {label}
    </span>
  );
}

function baseName(path: string): string {
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1] || path;
}
