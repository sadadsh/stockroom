/**
 * Add A Part: the one place to add a part to the library. Paste a product link (Mouser,
 * LCSC, DigiKey...) or a part number and Stockroom pulls every field and decides what the
 * part needs. A passive (R/C/L) is complete with no files: it uses KiCad's stock symbol,
 * footprint and 3D model, which are shown before it is added. A non-passive needs its
 * symbol, footprint and 3D model dropped as a vendor ZIP; the pulled identity/specs merge
 * onto it so nothing is re-typed. A vendor ZIP dropped with no link still works on its own.
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { ApiError, api } from "../api/client";
import type { EnrichmentResult, StagingCandidate } from "../api/types";
import { useJob, type JobProgress } from "../lib/useJob";
import { useEnrichLookup } from "../api/queries";
import { useToast } from "../lib/toast";
import { onQueuedPaths } from "../lib/ingestQueue";
import { mergeResultIntoCandidate } from "../lib/candidateFromResult";
import { sv } from "../lib/sourced";
import { Badge, Button, Card, Eyebrow } from "../components/primitives";
import { CandidateCard } from "../components/CandidateCard";
import { EnrichStages } from "../components/EnrichStages";
import { PassiveAddSection } from "../components/PassiveAddSection";
import { PulledDepth } from "../components/PulledDepth";
import { UploadIcon } from "../components/icons";

// Each staged candidate carries a stable id assigned on load, so committing or
// removing one never shifts another's React key (which would remount its sibling
// cards and discard their in-progress edits).
interface Staged {
  id: number;
  candidate: StagingCandidate;
  datasheetUrl: string;
}


const isUrl = (s: string) => /^https?:\/\//i.test(s.trim());

export function IngestPage() {
  const [input, setInput] = useState("");
  const [result, setResult] = useState<EnrichmentResult | null>(null);
  // The exact input that produced `result`, so the passive section and the ZIP merge
  // use the right link even after the input box is edited.
  const [lookedUpInput, setLookedUpInput] = useState("");
  // null = nothing inspected yet; [] = inspected, found nothing.
  const [staged, setStaged] = useState<Staged[] | null>(null);
  const nextId = useRef(0);
  const job = useJob<StagingCandidate[]>();
  // The lookup is a background job now (the render tier can take seconds): it streams the live
  // fetching/rendering/extracting/validating stages, and the sourced result lands on `enrich.result`.
  const enrich = useEnrichLookup();
  const looking = enrich.status === "running";
  const { toast } = useToast();

  const lookUp = useCallback(() => {
    const v = input.trim();
    if (!v || looking) return;
    setResult(null);
    setStaged(null);
    setLookedUpInput(v);
    // Drop any in-flight ZIP inspect so its result never merges onto this new lookup.
    job.reset();
    // Fire-and-forget: the hook drives status/progress/result; the settle effect below folds
    // the sourced fields in once the stream ends (a submit/stream failure lands as enrich.error).
    if (isUrl(v)) enrich.runUrl(v);
    else enrich.runPart(v);
  }, [input, looking, job, enrich]);

  // Fold the finished lookup into the page: the sourced result feeds the passive section and
  // the ZIP merge; a total miss or an error is surfaced honestly (never a fabricated value).
  // useLayoutEffect (not useEffect): `looking` flips false the moment the job commits done, but
  // the local `result` is written here; running BEFORE paint keeps the empty "Browse for ZIP"
  // state from flashing for one frame between the two on every successful lookup.
  useLayoutEffect(() => {
    if (enrich.status === "done" && enrich.result) {
      const r = enrich.result;
      setResult(r);
      const gotAnything =
        r.mpn || r.manufacturer || r.datasheet_url || Object.keys(r.specs).length > 0 || r.add_plan;
      if (!gotAnything) {
        toast(
          "Nothing came back. The page may have blocked the fetch, or the link is not a product page.",
          "neutral",
        );
      }
    } else if (enrich.status === "error") {
      toast(enrich.error ?? "Look up failed.", "err");
    }
    // toast is stable; re-running only on the lookup settling is intended.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enrich.status, enrich.result]);

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

  // Load the job's result once it settles. When a link was looked up (a non-passive), the
  // pulled identity/specs merge onto each candidate so only the ZIP's assets are new; the
  // pulled datasheet link is carried so the candidate can fetch+store it in one click.
  useEffect(() => {
    if (job.status !== "done" || !job.result) return;
    // Wait for a still-streaming lookup. A native drag can drop a ZIP mid-lookup, and its
    // inspect settles FIRST; staging its candidates now (with no result yet) would strand them
    // un-merged, because this effect keys off the ZIP job and would not re-run when the lookup
    // lands. Deferring while the lookup runs - enrich.status is a dep - folds the pulled data in
    // exactly once, when it arrives. enrich.result is read (not the local mirror) so the merge
    // never depends on the sibling layout effect having written `result` first.
    if (enrich.status === "running") return;
    const r = enrich.status === "done" ? enrich.result : null;
    const url = r && isUrl(lookedUpInput) ? lookedUpInput : "";
    setStaged(
      job.result.map((candidate) => ({
        id: nextId.current++,
        candidate: r ? mergeResultIntoCandidate(candidate, r, url) : candidate,
        datasheetUrl: r ? sv(r.datasheet_url) : "",
      })),
    );
    // enrich.result/lookedUpInput are read at settle time; re-running on their change would
    // re-key already-loaded cards and discard edits.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job.status, job.result, enrich.status]);

  // A drop anywhere in the window queues native paths here; inspect them.
  useEffect(() => {
    return onQueuedPaths((paths) => {
      if (paths.length > 0) inspect(paths, []);
    });
  }, [inspect]);

  // When the LAST staged candidate is committed away, tear down the whole part context (like a
  // passive add) so the just-added part's live lookup cannot contaminate a later ZIP and no
  // completed job lingers to resurrect. Keyed off staged transitioning NON-EMPTY -> empty; an
  // inspect that finds nothing (null -> empty) must NOT reset (it shows "No parts found"), hence
  // the prev-length guard. Reading the transition here (not inside removeStaged) lets removeStaged
  // use a functional update, so committing several candidates concurrently can never miss the
  // emptiness check via a stale render-closure.
  const prevStagedLen = useRef<number | null>(null);
  useEffect(() => {
    const wasNonEmpty = (prevStagedLen.current ?? 0) > 0;
    prevStagedLen.current = staged?.length ?? null;
    if (staged && staged.length === 0 && wasNonEmpty) reset();
    // reset is recreated each render; listing it would re-run this on every render. The transition
    // to empty is the only intended trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [staged]);

  function removeStaged(id: number) {
    // Functional update: read the LATEST staged, never this render's closure, so committing
    // several candidates concurrently (each card has its own Add button and async git commit) can
    // never drop the wrong one or miss the emptiness check. The full teardown fires from the
    // transition effect above once the list empties.
    setStaged((s) => (s ? s.filter((x) => x.id !== id) : s));
  }

  function reset() {
    setInput("");
    setResult(null);
    setLookedUpInput("");
    setStaged(null);
    // Tear down BOTH lifecycles, not just the local mirror. The staging effect merges from
    // enrich.result and keys off job.status, so a stale "done" lookup would contaminate the next
    // ZIP, and a still-"done" ZIP job would let flipping enrich.status done->idle re-fire the
    // effect and resurrect the just-cleared candidate un-merged. Reset a COMPLETED job, but leave
    // a genuinely in-flight one alone so a native-drag ZIP still inspecting through this teardown
    // is not silently discarded (it finishes and stages standalone).
    enrich.reset();
    if (job.status !== "running") job.reset();
  }

  const busy = job.status === "running";
  const plan = result?.add_plan ?? null;
  const pulledSomething =
    result !== null &&
    (!!sv(result.mpn) ||
      !!sv(result.manufacturer) ||
      !!sv(result.description) ||
      Object.keys(result.specs).some((k) => k !== "product_url"));
  // A real non-passive part (data pulled, needs its assets) vs a fetch that came back
  // empty (blocked/not a product page) - the latter must NOT assert "needs files".
  const nonPassive = result !== null && plan === null && pulledSomething;
  const blockedFetch = result !== null && plan === null && !pulledSomething;

  return (
    <div className="flex flex-col gap-4">
      {/* The hero: paste a link, or drop a ZIP. This is the whole point of the window. */}
      <div>
        <p className="mb-2.5 text-xs text-t3">
          Paste a product link and Stockroom pulls all the fields.
          A passive component is complete with no additional files; a non-passive component does to be complete.
        </p>
        <div className="flex items-center gap-2.5">
          <input
            aria-label="Product link or part number"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") lookUp();
            }}
            placeholder="https://www.mouser.com/ProductDetail/... or ERJ-P03F1101V"
            disabled={looking}
            className="h-11 min-w-0 flex-1 rounded-control border border-line2 bg-field px-3.5 text-base text-t1 outline-none transition-colors focus:border-acc disabled:opacity-50"
          />
          <Button
            variant="accent"
            onClick={lookUp}
            disabled={looking || !input.trim()}
            className="h-11 flex-none px-5"
          >
            {looking ? "Looking Up..." : "Look Up"}
          </Button>
        </div>
        {looking ? (
          <EnrichStages progress={enrich.progress} className="mt-3.5" />
        ) : !result ? (
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <Button onClick={browseForZip} disabled={busy} icon={<UploadIcon />}>
              Browse for ZIP
            </Button>
            <span className="text-xs text-t3">
              Or add a part straight from a vendor ZIP (SnapEDA, Ultra Librarian).
            </span>
          </div>
        ) : null}
      </div>

      {result && plan ? (
        <Card className="px-4 py-4">
          <PassiveAddSection
            key={lookedUpInput}
            result={result}
            plan={plan}
            input={lookedUpInput}
            onAdded={(name) => {
              toast(`Added ${name}`, "ok");
              reset();
            }}
            toast={toast}
          />
        </Card>
      ) : null}

      {blockedFetch ? (
        <Card className="px-4 py-4">
          <div className="flex flex-col gap-3">
            <span className="text-sm text-warn">
              Nothing was pulled. The page might have blocked the fetch, or the link is not a
              product page. Use a different link, or drop a vendor ZIP.
            </span>
            <div className="flex flex-wrap items-center gap-3">
              <Button onClick={browseForZip} disabled={busy} icon={<UploadIcon />}>
                Browse for ZIP
              </Button>
            </div>
          </div>
        </Card>
      ) : null}

      {nonPassive ? (
        <Card className="px-4 py-4">
          <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2 text-sm text-t2">
              <Badge tone="warn">Needs Files</Badge>
              <span>This part needs a symbol, footprint and 3D model.</span>
            </div>
            <PulledSummary result={result} />
            <div className="flex flex-wrap items-center gap-3">
              <Button onClick={browseForZip} disabled={busy} icon={<UploadIcon />}>
                Browse for ZIP
              </Button>
              <span className="text-xs text-t3">
                Drop its vendor ZIP (SnapEDA, Ultra Librarian) anywhere, or browse. The
                pulled details are kept, so all that is left is the files.
              </span>
            </div>
          </div>
        </Card>
      ) : null}

      {busy ? <Progress progress={job.progress} /> : null}
      {job.status === "error" ? (
        <div className="text-sm text-err">Inspect failed. {job.error}</div>
      ) : null}

      {staged && staged.length > 0 ? (
        <div className="flex flex-col gap-4">
          <Eyebrow>Review and Add</Eyebrow>
          {staged.map(({ id, candidate, datasheetUrl }) => (
            <CandidateCard
              key={id}
              candidate={candidate}
              initialDatasheetUrl={datasheetUrl}
              onCommitted={() => removeStaged(id)}
              toast={toast}
            />
          ))}
        </div>
      ) : staged && staged.length === 0 ? (
        <div className="py-4 text-center text-sm text-t3">
          No parts found in what was dropped.
        </div>
      ) : null}
    </div>
  );
}

function PulledSummary({ result }: { result: EnrichmentResult }) {
  const rows = (
    [
      ["MPN", sv(result.mpn)],
      ["Manufacturer", sv(result.manufacturer)],
      ["Description", sv(result.description)],
      ["Package", sv(result.package)],
    ] as [string, string][]
  ).filter(([, v]) => v);
  const specCount = Object.keys(result.specs).filter((k) => k !== "product_url").length;
  if (rows.length === 0 && specCount === 0) {
    return (
      <span className="text-sm text-warn">
        Nothing was pulled. The page may have blocked the fetch, or the link is not a product page.
      </span>
    );
  }
  return (
    <div className="flex flex-col gap-2 rounded-card border border-line2 bg-raise2 p-4">
      {rows.length > 0 ? (
        <div className="grid grid-cols-1 gap-1.5 text-sm sm:grid-cols-[max-content_1fr] sm:gap-x-4">
          {rows.map(([k, v]) => (
            <div key={k} className="contents">
              <span className="text-t3">{k}</span>
              <span className="truncate text-t1">{v}</span>
            </div>
          ))}
        </div>
      ) : null}
      {specCount > 0 ? (
        <span className="text-xs text-t3">{specCount} specs pulled and kept.</span>
      ) : null}
      <PulledDepth result={result} />
    </div>
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
