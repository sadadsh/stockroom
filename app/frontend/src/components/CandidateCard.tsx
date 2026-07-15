/**
 * One staged part in the Add-A-Part flow: a candidate produced by inspecting a vendor
 * ZIP (its symbol/footprint/3D), edited until the complete-to-add gate passes, then
 * committed. When it was seeded from a pulled purchase link (the non-passive branch),
 * the pulled identity/specs/purchase already ride on the candidate and the datasheet
 * link is pre-filled, so the only thing the user still supplies is the asset files.
 */
import { useEffect, useState } from "react";
import { ApiError, api } from "../api/client";
import { useIngestCommit } from "../api/queries";
import type { IngestEnrichResult, StagingCandidate } from "../api/types";
import { useJob } from "../lib/useJob";
import type { ToastTone } from "../lib/toast";
import { Badge, Button, Card, Dot } from "./primitives";
import { EnrichIcon } from "./icons";

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
  const [c, setC] = useState<StagingCandidate>(candidate);
  const [missing, setMissing] = useState<string[]>([]);
  const commit = useIngestCommit();
  // Autofill: paste a datasheet link (or attach the PDF) and a purchase link, and
  // the backend fills the remaining identity from the datasheet + enrichment.
  const enrich = useJob<IngestEnrichResult>();
  const [dsUrl, setDsUrl] = useState(initialDatasheetUrl ?? "");
  const [dsFile, setDsFile] = useState<string | null>(null);
  const [notes, setNotes] = useState<string[]>([]);
  const filling = enrich.status === "running";

  function set<K extends keyof StagingCandidate>(key: K, value: StagingCandidate[K]) {
    setC((prev) => ({ ...prev, [key]: value }));
  }

  async function handleAutofill() {
    if (filling) return;
    setNotes([]);
    try {
      const { job_id } = await api.ingestEnrich({
        candidate: c,
        datasheet_url: dsUrl.trim() || undefined,
        // Send the purchase link explicitly so the backend derives its real vendor
        // (Mouser/DigiKey/LCSC from the host) and scrapes that product page to fill
        // the rest of the identity, not just what a datasheet holds.
        purchase_url: (c.purchase?.[0]?.url ?? "").trim() || undefined,
        datasheet_file: dsFile ?? undefined,
      });
      await enrich.run(job_id);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Autofill failed", "err");
    }
  }

  async function attachPdf() {
    const hostApi = (
      window as unknown as {
        pywebview?: { api?: { pick_datasheet_file?: () => Promise<string[]> } };
      }
    ).pywebview?.api;
    if (!hostApi?.pick_datasheet_file) {
      toast(
        "Open Stockroom as the app to attach a PDF from disk, or paste its link instead.",
        "neutral",
      );
      return;
    }
    try {
      const paths = await hostApi.pick_datasheet_file();
      if (paths && paths.length > 0) setDsFile(paths[0]);
    } catch {
      // the picker was cancelled or is unavailable; nothing to do
    }
  }

  useEffect(() => {
    if (enrich.status === "done" && enrich.result) {
      setC(enrich.result.candidate);
      setNotes(enrich.result.notes);
      const n = enrich.result.filled.length;
      toast(
        n > 0 ? `Filled ${n} field${n === 1 ? "" : "s"}.` : "Nothing new was found.",
        n > 0 ? "ok" : "neutral",
      );
    }
  }, [enrich.status, enrich.result, toast]);

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
  const chosenFootprint = c.footprint_variants[c.chosen_footprint_index] ?? "";

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
        <Field label="Datasheet URL" value={dsUrl} mono onChange={setDsUrl} />
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
        <Asset label="Datasheet" present={!!c.datasheet_path} />
      </div>

      {c.gaps.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {c.gaps.map((g) => (
            <Badge key={g} tone="warn">
              {g}
            </Badge>
          ))}
        </div>
      ) : null}

      {notes.length > 0 ? (
        <div className="mt-3 flex flex-col gap-1">
          {notes.map((n) => (
            <div key={n} className="text-xs text-warn">
              {n}
            </div>
          ))}
        </div>
      ) : null}

      {enrich.status === "error" ? (
        <div className="mt-3 text-xs text-err">Autofill failed. {enrich.error}</div>
      ) : null}

      {missing.length > 0 ? (
        <div className="mt-3">
          <div className="mb-1.5 text-xs text-err">
            Still needs before it can be added
          </div>
          <div className="flex flex-wrap gap-1.5">
            {missing.map((m) => (
              <Badge key={m} tone="err">
                {m}
              </Badge>
            ))}
          </div>
        </div>
      ) : null}

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <Button
            onClick={handleAutofill}
            disabled={filling || commit.isPending}
            icon={<EnrichIcon />}
          >
            {filling ? "Filling..." : "Autofill"}
          </Button>
          <Button small onClick={attachPdf} disabled={filling}>
            Attach PDF
          </Button>
          {dsFile ? (
            <span className="max-w-[200px] truncate text-xs text-t3">{baseName(dsFile)}</span>
          ) : null}
        </div>
        <Button
          variant="accent"
          onClick={handleCommit}
          disabled={commit.isPending || filling}
        >
          {commit.isPending ? "Adding..." : "Add To Library"}
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
