/**
 * Add A Part: the one place to add a part to the library. Paste a product link (Mouser,
 * LCSC, DigiKey...) or a part number and Stockroom pulls every field and decides what the
 * part needs. A passive (R/C/L) is complete with no files: it uses KiCad's stock symbol,
 * footprint and 3D model, which are shown before it is added. A non-passive takes its KiCad
 * files from a vendor ZIP here (the complete-to-add gate), and the moment it lands the
 * Complete Part window opens so the guided capture finishes the ALTIUM set - the add flow
 * hands off into the both-EDA workflow instead of dead-ending on a toast. The pulled
 * identity/specs merge onto the ZIP so nothing is re-typed; a ZIP with no link still works.
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { ApiError, api } from "../api/client";
import type { EnrichmentResult, StagingCandidate } from "../api/types";
import { useJob, type JobProgress } from "../lib/useJob";
import { useEnrichLookup, useSettings } from "../api/queries";
import { useCapture } from "../lib/capture";
import { useAddPart } from "../lib/addPart";
import { useToast } from "../lib/toast";
import { Text, useText } from "../lib/copy";
import { onQueuedPaths } from "../lib/ingestQueue";
import {
  mergeResultIntoCandidate,
  pulledSpecConflicts,
  vendorFromUrl,
  type SpecConflict,
} from "../lib/candidateFromResult";
import { SPEC_HIDDEN_KEYS } from "../lib/specSchema";
import { distributorLabel } from "../lib/sourced";
import { sv } from "../lib/sourced";
import { Badge, Button, Card, Eyebrow } from "../components/primitives";
import { CandidateCard } from "../components/CandidateCard";
import { EnrichStages } from "../components/EnrichStages";
import { PassiveAddSection } from "../components/PassiveAddSection";
import { ProductPhoto, productPhotoUrl } from "../components/ProductPhoto";
import { PulledDepth } from "../components/PulledDepth";
import { UploadIcon } from "../components/icons";

// Each staged candidate carries a stable id assigned on load, so committing or
// removing one never shifts another's React key (which would remount its sibling
// cards and discard their in-progress edits).
interface Staged {
  id: number;
  candidate: StagingCandidate;
  datasheetUrl: string;
  // every spec disagreement around this candidate (API-vs-API + ZIP-vs-pull), kept for
  // display on the review card (merge-only-identical, owner 2026-07-24)
  conflicts: SpecConflict[];
}

const isUrl = (s: string) => /^https?:\/\//i.test(s.trim());

// The file-less seed a pulled result stages onto: every asset slot empty (the guided
// capture attaches both EDA formats AFTER the part lands), everything else filled by
// mergeResultIntoCandidate from the pull.
const FILE_LESS_CANDIDATE: StagingCandidate = {
  vendor: "",
  symbol_lib_path: null,
  symbol_name: "",
  footprint_variants: [],
  chosen_footprint_index: 0,
  model_path: null,
  datasheet_path: null,
  display_name: "",
  entry_name: "",
  category: "",
  mpn: "",
  manufacturer: "",
  description: "",
  tags: [],
  purchase: [],
  gaps: [],
  specs: {},
};

// One step of the part's path (pull -> KiCad -> Altium): a numbered micro-label in the
// quiet eyebrow register, so the sequence reads as structure, never a prose wall.
function PathStep({ n, children }: { n: number; children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-[0.06em] text-t3">
      <span className="tnum grid h-4 w-4 flex-none place-items-center rounded-full border border-line2 font-mono text-[9px] leading-none text-t2">
        {n}
      </span>
      {children}
    </span>
  );
}

function PathArrow() {
  return (
    <span aria-hidden className="text-2xs text-t3/60">
      {"→"}
    </span>
  );
}

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
  // The added-part continuation (the new Altium workflow): when the LAST staged
  // candidate lands, the Add window closes and the new part opens in its Complete
  // Part window, where the guided capture pulls the KiCad AND Altium assets in one
  // pass. Adding is no longer a dead end that leaves the part file-less.
  const capture = useCapture();
  const addPart = useAddPart();
  // Copy layer: strings that fire from callbacks/attributes resolve here (stable hook order);
  // everything visible below is a <Text> so the whole window is dev-mode editable.
  const inputAria = useText("ingest.input-aria", "Product link or part number");
  const inputPlaceholder = useText(
    "ingest.input-placeholder",
    "https://www.mouser.com/ProductDetail/... or ERJ-P03F1101V",
  );
  const toastNothing = useText(
    "ingest.toast-nothing",
    "Nothing came back. The page might have blocked the fetch, or the link is not a product page.",
  );
  const toastLookupFailed = useText("ingest.toast-lookup-failed", "Look up failed.");
  const toastInspectFailed = useText("ingest.toast-inspect-failed", "Inspect failed");
  const toastNoHost = useText(
    "ingest.toast-no-host",
    "Open Stockroom as the app to browse for a ZIP (a web browser cannot read file paths).",
  );
  const toastAdded = useText("ingest.toast-added", "Added");

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
        toast(toastNothing, "neutral");
      } else if (!r.add_plan) {
        // The perfect workflow (owner): a pulled NON-passive stages itself immediately -
        // one click lands it file-less, then the Complete Part window opens and the
        // guided capture downloads both the KiCad and Altium sets. A vendor ZIP stays
        // the fallback (inspecting one replaces this staged candidate wholesale).
        const url = isUrl(lookedUpInput) ? lookedUpInput : "";
        const candidate = {
          ...mergeResultIntoCandidate(FILE_LESS_CANDIDATE, r, url),
          vendor: url ? vendorFromUrl(url) : "pulled",
        };
        setStaged([
          {
            id: nextId.current++,
            candidate,
            datasheetUrl: sv(r.datasheet_url),
            conflicts: pulledSpecConflicts(FILE_LESS_CANDIDATE, r),
          },
        ]);
      }
    } else if (enrich.status === "error") {
      toast(enrich.error ?? toastLookupFailed, "err");
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
        toast(err instanceof ApiError ? err.message : toastInspectFailed, "err");
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
      toast(toastNoHost, "neutral");
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
        // conflicts compare the PRE-merge candidate (the ZIP's own answers) to the pull
        conflicts: r ? pulledSpecConflicts(candidate, r) : [],
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
  // When the empty pull came from a recognized distributor link and the matching API key
  // is absent, the blocked card names THE fix (the API-first lane is what makes those
  // Akamai-guarded links reliable) instead of a generic shrug. Unknown settings (still
  // loading / errored) keep the generic message: never claim a key is missing unseen.
  const settingsQ = useSettings();
  const blockedKeyVendor = (() => {
    if (!blockedFetch || !isUrl(lookedUpInput) || !settingsQ.data) return null;
    const u = lookedUpInput.toLowerCase();
    if (u.includes("mouser.") && !settingsQ.data.mouser_api_key_set) return "mouser";
    if ((u.includes("digikey.") || u.includes("digi-key")) && !settingsQ.data.digikey_client_secret_set)
      return "digikey";
    return null;
  })();

  return (
    <div data-dev-id="ingest.root" className="flex flex-col gap-5">
      {/* The hero: paste a link, or drop a ZIP. This is the whole point of the window. */}
      <div data-dev-id="ingest.hero">
        <Eyebrow className="mb-2">
          <Text id="ingest.source-eyebrow">Source</Text>
        </Eyebrow>
        <div className="flex items-center gap-2.5">
          <input
            data-dev-id="ingest.input"
            aria-label={inputAria}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") lookUp();
            }}
            placeholder={inputPlaceholder}
            disabled={looking}
            className="h-[34px] min-w-0 flex-1 rounded-control border border-line2 bg-field px-3 text-sm text-t1 outline-none transition-colors focus:border-acc disabled:opacity-50"
          />
          <Button
            data-dev-id="ingest.lookup"
            variant="accent"
            onClick={lookUp}
            disabled={looking || !input.trim()}
            className="flex-none px-4"
          >
            {looking ? (
              <Text id="ingest.lookup-busy">Looking Up...</Text>
            ) : (
              <Text id="ingest.lookup-label">Look Up</Text>
            )}
          </Button>
        </div>
        <p className="mt-2 text-xs text-t3">
          <Text id="ingest.hero-hint">
            A product link (Mouser, LCSC, DigiKey...) or a part number pulls every detail. A passive lands complete with no files.
          </Text>
        </p>
        {looking ? (
          <div data-dev-id="ingest.stages" className="mt-3.5">
            <EnrichStages progress={enrich.progress} />
          </div>
        ) : !result ? (
          <>
            {/* the alternate route: a vendor ZIP, as a region tile (the Complete Part
                window's file-tile idiom, so the two part-windows read as one family) */}
            <div
              data-dev-id="ingest.zip-tile"
              className="mt-3.5 flex items-center gap-3 rounded-control border border-line2 bg-raise p-3.5 shadow-file"
            >
              <span className="grid h-7 w-7 flex-none place-items-center rounded-control bg-raise2 text-t1">
                <UploadIcon className="h-3.5 w-3.5" />
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-sm font-semibold text-t1">
                  <Text id="ingest.zip-title">Vendor ZIP</Text>
                </div>
                <div className="mt-0.5 text-xs text-t3">
                  <Text id="ingest.browse-hint">
                    A SnapEDA or Ultra Librarian ZIP carries the KiCad files. Drop it anywhere in the window, or browse.
                  </Text>
                </div>
              </div>
              <Button data-dev-id="ingest.browse" onClick={browseForZip} disabled={busy} className="flex-none">
                <Text id="ingest.browse-label">Browse for ZIP</Text>
              </Button>
            </div>
            {/* the path a non-passive takes, as structure instead of prose: pull the
                details, land with the KiCad files, then the guided capture finishes the
                Altium set. The sequence IS the app's two-EDA design philosophy. */}
            <div
              data-dev-id="ingest.path"
              className="mt-3.5 flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-line pt-3"
            >
              <PathStep n={1}>
                <Text id="ingest.path-pull">Pull Details</Text>
              </PathStep>
              <PathArrow />
              <PathStep n={2}>
                <Text id="ingest.path-add">Add The Part</Text>
              </PathStep>
              <PathArrow />
              <PathStep n={3}>
                <Text id="ingest.path-capture">Capture KiCad + Altium Files</Text>
              </PathStep>
            </div>
          </>
        ) : null}
      </div>

      {result && plan ? (
        <Card data-dev-id="ingest.passive" className="px-4 py-4">
          <PassiveAddSection
            key={lookedUpInput}
            result={result}
            plan={plan}
            input={lookedUpInput}
            onAdded={(name) => {
              toast(`${toastAdded} ${name}`, "ok");
              reset();
            }}
            toast={toast}
          />
        </Card>
      ) : null}

      {blockedFetch ? (
        <Card data-dev-id="ingest.blocked" className="px-4 py-4">
          <div className="flex flex-col gap-3">
            <span className="text-sm text-warn">
              {blockedKeyVendor === "mouser" ? (
                <Text id="ingest.blocked-mouser-key">
                  Nothing was pulled, and no Mouser API key is set. Mouser blocks the page fetch, so the key is what resolves a Mouser link reliably. Add one in Settings under Sourcing, then look this up again, or drop a vendor ZIP.
                </Text>
              ) : blockedKeyVendor === "digikey" ? (
                <Text id="ingest.blocked-digikey-key">
                  Nothing was pulled, and no DigiKey API key is set. DigiKey blocks the page fetch, so the key is what resolves a DigiKey link reliably. Add one in Settings under Sourcing, then look this up again, or drop a vendor ZIP.
                </Text>
              ) : (
                <Text id="ingest.blocked-msg">
                  Nothing was pulled. The page might have blocked the fetch, or the link is not a product page. Use a different link, or drop a vendor ZIP.
                </Text>
              )}
            </span>
            <div className="flex flex-wrap items-center gap-3">
              <Button onClick={browseForZip} disabled={busy} icon={<UploadIcon />}>
                <Text id="ingest.browse-label">Browse for ZIP</Text>
              </Button>
            </div>
          </div>
        </Card>
      ) : null}

      {staged && staged.length > 0 ? (
        <div data-dev-id="ingest.staged" className="flex flex-col gap-4">
          <Eyebrow>
            <Text id="ingest.review-eyebrow">Review and Add</Text>
          </Eyebrow>
          {staged.map(({ id, candidate, datasheetUrl, conflicts }) => (
            <CandidateCard
              key={id}
              candidate={candidate}
              conflicts={conflicts}
              initialDatasheetUrl={datasheetUrl}
              onCommitted={(created) => {
                removeStaged(id);
                // Continue into Complete Part only when this emptied the staging list
                // (a bulk ZIP add stays here so the remaining cards keep their place).
                const remaining = (staged ?? []).filter((x) => x.id !== id).length;
                if (remaining === 0) {
                  capture.requestOpenFor(created.id);
                  addPart.close();
                }
              }}
              toast={toast}
            />
          ))}
        </div>
      ) : staged && staged.length === 0 ? (
        <div className="py-4 text-center text-sm text-t3">
          <Text id="ingest.no-parts">No parts found in what was dropped.</Text>
        </div>
      ) : null}

      {nonPassive ? (
        <Card data-dev-id="ingest.nonpassive" className="px-4 py-4">
          <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2 text-sm text-t2">
              <Badge tone="neutral">
                <Text id="ingest.needs-files">Files Via Capture</Text>
              </Badge>
              <span>
                <Text id="ingest.needs-msg">Add it below and the guided capture downloads the KiCad and Altium files.</Text>
              </span>
            </div>
            <PulledSummary result={result} />
            <div className="flex flex-wrap items-center gap-3">
              <Button onClick={browseForZip} disabled={busy} icon={<UploadIcon />}>
                <Text id="ingest.browse-label">Browse for ZIP</Text>
              </Button>
              <span className="text-xs text-t3">
                <Text id="ingest.drop-hint">
                  The fallback when the capture cannot: a vendor ZIP (SnapEDA, Ultra Librarian) supplies the KiCad files up front. The pulled details are kept either way.
                </Text>
              </span>
            </div>
          </div>
        </Card>
      ) : null}

      {busy ? <Progress progress={job.progress} /> : null}
      {job.status === "error" ? (
        <div className="text-sm text-err">
          <Text id="ingest.inspect-failed">Inspect failed.</Text> {job.error}
        </div>
      ) : null}

    </div>
  );
}

function PulledSummary({ result }: { result: EnrichmentResult }) {
  const rows = (
    [
      ["ingest.pulled-mpn", "MPN", sv(result.mpn)],
      ["ingest.pulled-manufacturer", "Manufacturer", sv(result.manufacturer)],
      ["ingest.pulled-description", "Description", sv(result.description)],
      ["ingest.pulled-package", "Package", sv(result.package)],
    ] as [string, string, string][]
  ).filter(([, , v]) => v);
  const specCount = Object.keys(result.specs).filter((k) => k !== "product_url").length;
  if (rows.length === 0 && specCount === 0) {
    return (
      <span className="text-sm text-warn">
        <Text id="ingest.nothing-pulled">
          Nothing was pulled. The page might have blocked the fetch, or the link is not a product page.
        </Text>
      </span>
    );
  }
  const photoUrl = productPhotoUrl(result.specs);
  return (
    <div
      data-dev-id="ingest.pulled-summary"
      className="flex flex-col gap-2 rounded-card border border-line2 bg-raise2 p-4"
    >
      <div className="flex items-start gap-4">
        {photoUrl ? (
          <div
            data-dev-id="ingest.pulled-photo"
            className="h-[72px] w-[72px] flex-none overflow-hidden rounded-control border border-line bg-stage p-1"
          >
            <ProductPhoto key={photoUrl} url={photoUrl} alt="Product photo" />
          </div>
        ) : null}
        {rows.length > 0 ? (
          <div className="grid min-w-0 flex-1 grid-cols-1 gap-1.5 text-sm sm:grid-cols-[max-content_1fr] sm:gap-x-4">
            {rows.map(([copyId, k, v]) => (
              <div key={k} className="contents">
                <span className="text-t3">
                  <Text id={copyId}>{k}</Text>
                </span>
                <span className="truncate text-t1">{v}</span>
              </div>
            ))}
          </div>
        ) : null}
      </div>
      <PulledSpecTable result={result} />
      <PulledDepth result={result} />
    </div>
  );
}

// EVERYTHING the pull returned, as real rows (owner 2026-07-24: "display all of it") -
// not a count. A key two sources disagreed on shows every value with its origin
// (merge-only-identical); internal keys (product_url, the photo URL) never show as rows.
function PulledSpecTable({ result }: { result: EnrichmentResult }) {
  const conflicts = result.spec_conflicts ?? {};
  const specRows = Object.entries(result.specs)
    .filter(
      ([k, v]) =>
        !SPEC_HIDDEN_KEYS.has(k) &&
        k !== "product_url" &&
        v != null &&
        String(v.value ?? "").trim() !== "",
    )
    .map(([k, v]) => ({
      key: k,
      value: String(v?.value ?? ""),
      conflict: conflicts[k],
    }));
  const datasheet = sv(result.datasheet_url);
  if (specRows.length === 0 && !datasheet) return null;
  return (
    <div className="border-t border-line pt-3">
      <div className="mb-2 flex items-baseline gap-2">
        <Eyebrow>
          <Text id="ingest.pulled-specs-title">Pulled Specs</Text>
        </Eyebrow>
        <span className="text-2xs tabular-nums text-t3">{specRows.length}</span>
      </div>
      <div
        data-dev-id="ingest.pulled-specs"
        className="max-h-56 overflow-y-auto"
        role="region"
        aria-label="Pulled Specs"
        tabIndex={0}
      >
        <div className="grid grid-cols-1 gap-y-1 text-sm sm:grid-cols-[max-content_1fr] sm:gap-x-4">
          {datasheet ? (
            <div className="contents">
              <span className="text-t3">
                <Text id="ingest.pulled-datasheet">Datasheet</Text>
              </span>
              <a
                href={datasheet}
                target="_blank"
                rel="noreferrer"
                className="truncate text-acc outline-none hover:underline focus-visible:ring-2 focus-visible:ring-acc"
              >
                {datasheet}
              </a>
            </div>
          ) : null}
          {specRows.map((r) => (
            <div key={r.key} className="contents">
              <span className="text-t3">{r.key}</span>
              {r.conflict && r.conflict.length > 1 ? (
                <span className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-t1">
                  {r.conflict.map((s, i) => (
                    <span key={i} className="inline-flex items-baseline gap-1">
                      {i > 0 ? (
                        <span aria-hidden="true" className="text-t3">
                          ·
                        </span>
                      ) : null}
                      <span>{String(s.value ?? "")}</span>
                      <span className="text-2xs text-t3">{distributorLabel(s.source)}</span>
                    </span>
                  ))}
                </span>
              ) : (
                <span className="truncate text-t1">{r.value}</span>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Progress({ progress }: { progress: JobProgress | null }) {
  const pct = Math.max(0, Math.min(100, progress?.pct ?? 0));
  return (
    <div className="mt-4">
      <div
        data-dev-id="ingest.progress"
        className="h-1.5 w-full overflow-hidden bg-raise2"
      >
        <div
          className="h-full bg-acc transition-[width]"
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="mt-2 text-xs text-t3">
        {progress?.message ? progress.message : <Text id="ingest.working">Working...</Text>}
      </div>
    </div>
  );
}
