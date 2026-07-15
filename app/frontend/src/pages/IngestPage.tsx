/**
 * The Ingest page: add parts to the library. A part enters by dropping a vendor
 * ZIP anywhere in the window (the global drop overlay hands the native paths here)
 * or by pasting LCSC part ids. Either way the backend inspects the input into
 * staging candidates over an SSE job; the user reviews and edits each candidate,
 * then commits it. The complete-to-add gate is honest: a 422 lists exactly which
 * required fields are still missing, shown on the candidate, and nothing is added
 * until it passes.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "../api/client";
import { useIngestCommit } from "../api/queries";
import type { IngestEnrichResult, StagingCandidate } from "../api/types";
import { useJob, type JobProgress } from "../lib/useJob";
import { useToast, type ToastTone } from "../lib/toast";
import { onQueuedPaths } from "../lib/ingestQueue";
import { Badge, Button, Card, Dot, Eyebrow } from "../components/primitives";
import { EnrichIcon, UploadIcon } from "../components/icons";

// Each staged candidate carries a stable id assigned on load, so committing or
// removing one never shifts another's React key (which would remount its sibling
// cards and discard their in-progress edits).
interface Staged {
  id: number;
  candidate: StagingCandidate;
}

export function IngestPage() {
  const [lcsc, setLcsc] = useState("");
  // null = nothing inspected yet; [] = inspected, found nothing.
  const [staged, setStaged] = useState<Staged[] | null>(null);
  const nextId = useRef(0);
  const job = useJob<StagingCandidate[]>();
  const { toast } = useToast();

  const inspect = useCallback(
    async (paths: string[], lcscIds: string[]) => {
      setStaged(null);
      job.reset();
      try {
        const { job_id } = await api.ingestInspect(paths, lcscIds);
        await job.run(job_id);
      } catch (err) {
        toast(err instanceof ApiError ? err.message : "Inspect failed", "err");
      }
    },
    [job, toast],
  );

  // Native file picker for vendor ZIPs (the reliable path): the host exposes
  // window.pywebview.api.pick_ingest_files, which returns real filesystem paths straight into
  // the normal inspect flow. Drag-drop needs pywebview's own DOM registration to deliver paths
  // and silently yields none otherwise, so Browse is the dependable way to add a ZIP.
  const browseForZip = useCallback(async () => {
    const hostApi = (
      window as unknown as {
        pywebview?: { api?: { pick_ingest_files?: () => Promise<string[]> } };
      }
    ).pywebview?.api;
    if (!hostApi?.pick_ingest_files) {
      toast(
        "Open Stockroom as the app to browse for a ZIP (a web browser cannot read file paths).",
        "neutral",
      );
      return;
    }
    try {
      const paths = await hostApi.pick_ingest_files();
      if (paths && paths.length > 0) inspect(paths, []);
    } catch {
      // the picker was cancelled or is unavailable; nothing to do
    }
  }, [inspect, toast]);

  // Load the job's result into editable local state once it settles, tagging each
  // with a stable id so a commit/remove never remounts its siblings.
  useEffect(() => {
    if (job.status === "done" && job.result) {
      setStaged(job.result.map((candidate) => ({ id: nextId.current++, candidate })));
    }
  }, [job.status, job.result]);

  // A drop anywhere in the window queues native paths here; inspect them.
  useEffect(() => {
    return onQueuedPaths((paths) => {
      if (paths.length > 0) inspect(paths, []);
    });
  }, [inspect]);

  function handleInspectClick() {
    const ids = lcsc.split(/[\s,]+/).map((s) => s.trim()).filter(Boolean);
    if (ids.length > 0) inspect([], ids);
  }

  function removeStaged(id: number) {
    setStaged((s) => (s ? s.filter((x) => x.id !== id) : s));
  }

  const busy = job.status === "running";

  return (
    <>
      <div className="min-h-0 flex-1 overflow-y-auto px-[30px] pt-[22px]">
        <div className="max-w-[760px] pb-10">
          <Card className="px-4 py-3.5">
            <label
              htmlFor="lcsc-ids"
              className="mb-2 block text-xs text-t3"
            >
              LCSC Part IDs
            </label>
            <div className="flex items-center gap-3">
              <input
                id="lcsc-ids"
                value={lcsc}
                onChange={(e) => setLcsc(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleInspectClick();
                }}
                placeholder="C25804, C7442 ..."
                disabled={busy}
                className="min-w-0 flex-1 rounded-control border border-line2 bg-field px-3 py-2 text-base text-t1 outline-none focus:border-acc disabled:opacity-50"
              />
              <Button
                variant="accent"
                onClick={handleInspectClick}
                disabled={busy}
                className="flex-none"
              >
                {busy ? "Inspecting..." : "Inspect"}
              </Button>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <Button onClick={browseForZip} disabled={busy} icon={<UploadIcon />}>
                Browse For ZIP
              </Button>
              <span className="text-xs text-t3">
                Pick one or more vendor ZIP files to inspect and add.
              </span>
            </div>
          </Card>

          {busy ? <Progress progress={job.progress} /> : null}
          {job.status === "error" ? (
            <div className="mt-4 text-sm text-err">
              Inspect failed. {job.error}
            </div>
          ) : null}

          {staged && staged.length > 0 ? (
            <div className="mt-6 flex flex-col gap-4">
              <Eyebrow>Review And Add</Eyebrow>
              {staged.map(({ id, candidate }) => (
                <CandidateCard
                  key={id}
                  candidate={candidate}
                  onCommitted={() => removeStaged(id)}
                  toast={toast}
                />
              ))}
            </div>
          ) : staged && staged.length === 0 ? (
            <div className="mt-8 text-center text-sm text-t3">
              No parts found in what you dropped or entered.
            </div>
          ) : null}

        </div>
      </div>
    </>
  );
}

function Progress({ progress }: { progress: JobProgress | null }) {
  const pct = Math.max(0, Math.min(100, progress?.pct ?? 0));
  return (
    <div className="mt-4">
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-raise2">
        <div
          className="h-full rounded-full bg-acc transition-[width]"
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="mt-2 text-xs text-t3">
        {progress?.message ? progress.message : "Working..."}
      </div>
    </div>
  );
}

function CandidateCard({
  candidate,
  onCommitted,
  toast,
}: {
  candidate: StagingCandidate;
  onCommitted: () => void;
  toast: (message: string, tone?: ToastTone) => void;
}) {
  const [c, setC] = useState<StagingCandidate>(candidate);
  const [missing, setMissing] = useState<string[]>([]);
  const commit = useIngestCommit();
  // Autofill: paste a datasheet link (or attach the PDF) and a purchase link, and
  // the backend fills the remaining identity from the datasheet + enrichment.
  const enrich = useJob<IngestEnrichResult>();
  const [dsUrl, setDsUrl] = useState("");
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
