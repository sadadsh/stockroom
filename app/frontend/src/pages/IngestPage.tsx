/**
 * Add A Part: the one place to add a part to the library. Paste a product link (Mouser,
 * LCSC, DigiKey...) or a part number and Stockroom retains every available sourced field and
 * decides what the part needs. A passive (R/C/L) needs no provider download because qualified
 * built-in representations project into both tools. A non-passive lands as an identity/spec
 * record, then Complete Part runs
 * the network capture that must verify one same-source KiCad + Altium + STEP set. Files selected
 * during that task use the same identity and cross-EDA gates as intercepted downloads.
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import type {
  EnrichmentResult,
  PartDetail,
  SourcedField,
  StagingCandidate,
} from "../api/types";
import { useEnrichLookup, useSettings } from "../api/queries";
import { useCapture } from "../lib/capture";
import { useAddPart } from "../lib/addPart";
import { useToast } from "../lib/toast";
import { Text, useCopyFormatter, useText } from "../lib/copy";
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
import { BulkImportSection } from "../components/BulkImportSection";
import { CandidateCard } from "../components/CandidateCard";
import { EnrichStages } from "../components/EnrichStages";
import { PassiveAddSection } from "../components/PassiveAddSection";
import { PhotoTrigger } from "../components/ProductPhoto";
import { productPhotoUrl } from "../components/partPhotos";
import { PulledDepth } from "../components/PulledDepth";
import {
  discardIntakeDraft,
  loadIntakeDraft,
  readUiSession,
  setPendingIntakeDraft,
  type IntakeDraftBodyV1,
  type IntakeDraftCandidate,
  type IntakeDraftNetworkInput,
  type IntakeDraftPurchase,
  type IntakeDraftReview,
  type JsonValue,
} from "../lib/uiSession";

// Each staged candidate carries a stable id assigned on load, so committing or
// removing one never shifts another's React key (which would remount its sibling
// cards and discard their in-progress edits).
interface Staged {
  id: number;
  candidate: StagingCandidate;
  datasheetUrl: string;
  // Every source disagreement around this candidate, kept for display on the
  // review card (merge-only-identical, owner 2026-07-24).
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
    <span className="inline-flex items-center gap-1.5 ui-property-label">
      <span className="tnum grid h-4 w-4 flex-none place-items-center rounded-full border border-line2 font-mono text-2xs leading-none text-t2">
        {n}
      </span>
      {children}
    </span>
  );
}

function PathArrow() {
  return (
    <span aria-hidden className="ui-row-metadata">
      {"→"}
    </span>
  );
}

function mpnIdentityKey(value: string): string {
  return value.normalize("NFC").trim().toLocaleLowerCase("en-US");
}

function hasExactPulledIdentity(result: EnrichmentResult, input: string): boolean {
  const mpn = sv(result.mpn);
  if (!mpn) return false;
  return isUrl(input) || mpnIdentityKey(mpn) === mpnIdentityKey(input);
}

export function IngestPage() {
  const [input, setInput] = useState("");
  const [result, setResult] = useState<EnrichmentResult | null>(null);
  // The exact input that produced `result`, so the staged identity and passive
  // section use the right source even after the input box is edited.
  const [lookedUpInput, setLookedUpInput] = useState("");
  // A non-passive exact match stages one metadata-only candidate for review.
  const [staged, setStaged] = useState<Staged[] | null>(null);
  const nextId = useRef(0);
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
  const lastCommittedPart = useRef<PartDetail | null>(null);
  // Copy layer: strings that fire from callbacks/attributes resolve here (stable hook order);
  // everything visible below is a <Text> so the whole window is dev-mode editable.
  const toastNothing = useText(
    "ingest.toast-nothing",
    "Nothing came back. The page might have blocked the fetch, or the link is not a product page.",
  );
  const toastLookupFailed = useText("ingest.toast-lookup-failed", "Look up failed.");
  const toastAdded = useCopyFormatter("ingest.toast-added", "Added {name}");

  // Rehydrate the server-staged draft once. The session document contains only
  // its immutable id/revision; network input and review fields live in the
  // separately bounded draft store and never in the host/session snapshot.
  useEffect(() => {
    if (!readUiSession().intake_draft_ref) return;
    let cancelled = false;
    void loadIntakeDraft()
      .then((saved) => {
        if (!saved || cancelled) return;
        const value = saved.network_input.value;
        const review = saved.review;
        setInput(value);
        setLookedUpInput(review.lookup_input?.value ?? "");
        setResult(review.enrichment_result);
        const restored = review.candidates.map((candidate) => {
          const match = /^candidate-(\d+)$/.exec(candidate.client_id);
          const id = match ? Number(match[1]) : nextId.current;
          nextId.current = Math.max(nextId.current, id + 1);
          return stagedFromDraft(id, candidate);
        });
        setStaged(restored.length > 0 ? restored : null);
      })
      .catch(() => {
        // The visible draft stays empty when its referenced bytes are unavailable;
        // the backend retains the honest missing/corrupt state for diagnostics.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Keep the latest keystroke and review edits available to both the background
  // server checkpoint and the host's synchronous pre-update export hook.
  useEffect(() => {
    const value = input.trim();
    if (!value && (!staged || staged.length === 0)) {
      setPendingIntakeDraft(null);
      return;
    }
    // A review is identity-bound to the input that produced it. If the person
    // begins typing a different MPN after lookup, preserve that latest input
    // without falsely attaching the previous candidate to it.
    const first =
      value === lookedUpInput.trim() ? staged?.[0] : undefined;
    const lookupInput =
      value === lookedUpInput.trim() && value
        ? networkInput(value)
        : null;
    const review: IntakeDraftReview = {
      lookup_input: lookupInput,
      enrichment_result: lookupInput ? result : null,
      candidates: first ? (staged ?? []).map(draftCandidate) : [],
    };
    const draft: IntakeDraftBodyV1 = {
      network_input: networkInput(value),
      review,
    };
    setPendingIntakeDraft(draft);
  }, [input, lookedUpInput, result, staged]);

  const runLookup = useCallback((raw: string) => {
    const v = raw.trim();
    if (!v || looking) return;
    setInput(v);
    setResult(null);
    setStaged(null);
    setLookedUpInput(v);
    // Fire-and-forget: the hook drives status/progress/result; the settle effect below folds
    // the sourced fields in once the stream ends (a submit/stream failure lands as enrich.error).
    if (isUrl(v)) enrich.runUrl(v);
    else enrich.runPart(v);
  }, [looking, enrich]);
  const lookUp = useCallback(() => runLookup(input), [input, runLookup]);

  // Fold the finished lookup into the page: the sourced result feeds the passive section and
  // metadata-only staging; a total miss or an error is surfaced honestly.
  // useLayoutEffect (not useEffect): `looking` flips false the moment the job commits done, but
  // the local `result` is written here; running BEFORE paint keeps the empty state
  // from flashing for one frame between the two on every successful lookup.
  useLayoutEffect(() => {
    if (enrich.status === "done" && enrich.result) {
      const r = enrich.result;
      setResult(r);
      const exactIdentity = hasExactPulledIdentity(r, lookedUpInput);
      if (!exactIdentity) {
        setStaged(null);
        toast(toastNothing, "neutral");
      } else if (!r.add_plan) {
        // The perfect workflow (owner): a pulled NON-passive stages itself immediately -
        // one click lands it file-less, then the Complete Part window opens and the
        // guided network capture verifies both EDA projections and their shared STEP.
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

  // When the staged candidate is committed away, tear down the whole part context
  // so the just-added part's live lookup cannot contaminate the next lookup.
  // Reading the transition here (not inside removeStaged) lets removeStaged
  // use a functional update, so committing several candidates concurrently can never miss the
  // emptiness check via a stale render-closure.
  const prevStagedLen = useRef<number | null>(null);
  useEffect(() => {
    const wasNonEmpty = (prevStagedLen.current ?? 0) > 0;
    prevStagedLen.current = staged?.length ?? null;
    if (staged && staged.length === 0 && wasNonEmpty) {
      const created = lastCommittedPart.current;
      lastCommittedPart.current = null;
      reset();
      if (created) {
        capture.requestOpenFor(created.id);
        addPart.close();
      }
    }
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
    // Tear down the source job as well as the local mirror so a stale successful
    // lookup cannot contaminate the next part.
    enrich.reset();
    void discardIntakeDraft();
  }

  const plan = result?.add_plan ?? null;
  const pulledSomething = result !== null && hasExactPulledIdentity(result, lookedUpInput);
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
    if (
      (u.includes("digikey.") || u.includes("digi-key")) &&
      !settingsQ.data.digikey_client_secret_set
    )
      return "digikey";
    return null;
  })();

  return (
    <div data-dev-id="ingest.root" className="flex flex-col gap-5">
      {/* One network-first entry: exact identity before any CAD acquisition. */}
      <LookupHero
        input={input}
        onInput={setInput}
        onLookUp={lookUp}
        looking={looking}
        progress={enrich.progress}
        showPath={!result}
      />

      {result && plan ? (
        <Card data-dev-id="ingest.passive" className="px-4 py-4">
          <PassiveAddSection
            key={lookedUpInput}
            result={result}
            plan={plan}
            input={lookedUpInput}
            onAdded={(name) => {
              toast(toastAdded({ name }), "ok");
              reset();
            }}
            toast={toast}
          />
        </Card>
      ) : null}

      {blockedFetch ? (
        <BlockedFetchCard
          vendor={blockedKeyVendor}
          lookedUpInput={lookedUpInput}
          sourceStates={result.source_states ?? {}}
          suggestions={result.identity_suggestions ?? {}}
          onCorrect={runLookup}
        />
      ) : null}

      {staged && staged.length > 0 ? (
        <div data-dev-id="ingest.staged" className="flex flex-col gap-4">
          <Eyebrow>
            <Text id="ingest.review-eyebrow">Review and Add</Text>
          </Eyebrow>
          {staged.map(({ id, candidate, datasheetUrl, conflicts }) => (
            <CandidateCard
              key={id}
              stagedId={String(id)}
              candidate={candidate}
              conflicts={conflicts}
              initialDatasheetUrl={datasheetUrl}
              onCommitted={(created) => {
                lastCommittedPart.current = created;
                removeStaged(id);
              }}
              toast={toast}
            />
          ))}
        </div>
      ) : null}

      {nonPassive ? <NonPassiveCard result={result} /> : null}

      {/* The many-at-once lane, below the one-at-a-time lane it complements: the single-part
          flow stays the focal point of the page, and a whole sourcing document lands here. */}
      <BulkImportSection />
    </div>
  );
}


// The page's one network-first entry: the link/MPN field, the Look Up action, and either the
// live enrichment stages or the three-step path the flow is about to take.
function LookupHero({
  input,
  onInput,
  onLookUp,
  looking,
  progress,
  showPath,
}: {
  input: string;
  onInput: (value: string) => void;
  onLookUp: () => void;
  looking: boolean;
  progress: React.ComponentProps<typeof EnrichStages>["progress"];
  showPath: boolean;
}) {
  const inputAria = useText("ingest.input-aria", "Product link or part number");
  const inputPlaceholder = useText(
    "ingest.input-placeholder",
    "https://www.mouser.com/ProductDetail/... or ERJ-P03F1101V",
  );
  return (
    <div data-dev-id="ingest.hero">
      <Eyebrow className="mb-2">
        <Text id="ingest.source-eyebrow">Source</Text>
      </Eyebrow>
      <div className="flex items-center gap-2.5">
        <input
          data-dev-id="ingest.input"
          aria-label={inputAria}
          value={input}
          onChange={(e) => onInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") onLookUp();
          }}
          placeholder={inputPlaceholder}
          disabled={looking}
          className="h-[34px] min-w-0 flex-1 rounded-control border border-line2 bg-field px-3 text-sm text-t1 outline-none transition-colors focus:border-acc disabled:opacity-50"
        />
        <Button
          data-dev-id="ingest.lookup"
          variant="accent"
          onClick={onLookUp}
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
          An MPN or distributor link retains available metadata, datasheet, provenance, and source
          disagreements. Qualified passives need no provider download.
        </Text>
      </p>
      {looking ? (
        <div data-dev-id="ingest.stages" className="mt-3.5">
          <EnrichStages progress={progress} />
        </div>
      ) : showPath ? (
        <>
          {/* The only non-passive path: identity first, then one coherent network set. */}
          <div
            data-dev-id="ingest.path"
            className="mt-3.5 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-control border border-line bg-raise px-3 py-2.5"
          >
            <PathStep n={1}>
              <Text id="ingest.path-pull">Resolve Identification + Data</Text>
            </PathStep>
            <PathArrow />
            <PathStep n={2}>
              <Text id="ingest.path-add">Add Once</Text>
            </PathStep>
            <PathArrow />
            <PathStep n={3}>
              <Text id="ingest.path-capture">Collect One KiCad + Altium + STEP Package</Text>
            </PathStep>
          </div>
        </>
      ) : null}
    </div>
  );
}

// Why a look up came back with nothing: a missing distributor credential the page fetch needs,
// or an input that proved no exact manufacturer + part-number match.
function BlockedFetchCard({
  vendor,
  lookedUpInput,
  sourceStates,
  suggestions,
  onCorrect,
}: {
  vendor: string | null;
  lookedUpInput: string;
  sourceStates: Record<string, string>;
  suggestions: Record<string, string[]>;
  onCorrect: (mpn: string) => void;
}) {
  const candidates = [...new Set(Object.values(suggestions).flat())];
  const correctionLabel = useCopyFormatter("ingest.blocked-use-correction", "Use {mpn}");
  return (
    <Card data-dev-id="ingest.blocked" className="px-4 py-4">
      <div className="flex flex-col gap-3">
        <span className="text-sm text-warn">
          {vendor === "mouser" ? (
            <Text id="ingest.blocked-mouser-key">Nothing was pulled, and no Mouser API credential is set. Mouser blocks the page fetch, so the credential is what makes a Mouser link resolve. Add one in Settings under Sourcing, then look this up again.</Text>
          ) : vendor === "digikey" ? (
            <Text id="ingest.blocked-digikey-key">Nothing was pulled, and no DigiKey API credential is set. DigiKey blocks the page fetch, so the credential is what makes a DigiKey link resolve. Add one in Settings under Sourcing, then look this up again.</Text>
          ) : (
            <>
              {isUrl(lookedUpInput) ? (
                <Text id="ingest.blocked-msg">
                  Nothing was pulled. The page might have blocked the fetch, or the link is not
                  a product page. Use the exact manufacturer part number or a different product
                  link.
                </Text>
              ) : (
                <>
                  <Text id="ingest.blocked-exact">
                    No exact manufacturer and part-number match was proven for
                  </Text>{" "}
                  <span className="font-mono text-t1">{lookedUpInput}</span>
                  <Text id="ingest.blocked-exact-suffix">
                    . Stockroom rejected near matches and will not add a blank replacement.
                  </Text>
                </>
              )}
            </>
          )}
        </span>
        {sourceStates.digikey === "unavailable" ? (
          <p className="text-xs text-t2">
            <Text id="ingest.blocked-digikey-checked">DigiKey was checked and returned no exact match.</Text>
          </p>
        ) : null}
        {candidates.length > 0 ? (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-t3">
              <Text id="ingest.blocked-corrections">Possible match:</Text>
            </span>
            {candidates.map((candidate) => (
              <Button
                key={candidate}
                type="button"
                small
                aria-label={correctionLabel({ mpn: candidate })}
                onClick={() => onCorrect(candidate)}
              >
                {candidate}
              </Button>
            ))}
          </div>
        ) : null}
      </div>
    </Card>
  );
}

// What happens next for a part that needs real CAD assets, plus everything the pull returned.
function NonPassiveCard({ result }: { result: EnrichmentResult }) {
  return (
    <Card data-dev-id="ingest.nonpassive" className="px-4 py-4">
      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-2 text-sm text-t2">
          <Badge tone="neutral">
            <Text id="ingest.needs-files">Automatic Source Ladder</Text>
          </Badge>
          <span>
            <Text id="ingest.needs-msg">
              Add it once; Stockroom reuses validated evidence, searches eligible providers in
              trust order, retains fallbacks, and activates one same-download KiCad + Altium +
              STEP package.
            </Text>
          </span>
        </div>
        <PulledSummary result={result} />
        <p className="text-xs text-t3">
          <Text id="ingest.network-only">The same STEP is linked in KiCad and embedded in the Altium footprint. Identification-alone sources can contribute data but never active CAD; a visible provider window pauses just for an account gate, a protection challenge, or an explicit download choice.</Text>
        </p>
      </div>
    </Card>
  );
}
// A detached copy of one spec/alternate/conflict value for the draft. Every caller passes a value
// that came off the wire as JSON, so there is no Date, Map, function, NaN, or Infinity for a
// re-serializing clone to have rewritten - structuredClone copies the same shape without the
// stringify/parse round trip.
function jsonValue(value: unknown): JsonValue {
  return structuredClone(value) as JsonValue;
}

function networkInput(value: string): IntakeDraftNetworkInput {
  return {
    kind: isUrl(value) ? "product_url" : "mpn",
    value,
  };
}

function draftPurchase(value: StagingCandidate["purchase"][number]): IntakeDraftPurchase {
  const priceBreaks = Array.isArray(value.price_breaks)
    ? value.price_breaks.flatMap((entry) => {
        if (!entry || typeof entry !== "object" || Array.isArray(entry)) return [];
        const row = entry as Record<string, unknown>;
        const qty = Number(row.qty);
        const price = Number(row.price);
        if (!Number.isFinite(qty) || qty < 0 || !Number.isFinite(price)) return [];
        return [
          {
            qty,
            price,
            currency: typeof row.currency === "string" ? row.currency : "",
          },
        ];
      })
    : [];
  return {
    vendor: value.vendor ?? "",
    url: value.url ?? "",
    part_number: value.part_number ?? "",
    price_breaks: priceBreaks,
    stock:
      value.stock === null || (typeof value.stock === "number" && Number.isFinite(value.stock))
        ? value.stock
        : null,
    currency: value.currency ?? "",
    fetched_at: value.fetched_at ?? "",
  };
}

function draftCandidate(staged: Staged): IntakeDraftCandidate {
  const candidate = staged.candidate;
  return {
    client_id: `candidate-${staged.id}`,
    vendor: candidate.vendor,
    display_name: candidate.display_name,
    entry_name: candidate.entry_name,
    category: candidate.category,
    mpn: candidate.mpn,
    manufacturer: candidate.manufacturer,
    description: candidate.description,
    tags: [...candidate.tags],
    purchase: candidate.purchase.map(draftPurchase),
    gaps: [...candidate.gaps],
    specs: Object.entries(candidate.specs ?? {}).map(([key, value]) => ({
      key,
      value: jsonValue(value),
    })),
    alternates: Object.entries(candidate.alternates ?? {}).map(([key, values]) => ({
      key,
      values: values.map((value) => ({
        value: jsonValue(value.value),
        source: value.source,
        confidence: value.confidence,
      })),
    })),
    enrichment: Object.entries(candidate.enrichment ?? {}).map(([key, value]) => ({
      key,
      source: value.source,
      confidence: value.confidence,
    })),
    datasheet_url: staged.datasheetUrl,
    conflicts: staged.conflicts.map((conflict) => ({
      key: conflict.key,
      values: conflict.values.map((value) => ({
        value: jsonValue(value.value),
        source: value.source,
      })),
    })),
  };
}

function stagedFromDraft(id: number, saved: IntakeDraftCandidate): Staged {
  const candidate: StagingCandidate = {
    ...FILE_LESS_CANDIDATE,
    vendor: saved.vendor,
    display_name: saved.display_name,
    entry_name: saved.entry_name,
    category: saved.category,
    mpn: saved.mpn,
    manufacturer: saved.manufacturer,
    description: saved.description,
    tags: [...saved.tags],
    purchase: saved.purchase.map((purchase) => ({
      vendor: purchase.vendor,
      url: purchase.url,
      part_number: purchase.part_number,
      price_breaks: purchase.price_breaks.map((entry) => ({ ...entry })),
      stock: purchase.stock,
      currency: purchase.currency,
      fetched_at: purchase.fetched_at,
    })),
    gaps: [...saved.gaps],
    specs: Object.fromEntries(saved.specs.map(({ key, value }) => [key, value])),
    alternates: Object.fromEntries(
      saved.alternates.map(({ key, values }) => [
        key,
        values.map((value) => ({
          value: String(value.value ?? ""),
          source: value.source,
          confidence: value.confidence,
        })),
      ]),
    ),
    enrichment: Object.fromEntries(
      saved.enrichment.map(({ key, source, confidence }) => [
        key,
        { source, confidence },
      ]),
    ),
  };
  return {
    id,
    candidate,
    datasheetUrl: saved.datasheet_url,
    conflicts: saved.conflicts.map(({ key, values }) => ({
      key,
      values: values.map(({ value, source }) => ({
        value: String(value ?? ""),
        source,
      })),
    })),
  };
}

function PulledSummary({ result }: { result: EnrichmentResult }) {
  const selected = result.selected_specs;
  const rows = (
    [
      ["ingest.pulled-mpn", "MPN", sv(result.mpn)],
      ["ingest.pulled-manufacturer", "Manufacturer", sv(result.manufacturer)],
      ["ingest.pulled-description", "Description", sv(result.description)],
      [
        "ingest.pulled-package",
        "Package",
        selected ? sv(selected.Package) : sv(result.package),
      ],
    ] as [string, string, string][]
  ).filter(([, , v]) => v);
  const shownSpecs = selected ?? result.specs;
  const specCount = Object.keys(shownSpecs).filter((k) => k !== "product_url").length;
  if (rows.length === 0 && specCount === 0) {
    return (
      <span className="text-sm text-warn">
        <Text id="ingest.nothing-pulled">
          Nothing was pulled. The page might have blocked the fetch, or the link is not a product
          page.
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
        <PhotoTrigger devId="ingest.pulled-photo" url={photoUrl} partName={sv(result.mpn)} />
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
  const pulledSpecsLabel = useText("ingest.pulled-specs-label", "Pulled Specs");
  const specs = result.selected_specs ?? result.specs;
  const conflicts = result.selected_spec_conflicts ?? result.spec_conflicts ?? {};
  // one pass: a shown key is selected and projected together, rather than walking the spec bag
  // once to drop the hidden/empty keys and again to build the rows
  const specRows: { key: string; value: string; conflict: SourcedField[] | undefined }[] = [];
  for (const [k, v] of Object.entries(specs)) {
    if (SPEC_HIDDEN_KEYS.has(k) || k === "product_url" || v == null) continue;
    const value = String(v.value ?? "");
    if (value.trim() === "") continue;
    specRows.push({ key: k, value, conflict: conflicts[k] });
  }
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
        aria-label={pulledSpecsLabel}
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
                  {/* A conflict list never records a value it already holds, so the value is the
                      entry's id. */}
                  {r.conflict.map((s, i) => (
                    <span
                      key={`${s.source}|${String(s.value ?? "")}`}
                      className="inline-flex items-baseline gap-1"
                    >
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
