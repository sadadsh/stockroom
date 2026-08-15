/**
 * The Complete Part window: ONE place to get everything a landed part still needs. It is laid
 * out as two regions - FILES (the guided capture, the hero: get both the KiCad and the Altium
 * assets in one pass, watching a two-track checklist fill) and DETAILS (datasheet, part number,
 * manufacturer, value). Stockroom opens the provider page; the PERSON signs in if the provider
 * asks, chooses the formats, and downloads. The capture runs through the global CaptureProvider
 * store, so "Keep Working" can hand it off to the background status pill and the user can close
 * this and keep moving while the files land. A person can also select files downloaded from the
 * active provider task; those bytes enter the exact same validation and atomic activation
 * pipeline.
 */
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import * as m from "motion/react-m";
import { useQueryClient } from "@tanstack/react-query";
import { assetPresent, assetsFor } from "../lib/edaTarget";
import type {
  CompletionEvidence,
  PartDetail,
  ProviderOutcome,
  ProviderOutcomeStatus,
  Requirement,
} from "../api/types";
import { useCadSourceQuery } from "../api/queries";
import { invalidatePartCadProjection } from "../api/partCadProjectionQueries";
import { api } from "../api/client";
import { useGuidedCapture, type GuidedStatus } from "../lib/useGuidedCapture";
import { useCapture } from "../lib/capture";
import { captureInFlight } from "../lib/captureRequirements";
import { pickHostFiles } from "../lib/hostFilePicker";
import { useModalDismiss } from "../lib/useModalDismiss";
import { useToast } from "../lib/toast";
import { Text, useCopyFormatter, useText } from "../lib/copy";
import { Button } from "./primitives";
import { Icon } from "./Icon";
import { DownloadIcon } from "./icons";

interface Props {
  detail: PartDetail;
  hasModel: boolean;
  onClose: () => void;
  onEditField?: (field: string, value: unknown) => void;
  busy?: boolean;
  autoStart?: boolean;
}

const CheckMark = () => <Icon id="modal.check" className="h-2.5 w-2.5" />;

// A segmented meter: one cell per needed file, filling as each lands. The discrete cells read
// the discrete requirements at a glance (vs one anonymous bar), and settle green on completion.
function SegmentMeter({
  needs,
  received,
  done,
}: {
  needs: Requirement[];
  received: Partial<Record<Requirement, boolean>>;
  done: boolean;
}) {
  const count = needs.filter((n) => received[n]).length;
  return (
    <div
      className="flex flex-none items-center gap-2"
      role="progressbar"
      aria-valuenow={count}
      aria-valuemin={0}
      aria-valuemax={needs.length}
      aria-valuetext={`${count} of ${needs.length} files received`}
    >
      <div className="flex gap-1">
        {needs.map((n) => (
          <m.span
            key={n}
            className={"h-2 w-5 " + (received[n] ? "bg-ok" : "bg-raise2")}
            initial={false}
            animate={
              received[n]
                ? { opacity: done ? 1 : 0.92, scaleY: [1, 1.6, 1] }
                : { opacity: 1, scaleY: 1 }
            }
            transition={{ duration: 0.3, ease: "easeOut" }}
          />
        ))}
      </div>
      <span className="tnum whitespace-nowrap font-mono text-2xs text-t3">
        {count}/{needs.length}
      </span>
    </div>
  );
}

// Symbol/Footprint share one copy id across the KiCad and Altium groups, so a single override
// serves both; the shared 3D model row carries its own.
const KICAD_ROWS = [
  { req: "kicad_symbol", label: "Symbol", copyId: "modal.completePart.row-symbol" },
  { req: "kicad_footprint", label: "Footprint", copyId: "modal.completePart.row-footprint" },
] as const;
// The 3D model is a .step - one file, referenced by BOTH the KiCad and the Altium footprint - so
// it is captured once and lives in its own Shared group, not doubled under each tool.
const SHARED_ROWS = [
  { req: "kicad_model", label: "3D Model", copyId: "modal.completePart.row-model" },
] as const;
const ALTIUM_ROWS = [
  { req: "altium_symbol", label: "Symbol", copyId: "modal.completePart.row-symbol" },
  { req: "altium_footprint", label: "Footprint", copyId: "modal.completePart.row-footprint" },
] as const;

// One EDA tool's group of needed rows, each flipping waiting -> received with a settle. The
// group renders directly in the hero card (a small tool sub-label + a hairline), so a part that
// needs only one tool - the common case in a KiCad-complete library - reads clean and balanced
// rather than as a sparse boxed panel.
function CaptureGroup({
  tool,
  copyId,
  rows,
  received,
  note,
}: {
  tool: string;
  copyId: string;
  rows: readonly { req: Requirement; label: string; copyId: string }[];
  received: Partial<Record<Requirement, boolean>>;
  note?: string;
}) {
  const done = rows.filter((r) => received[r.req]).length;
  return (
    <div data-track={tool}>
      <div className="mb-1 flex items-center gap-2">
        <span className="ui-property-label">
          <Text id={copyId}>{tool}</Text>
        </span>
        {note ? <span className="text-2xs text-t3">{note}</span> : null}
        <span className="h-px flex-1 bg-line" />
        <span className="tnum font-mono text-2xs text-t3">
          {done}/{rows.length}
        </span>
      </div>
      <div className="flex flex-col">
        {rows.map((r) => (
          <CaptureRow key={r.req} label={r.label} copyId={r.copyId} done={!!received[r.req]} />
        ))}
      </div>
    </div>
  );
}

function CaptureRow({ label, copyId, done }: { label: string; copyId: string; done: boolean }) {
  return (
    <div className="flex items-center gap-2.5 py-1" data-received={done}>
      <m.span
        className={
          "grid h-4 w-4 flex-none place-items-center rounded-full " +
          (done ? "bg-ok text-white" : "border-[1.5px] border-line2 text-transparent")
        }
        initial={false}
        animate={done ? { scale: [1, 1.28, 1] } : { scale: 1 }}
        transition={{ duration: 0.34, ease: "easeOut" }}
      >
        <CheckMark />
      </m.span>
      <span className={"flex-1 text-sm " + (done ? "text-t2" : "text-t1")}>
        <Text id={copyId}>{label}</Text>
      </span>
      {/* The waiting pill is the quiet --c-t3 tier, so it needs a surface quiet text can sit on.
          `bg-raise2` is a RAISED step: in dark it lifted this chip to 2.92:1 against the helper
          colour (VA-014), and nothing below --c-t1 clears AA on it -- --c-t2 only reaches 3.7:1
          there. The recessed `bg-field` step keeps the same visual restraint and measures 5.8:1
          dark / 5.5:1 light on the file card. Measured in CompletePartModal.contrast.test.ts. */}
      <span
        className={
          "rounded-full px-2 py-0.5 text-2xs font-medium " +
          (done ? "bg-ok/15 text-ok-text" : "bg-field text-t3")
        }
      >
        {done ? (
          <Text id="modal.completePart.checklist-received">Received</Text>
        ) : (
          <Text id="modal.completePart.checklist-needed">Needed</Text>
        )}
      </span>
    </div>
  );
}

// The default subline for a part that still needs files: what the PERSON does, in order.
const NEEDS_SUBLINE =
  "Stockroom reuses verified evidence, then opens the provider page. Sign in if the provider " +
  "asks, choose the formats you need, and download; Stockroom captures each file and validates it.";

function shortManifestDigest(value: string): string {
  const digest = value.trim();
  return digest.length > 20 ? `${digest.slice(0, 20)}...` : digest;
}

function evidenceReason(evidence: CompletionEvidence | null): string {
  return evidence?.reason.trim() ?? "";
}

const ROUTE_STATUS: Record<ProviderOutcomeStatus, { label: string; tone: string }> = {
  activated: { label: "Activated", tone: "text-ok-text" },
  "succeeded-retained": { label: "Retained", tone: "text-ok-text" },
  unavailable: { label: "Unavailable", tone: "text-t2" },
  "requires-human": { label: "Needs Your Input", tone: "text-warn-text" },
  blocked: { label: "Blocked", tone: "text-warn-text" },
  failed: { label: "Failed", tone: "text-err-text" },
  cancelled: { label: "Cancelled", tone: "text-warn-text" },
  "not-attempted": { label: "Not Attempted", tone: "text-warn-text" },
};

function routeStatus(outcome: ProviderOutcome): { label: string; tone: string } {
  const base = ROUTE_STATUS[outcome.status];
  const reason = (outcome.reason || "").toLocaleLowerCase();
  if (outcome.status === "requires-human") {
    if (/(cloudflare|captcha|challenge|security|verification)/.test(reason)) {
      return { ...base, label: "Security Check Required" };
    }
    if (/(sign in|log in|login|account|credentials)/.test(reason)) {
      return { ...base, label: "Sign In Required" };
    }
    if (/(choose|select|start).*(download|export)/.test(reason)) {
      return { ...base, label: "Download Choice Required" };
    }
  }
  if (
    outcome.status === "blocked" &&
    /(cloudflare|captcha|challenge|security|verification)/.test(reason)
  ) {
    return { ...base, label: "Security Check Blocked" };
  }
  return base;
}

function routeReason(outcome: ProviderOutcome, usable: boolean): string {
  if (outcome.reason) return outcome.reason;
  switch (outcome.status) {
    case "activated":
      return "This exact provider set is now active.";
    case "succeeded-retained":
      return `${outcome.retained} exact ${
        outcome.retained === 1 ? "file was" : "files were"
      } retained without replacing the active pair.`;
    case "unavailable":
      return "This route was checked and has no exact deliverable.";
    case "requires-human":
      return usable
        ? "This optional route needs a person-driven step before it can add another variant."
        : outcome.attempted
          ? "The route requires your input before collection can continue."
          : "This route requires a person-driven handoff and collection remains incomplete.";
    case "blocked":
      return usable
        ? "This optional provider route was blocked; the active CAD package remains usable."
        : "Provider access was blocked and collection remains incomplete.";
    case "failed":
      return usable
        ? "This optional provider route failed; the active CAD package remains usable."
        : "The route failed and collection remains incomplete.";
    case "cancelled":
      return usable
        ? "This optional provider route was cancelled; the active CAD package remains usable."
        : "The route was cancelled and collection remains incomplete.";
    case "not-attempted":
      return usable
        ? "This optional route was not attempted after an earlier stop."
        : "This route was not attempted after an earlier stop, so collection remains incomplete.";
  }
}

function ProviderRouteOutcomes({
  outcomes,
  usable,
}: {
  outcomes: ProviderOutcome[];
  usable: boolean;
}) {
  if (outcomes.length === 0) return null;
  return (
    <div className="mt-3.5 border-t border-line pt-3" data-dev-id="complete.cad-provider-outcomes">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="ui-section-title">
            <Text id="complete.source-results">Source Results</Text>
          </div>
          <p
            className={
              "mt-1 text-2xs leading-snug " + (usable ? "text-t2" : "text-warn-text")
            }
          >
            {usable ? (
              <Text id="complete.source-results-usable">
                Part Prepared. One provider supplied a complete verified CAD package.
              </Text>
            ) : (
              <Text id="complete.source-results-incomplete">
                Provider Attempt Incomplete. This part still needs files.
              </Text>
            )}
          </p>
        </div>
        <span
          className={
            "flex-none rounded-full px-2 py-0.5 text-2xs font-semibold " +
            (usable
              ? "bg-ok/15 text-ok-text"
              : "bg-warn/15 text-warn-text")
          }
        >
          {usable ? (
            <Text id="complete.source-results-status-usable">Prepared</Text>
          ) : (
            <Text id="complete.source-results-status-incomplete">Incomplete</Text>
          )}
        </span>
      </div>
      <div className="mt-2 flex flex-col divide-y divide-line">
        {outcomes.map((outcome) => {
          const status = routeStatus(outcome);
          return (
            <div
              key={outcome.route_id}
              className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-0.5 py-2"
              data-route-id={outcome.route_id}
            >
              <div className="truncate text-xs font-medium text-t1">{outcome.label}</div>
              <div className={"text-2xs font-semibold " + status.tone}>{status.label}</div>
              <div className="col-span-2 text-2xs leading-snug text-t2">
                {routeReason(outcome, usable)}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function cadLabel(status: GuidedStatus): string {
  switch (status) {
    case "resolving":
      return "Looking Up...";
    case "window-open":
    case "receiving":
      return "Working...";
    case "attaching":
      return "Attaching...";
    case "done":
      return "Files Reverified";
    case "timed-out":
    case "unavailable":
      return "Try Again";
    case "error":
      // Retrying uses the same Get Files workflow and preserves the existing evidence/session.
      return "Try Again";
    default:
      return "Get Files";
  }
}

// The copy id for each cadLabel state, so the button caption resolves its own override while
// cadLabel keeps returning the plain default string.
function cadButtonId(status: GuidedStatus): string {
  switch (status) {
    case "resolving":
      return "modal.completePart.cad-btn-resolving";
    case "window-open":
    case "receiving":
      return "modal.completePart.cad-btn-waiting";
    case "attaching":
      return "modal.completePart.cad-btn-attaching";
    case "timed-out":
    case "unavailable":
    case "error":
      return "modal.completePart.cad-btn-retry";
    default:
      return "modal.completePart.cad-btn-start";
  }
}

// Sentence-case toast copy fired as each requirement lands (body prose, not a label).
const REQ_TOAST: Record<Requirement, string> = {
  kicad_symbol: "KiCad symbol received",
  kicad_footprint: "KiCad footprint received",
  kicad_model: "3D model received",
  altium_symbol: "Altium symbol received",
  altium_footprint: "Altium footprint received",
};

// A quiet section eyebrow that gives FILES and DETAILS a real, legible hierarchy.
function Eyebrow({
  children,
  trailing,
}: {
  children: React.ReactNode;
  trailing?: React.ReactNode;
}) {
  return (
    <div className="mb-2 flex items-center gap-2.5">
      <span className="ui-property-label">{children}</span>
      <span className="h-px flex-1 bg-line" />
      {trailing}
    </div>
  );
}

export function CompletePartModal({
  detail,
  hasModel,
  onClose,
  onEditField,
  busy,
  autoStart = false,
}: Props) {
  const kicadAssets = assetsFor(detail, "kicad");
  const hasSymbol = assetPresent(kicadAssets.symbol);
  const hasFootprint = assetPresent(kicadAssets.footprint);
  const hasDatasheet = !!(detail.datasheet?.source_url || detail.datasheet?.file);

  const cadSource = useCadSourceQuery(detail.id, true);
  const cadNeeds = useMemo<Requirement[]>(() => cadSource.data?.needs ?? [], [cadSource.data]);
  const download = useGuidedCapture(detail.id, cadNeeds, detail.derived.display_name);
  const capture = useCapture();
  const { toast } = useToast();
  // Resolve the five per-requirement toast strings through the copy layer at the top (hooks run
  // unconditionally, fixed order), keeping REQ_TOAST's prose as the fallbacks. A ref carries the
  // latest resolved map into the received-watch effect without widening its dependency set.
  const reqToast: Record<Requirement, string> = {
    kicad_symbol: useText("modal.completePart.toast-kicad-symbol", REQ_TOAST.kicad_symbol),
    kicad_footprint: useText("modal.completePart.toast-kicad-footprint", REQ_TOAST.kicad_footprint),
    kicad_model: useText("modal.completePart.toast-kicad-model", REQ_TOAST.kicad_model),
    altium_symbol: useText("modal.completePart.toast-altium-symbol", REQ_TOAST.altium_symbol),
    altium_footprint: useText(
      "modal.completePart.toast-altium-footprint",
      REQ_TOAST.altium_footprint,
    ),
  };
  const reqToastRef = useRef(reqToast);
  // Synced in a layout effect, not during render: render can be replayed or thrown away, and a ref
  // written there would carry a value from a tree that never committed. Layout effects run before
  // every passive effect of this commit, so the received-watch effect below still reads this
  // render's map.
  useLayoutEffect(() => {
    reqToastRef.current = reqToast;
  });
  // The dialog and Close accessible names live in attributes, so they resolve through useText.
  const dialogLabel = useText("modal.completePart.aria", "Complete this part");
  const closeLabel = useText("modal.completePart.close", "Close");
  // A toast takes a resolved string and is written from a callback, where a hook cannot run, so
  // every message this window can raise resolves here. The counted ones carry a whole sentence per
  // number agreement rather than a stitched noun, so a rewording keeps the grammar it was written
  // with. A backend diagnostic (`error.message`) is data and is passed through untouched.
  const startFailed = useText(
    "modal.completePart.toast-start-failed",
    "Could not start source collection.",
  );
  const needs: Requirement[] = download.needs;
  // Canonical per-part readback is the only rendered completion authority. The capture store
  // retains live progress and provider diagnostics, never a terminal shadow of library truth.
  const completionEvidence = cadSource.data?.completion_evidence ?? null;
  const verifiedDigest =
    completionEvidence?.state === "verified"
      ? /^sha256:[0-9a-f]{64}$/.test(completionEvidence.manifest_digest?.trim() ?? "")
        ? completionEvidence.manifest_digest!.trim()
        : null
      : null;
  const completionVerified = verifiedDigest !== null;
  const completionNotRequired = completionEvidence?.state === "not-required";
  const completionProven = completionVerified || completionNotRequired;
  const hasExactIdentity = Boolean(detail.manufacturer.trim() && detail.mpn.trim());
  const showCad = needs.length > 0 || hasExactIdentity;
  // `needs: []` is only a projection. Completion belongs to explicit backend evidence: either a
  // non-empty immutable manifest that was reverified, or an honest policy verdict that CAD is not
  // required. Missing/unverified evidence remains incomplete even when every list is empty.
  const isDone = completionProven;
  const captureBusy =
    download.status === "resolving" ||
    download.status === "window-open" ||
    download.status === "receiving" ||
    download.status === "attaching";
  const providerPageActive = captureBusy && Boolean(capture.active.routeToken);
  const anotherCaptureBusy =
    captureInFlight(capture.active) && capture.active.partId !== detail.id;
  const cadBusy = captureBusy || anotherCaptureBusy;
  const autoStartHandled = useRef(false);
  useEffect(() => {
    if (
      !autoStart ||
      autoStartHandled.current ||
      !cadSource.data ||
      !hasExactIdentity ||
      cadBusy
    ) {
      return;
    }
    autoStartHandled.current = true;
    void download.start().catch((error) =>
      toast(error instanceof Error ? error.message : startFailed, "err"),
    );
  }, [autoStart, cadSource.data, hasExactIdentity, cadBusy, download, toast, startFailed]);



  // Closing the window while a capture is still in flight must not lose it: hand it to the
  // background pill instead of dropping it. Every close path (Escape, backdrop, the X, Done)
  // goes here.
  function handleClose() {
    if (captureBusy) download.keepWorking();
    else if (capture.active.partId === detail.id) download.reset();
    onClose();
  }

  // Escape + the Tab focus-trap + the focus move into the dialog: the shared idiom seven sibling
  // modals already use. This window is mounted only while it is open (DetailPanel unmounts it),
  // so `open` is true whenever it renders - the same call BenchPartModal and AboutModal make.
  const { ref: dialogRef, zIndex: modalZ } = useModalDismiss(true, handleClose);
  // The hook restores focus when its `open` flips false, which an unmounted window can never do.
  // Remember the control that opened this one during the first render - before the hook moves
  // focus into the dialog - and hand focus back on the way out, so closing never strands focus
  // on inert background.
  const openerRef = useRef<HTMLElement | null>(
    document.activeElement instanceof HTMLElement && document.activeElement !== document.body
      ? document.activeElement
      : null,
  );
  useEffect(() => () => openerRef.current?.focus(), []);

  // Feel-good validation: toast each requirement the moment it flips to received. `received` lives
  // in the global capture store and OUTLIVES this window, so the first pass after a mount only
  // records a baseline: without it, reopening a part replayed every toast of a run that already
  // reported, once per reopen. `null` is the pre-baseline state, which `{}` could not express.
  const prevReceived = useRef<Partial<Record<Requirement, boolean>> | null>(null);
  useEffect(() => {
    const rec = download.received;
    const seen = prevReceived.current;
    if (seen) {
      (Object.keys(rec) as Requirement[]).forEach((req) => {
        if (rec[req] && !seen[req]) toast(reqToastRef.current[req], "ok");
      });
    }
    prevReceived.current = { ...rec };
  }, [download.received, toast]);


  const requirements = useMemo(
    () =>
      detailRequirements(
        detail,
        { hasSymbol, hasFootprint, hasModel, hasDatasheet },
        showCad,
      ),
    [detail, hasSymbol, hasFootprint, hasModel, hasDatasheet, showCad],
  );
  // The header counter must count exactly what this window renders. When FILES is shown it takes
  // the whole asset story out of DETAILS, and the card itself is one more countable item - it has
  // its own settle glyph and it is done only when completion evidence proves it. Counting the
  // checklist rows alone dropped the CAD rows out of the denominator with nothing in their place,
  // so a part with complete metadata and an empty `needs` projection read "4 / 4" in the header
  // while the card directly below it said "No completion evidence is recorded" (VA-001: completion
  // is impossible until digest-bound evidence exists, and nothing in this window may claim it).
  const cadTotal = showCad ? needs.length + 1 : 0;
  const cadDone = showCad
    ? needs.filter((n) => download.received[n]).length + (isDone ? 1 : 0)
    : 0;
  const doneCount = requirements.filter((r) => r.present).length + cadDone;
  const total = requirements.length + cadTotal;

  return (
    <div
      style={{ zIndex: modalZ }}
      className="fixed inset-0 flex items-start justify-center overflow-y-auto bg-scrim p-4 pt-[7vh]"
      role="presentation"
      // Dismiss on the PRESS, and only when the press lands on the scrim itself: the guard every
      // sibling modal uses. Closing on `click` meant a text-selection drag that began inside the
      // window and released on the scrim counted as a backdrop click and discarded what was typed.
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) handleClose();
      }}
    >
      <m.div
        ref={dialogRef}
        tabIndex={-1}
        data-dev-id="complete.root"
        className="w-full max-w-[560px] overflow-hidden rounded-card border border-line2 bg-popover shadow-pop focus:outline-none"
        role="dialog"
        aria-modal="true"
        aria-label={dialogLabel}
        initial={{ opacity: 0, y: 10, scale: 0.985 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.2, ease: "easeOut" }}
      >
        <div
          data-dev-id="complete.header"
          className="flex items-start justify-between gap-3 border-b border-line bg-band px-5 py-3"
        >
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold leading-tight text-t1">
              {detail.derived.display_name}
            </div>
            <div className="mt-0.5 text-xs text-t3">
              <Text id="modal.completePart.subtitle">Open the provider, sign in if it asks, and download. Stockroom captures the download and validates it.</Text>
            </div>
          </div>
          <div className="flex flex-none items-center gap-3">
            <span className="tnum whitespace-nowrap font-mono text-xs text-t2">
              {doneCount} / {total}
            </span>
            <button
              type="button"
              onClick={handleClose}
              aria-label={closeLabel}
              className="grid h-7 w-7 place-items-center rounded-control text-t3 hover:bg-raise2 hover:text-t1"
            >
              <Icon id="modal.close" className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>

        <div className="max-h-[70vh] overflow-y-auto px-5 py-4">
          {showCad ? (
            <ProviderFilesSection
              partId={detail.id}
              hasExactIdentity={hasExactIdentity}
              needs={needs}
              download={download}
              isDone={isDone}
              completionEvidence={completionEvidence}
              verifiedDigest={verifiedDigest}
              captureBusy={captureBusy}
              anotherCaptureBusy={anotherCaptureBusy}
              cadBusy={cadBusy}
              providerPageActive={providerPageActive}
              onClose={onClose}
            />
          ) : null}

          <section>
            <Eyebrow>
              <Text id="complete.details-eyebrow">Details</Text>
            </Eyebrow>
            <div data-dev-id="complete.requirements" className="flex flex-col divide-y divide-line">
              {requirements.map((req) => (
                <Requirement key={req.key} req={req} busy={busy} onEditField={onEditField} />
              ))}
            </div>
          </section>
        </div>

        <div className="flex justify-end border-t border-line px-5 py-3.5">
          <Button data-dev-id="complete.done" variant="accent" small onClick={handleClose}>
            <Text id="modal.completePart.done">Done</Text>
          </Button>
        </div>
      </m.div>
    </div>
  );
}


/**
 * The FILES region: one card that says what the provider trip is for, what has landed, what the
 * last run reported, and the four moves available right now.
 *
 * It is a component because everything about the trip is local to it. The seconds counter and the
 * file-selection gate are two pieces of state nothing outside this card renders or reads; the two
 * host calls behind Add Files, and the twelve sentences their outcomes can produce, belong to the
 * one button that makes them; and the completion title and subline are four readings of one
 * evidence record that only this card shows. The window around it keeps what the WINDOW needs -
 * the counter in its header, and whether closing has a capture to hand off.
 *
 * Nothing here may claim completion on its own (VA-001): the title, the settle glyph and the tone
 * all follow the backend's digest-bound evidence, never an empty `needs` projection.
 */
function ProviderFilesSection({
  partId,
  hasExactIdentity,
  needs,
  download,
  isDone,
  completionEvidence,
  verifiedDigest,
  captureBusy,
  anotherCaptureBusy,
  cadBusy,
  providerPageActive,
  onClose,
}: {
  partId: string;
  hasExactIdentity: boolean;
  needs: Requirement[];
  download: ReturnType<typeof useGuidedCapture>;
  isDone: boolean;
  completionEvidence: CompletionEvidence | null;
  /** The reverified manifest digest, or null when no verified evidence exists. */
  verifiedDigest: string | null;
  captureBusy: boolean;
  anotherCaptureBusy: boolean;
  cadBusy: boolean;
  providerPageActive: boolean;
  /** Keep Working hands the capture to the background pill and leaves the window. */
  onClose: () => void;
}) {
  // Read off the evidence rather than taken as two more props, so the digest and the claim it
  // supports cannot be handed down disagreeing with each other.
  const completionVerified = verifiedDigest !== null;
  const completionNotRequired = completionEvidence?.state === "not-required";
  // Rendered as a computed value rather than as JSX children, so it resolves its override here.
  const needsSubline = useText("modal.completePart.cad-subline", NEEDS_SUBLINE);
  // How long the trip has been out. Only a route waiting for human input opens the embedded
  // provider page, so this counter belongs to the live band and to nothing else.
  const [captureElapsed, setCaptureElapsed] = useState(0);
  useEffect(() => {
    if (!captureBusy) {
      setCaptureElapsed(0);
      return;
    }
    const startedAt = Date.now();
    setCaptureElapsed(0);
    const timer = window.setInterval(() => {
      setCaptureElapsed(Math.max(0, Math.floor((Date.now() - startedAt) / 1000)));
    }, 1_000);
    return () => window.clearInterval(timer);
  }, [captureBusy]);


  const kicadRows = KICAD_ROWS.filter((r) => needs.includes(r.req));
  const sharedRows = SHARED_ROWS.filter((r) => needs.includes(r.req));
  const altiumRows = ALTIUM_ROWS.filter((r) => needs.includes(r.req));

  const completionTitle = completionVerified
    ? "Files Reverified"
    : completionNotRequired
      ? "CAD Files Not Required"
      : download.status === "error" && needs.length === 0
        ? "Completion Not Verified"
        : "Files From The Provider";
  const completionSubline = completionVerified
    ? `Reverified from ${shortManifestDigest(verifiedDigest)}.${
        evidenceReason(completionEvidence) ? ` ${evidenceReason(completionEvidence)}` : ""
      }`
    : completionNotRequired
      ? evidenceReason(completionEvidence) || "This part has no required CAD deliverables."
      : completionEvidence?.state === "unverified"
        ? evidenceReason(completionEvidence) ||
          "The last completion attempt did not produce verified evidence."
        : needs.length === 0
          ? "No completion evidence is recorded. Run verification before treating this part as complete."
          : needsSubline;
  const showDownloadMessage =
    Boolean(download.message) && (!isDone || download.providerOutcomes.length > 0);

  const statusTone = isDone
    ? "text-ok-text"
    : download.status === "error"
      ? "text-err-text"
      : download.status === "timed-out"
        ? "text-warn-text"
        : "text-t3";

  return (
    <section className="mb-5" data-dev-id="complete.cad">
      <Eyebrow>
        <Text id="complete.files-eyebrow">Files</Text>
      </Eyebrow>
      <div
        data-completion-evidence={completionEvidence?.state ?? "missing"}
        className={
          "rounded-control border p-4 shadow-file transition-colors " +
          (isDone ? "border-ok/40 bg-ok/[0.07]" : "border-line2 bg-raise")
        }
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-2.5">
            <span
              className={
                "mt-0.5 grid h-7 w-7 flex-none place-items-center rounded-control " +
                (isDone ? "bg-ok/20 text-ok-text" : "bg-raise2 text-t1")
              }
            >
              {isDone ? <CheckMark /> : <DownloadIcon className="h-3.5 w-3.5" />}
            </span>
            <div className="min-w-0">
              <div className="text-sm font-semibold text-t1">
                {completionVerified ? (
                  <Text id="modal.completePart.cad-verified-title">
                    {completionTitle}
                  </Text>
                ) : completionNotRequired ? (
                  <Text id="modal.completePart.cad-not-required-title">
                    {completionTitle}
                  </Text>
                ) : download.status === "error" && needs.length === 0 ? (
                  <Text id="modal.completePart.cad-unverified-title">
                    {completionTitle}
                  </Text>
                ) : (
                <Text id="modal.completePart.cad-title">Files From The Provider</Text>
                )}
              </div>
              <div className="mt-0.5 text-2xs leading-snug text-t2">
                {completionSubline}
              </div>
            </div>
          </div>
          {needs.length > 0 ? (
            <SegmentMeter needs={needs} received={download.received} done={isDone} />
          ) : null}
        </div>

        {needs.length > 0 ? (
          <div data-dev-id="complete.cad-checklist" className="mt-3.5 flex flex-col gap-3">
            {kicadRows.length > 0 ? (
              <CaptureGroup
                tool="KiCad"
                copyId="modal.completePart.group-kicad"
                rows={kicadRows}
                received={download.received}
              />
            ) : null}
            {sharedRows.length > 0 ? (
              <CaptureGroup
                tool="Shared"
                copyId="modal.completePart.group-shared"
                rows={sharedRows}
                received={download.received}
                note="Used by KiCad and Altium"
              />
            ) : null}
            {altiumRows.length > 0 ? (
              <CaptureGroup
                tool="Altium"
                copyId="modal.completePart.group-altium"
                rows={altiumRows}
                received={download.received}
              />
            ) : null}
          </div>
        ) : null}

        {showDownloadMessage ? (
          <p className={"mt-3 text-xs " + statusTone}>{download.message}</p>
        ) : null}

        <ProviderRouteOutcomes outcomes={download.providerOutcomes} usable={isDone} />

        {captureBusy ? (
          <div
            className="mt-3 rounded-control border border-line bg-field px-3 py-2"
            data-dev-id="complete.cad-live-status"
            role="status"
            aria-live="polite"
          >
            <div className="flex items-center justify-between gap-3">
              <span className="text-xs font-semibold text-t1">
                {providerPageActive ? (
                  <Text id="modal.completePart.live-provider-open">
                    Provider Page Is Prepared
                  </Text>
                ) : (
                  <Text id="modal.completePart.live-processing">
                    Processing Downloaded Files
                  </Text>
                )}
              </span>
              <span className="tnum font-mono text-2xs text-t3">
                {captureElapsed < 1 ? (
                  <Text id="modal.completePart.live-starting">Starting</Text>
                ) : (
                  `${captureElapsed}s`
                )}
              </span>
            </div>
            <p className="mt-1 text-2xs leading-snug text-t2">
              {providerPageActive ? (
                <Text id="modal.completePart.provider-page-live">The provider page is open. Sign in if it asks, choose the formats this part needs, and download. Stockroom captures the download and validates it; use the permanent Stockroom and Provider controls above the page to switch without losing it.</Text>
              ) : (
                <Text id="modal.completePart.provider-page-processing">Stockroom received the download and is validating, converting, and attaching its KiCad, Altium, and STEP files as one provider set. No one needs to find or import the downloads.</Text>
              )}
            </p>
          </div>
        ) : null}

        <CompletionActions
          partId={partId}
          hasExactIdentity={hasExactIdentity}
          needs={needs}
          download={download}
          isDone={isDone}
          captureBusy={captureBusy}
          anotherCaptureBusy={anotherCaptureBusy}
          cadBusy={cadBusy}
          onClose={onClose}
        />
      </div>
    </section>
  );
}

/**
 * The four moves available on the FILES card: start (or refresh) the trip, add files that were
 * downloaded by hand, come back to the provider page, and leave without dropping the capture.
 *
 * A component because everything behind these buttons is theirs alone. The file-selection gate is
 * one boolean nothing else on the card renders or reads; the two host calls behind Add Files, and
 * the twelve sentences their outcomes can produce, exist for one control; and which of the four
 * are offered at all is a question about the capture slot, not about the evidence the card above
 * is showing.
 */
function CompletionActions({
  partId,
  hasExactIdentity,
  needs,
  download,
  isDone,
  captureBusy,
  anotherCaptureBusy,
  cadBusy,
  onClose,
}: {
  partId: string;
  hasExactIdentity: boolean;
  needs: Requirement[];
  download: ReturnType<typeof useGuidedCapture>;
  isDone: boolean;
  captureBusy: boolean;
  anotherCaptureBusy: boolean;
  cadBusy: boolean;
  /** Keep Working hands the capture to the background pill and leaves the window. */
  onClose: () => void;
}) {
  const capture = useCapture();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [selectedFilesBusy, setSelectedFilesBusy] = useState(false);
  // A toast takes a resolved string and is written from a callback, where a hook cannot run, so
  // every message this card can raise resolves here. The counted ones carry a whole sentence per
  // number agreement rather than a stitched noun, so a rewording keeps the grammar it was written
  // with. A backend diagnostic (`error.message`) is data and is passed through untouched.
  const showProviderFailed = useText(
    "modal.completePart.toast-show-provider-failed",
    "Could not show the provider page.",
  );
  const completionFailed = useText(
    "modal.completePart.toast-completion-failed",
    "Could not start completion.",
  );
  const addFilesFailed = useText(
    "modal.completePart.toast-add-files-failed",
    "Could not add the selected files.",
  );
  const queuedOne = useCopyFormatter(
    "modal.completePart.toast-queued-one",
    "Stockroom added {count} selected file to this provider task.",
  );
  const queuedMany = useCopyFormatter(
    "modal.completePart.toast-queued-many",
    "Stockroom added {count} selected files to this provider task.",
  );
  const attachedDoneOne = useCopyFormatter(
    "modal.completePart.toast-attached-done-one",
    "Component complete. Stockroom attached {count} CAD role.{suffix}",
  );
  const attachedDoneMany = useCopyFormatter(
    "modal.completePart.toast-attached-done-many",
    "Component complete. Stockroom attached {count} CAD roles.{suffix}",
  );
  const attachedLeftOne = useCopyFormatter(
    "modal.completePart.toast-attached-left-one",
    "Stockroom attached {count} CAD role; {remaining} still needed.{suffix}",
  );
  const attachedLeftMany = useCopyFormatter(
    "modal.completePart.toast-attached-left-many",
    "Stockroom attached {count} CAD roles; {remaining} still needed.{suffix}",
  );
  // The clause that gets appended when a selection held things this part cannot use. It rides into
  // the sentences above through `{suffix}`, but it is authored prose in its own right, so it holds
  // its own ids rather than being the one phrase in that toast nobody can reword.
  const ignoredOne = useCopyFormatter(
    "modal.completePart.toast-ignored-one",
    " {count} unrelated or unreadable item was ignored.",
  );
  const ignoredMany = useCopyFormatter(
    "modal.completePart.toast-ignored-many",
    " {count} unrelated or unreadable items were ignored.",
  );
  // The tooltip that names the part holding the one capture slot, and the stand-in for a part the
  // slot has not named yet. Both live in an attribute, so both resolve as strings.
  const anotherRunningTitle = useCopyFormatter(
    "modal.completePart.another-running-title",
    "Finish the active completion for {name} first.",
  );
  const currentPartName = useText("modal.completePart.current-part", "the current part");
  // "Keep Working" only makes sense while a capture is actually in flight through the host.
  const canBackground = captureBusy;
  const canSelectDownloadedFiles =
    capture.active.partId === partId &&
    captureBusy &&
    Boolean(
      capture.active.workflowItemId &&
        capture.active.vendor &&
        capture.active.url &&
        capture.active.routeToken,
    );
  const canShowProvider =
    capture.active.partId === partId &&
    !isDone &&
    Boolean(capture.active.workflowItemId);

  async function showProvider() {
    try {
      await capture.showProvider();
    } catch (error) {
      toast(error instanceof Error ? error.message : showProviderFailed, "err");
    }
  }

  async function addFiles() {
    setSelectedFilesBusy(true);
    try {
      const paths = await pickHostFiles("cad-recovery");
      if (paths.length === 0) return;
      const vendor = capture.active.vendor;
      const detailUrl = capture.active.url;
      const workflowItemId = capture.active.workflowItemId;
      const routeToken = capture.active.routeToken;
      if (
        canSelectDownloadedFiles &&
        vendor &&
        detailUrl &&
        workflowItemId &&
        routeToken
      ) {
        const result = await api.attachSelectedCaptureFiles({
          partId,
          workflowItemId,
          paths,
          vendor,
          detailUrl,
          routeToken,
        });
        const queued = result.queued_files === 1 ? queuedOne : queuedMany;
        toast(queued({ count: result.queued_files }), "ok");
      } else {
        const result = await api.addPartFiles({ partId, paths });
        await invalidatePartCadProjection(queryClient, partId);
        const attached = result.attached.length;
        const ignored = result.ignored.length;
        const suffix = ignored
          ? (ignored === 1 ? ignoredOne : ignoredMany)({ count: ignored })
          : "";
        const sentence = result.complete
          ? attached === 1
            ? attachedDoneOne({ count: attached, suffix })
            : attachedDoneMany({ count: attached, suffix })
          : attached === 1
            ? attachedLeftOne({ count: attached, remaining: result.remaining.length, suffix })
            : attachedLeftMany({ count: attached, remaining: result.remaining.length, suffix });
        toast(sentence, attached ? "ok" : "err");
      }
    } catch (error) {
      toast(error instanceof Error ? error.message : addFilesFailed, "err");
    } finally {
      setSelectedFilesBusy(false);
    }
  }

  return (
    <div
      data-dev-id="complete.cad-actions"
      className="mt-3 flex flex-wrap items-center gap-2"
    >
      {hasExactIdentity ? (
        <Button
          variant={isDone ? "default" : "accent"}
          small
          icon={<DownloadIcon className="h-3.5 w-3.5" />}
          disabled={cadBusy}
          title={
            anotherCaptureBusy
              ? anotherRunningTitle({
                  name: capture.active.partName || currentPartName,
                })
              : undefined
          }
          onClick={() =>
            void download
              .start()
              .catch((error) =>
                toast(error instanceof Error ? error.message : completionFailed, "err"),
              )
          }
        >
          {anotherCaptureBusy ? (
            <Text id="complete.cad-another-running">Another Part Is Running</Text>
          ) : isDone ? (
            <Text id="complete.cad-refresh-sources">Refresh Sources</Text>
          ) : (
            <Text id={cadButtonId(download.status)}>{cadLabel(download.status)}</Text>
          )}
        </Button>
      ) : needs.length > 0 ? (
        <p className="text-xs text-warn-text">
          <Text id="complete.identity-required">
            Add the manufacturer and exact part number before collecting files.
          </Text>
        </p>
      ) : null}
      {hasExactIdentity ? (
        <Button
          variant="default"
          small
          disabled={selectedFilesBusy || anotherCaptureBusy}
          onClick={() => void addFiles()}
        >
          {selectedFilesBusy ? (
            <Text id="modal.completePart.add-files-busy">Processing Files...</Text>
          ) : (
            <Text id="modal.completePart.add-files">Add Files</Text>
          )}
        </Button>
      ) : null}
      {canShowProvider ? (
        <Button variant="default" small onClick={() => void showProvider()}>
          <Text id="complete.show-provider">Show Provider</Text>
        </Button>
      ) : null}
      {canBackground ? (
        <button
          type="button"
          onClick={() => {
            download.keepWorking();
            onClose();
          }}
          className="ml-auto rounded-control px-2.5 py-1 text-xs font-medium text-t2 hover:bg-raise2 hover:text-t1"
        >
          <Text id="modal.completePart.keep-working">Keep Working</Text>
        </button>
      ) : null}
    </div>
  );
}


type Req = {
  key: string;
  label: string;
  copyId: string;
  kind: "asset" | "cad-only" | "url" | "text";
  present: boolean;
};


/**
 * The DETAILS checklist: the metadata rows this window can show and edit, in reading order.
 *
 * A pure builder rather than markup, because the window counts these rows in its header as well as
 * rendering them, and one list computed once is the only way those two can agree.
 */
function detailRequirements(
  detail: PartDetail,
  present: {
    hasSymbol: boolean;
    hasFootprint: boolean;
    hasModel: boolean;
    hasDatasheet: boolean;
  },
  showCad: boolean,
): Req[] {
  return [
    {
      key: "symbol",
      label: "Symbol",
      copyId: "modal.completePart.row-symbol",
      kind: "asset" as const,
      present: present.hasSymbol,
    },
    {
      key: "footprint",
      label: "Footprint",
      copyId: "modal.completePart.row-footprint",
      kind: "asset" as const,
      present: present.hasFootprint,
    },
    {
      key: "model",
      label: "3D Model",
      copyId: "modal.completePart.row-model",
      kind: "cad-only" as const,
      present: present.hasModel,
    },
    {
      key: "datasheet",
      label: "Datasheet",
      copyId: "modal.completePart.row-datasheet",
      kind: "url" as const,
      present: present.hasDatasheet,
    },
    {
      key: "mpn",
      label: "Part Number",
      copyId: "modal.completePart.row-mpn",
      kind: "text" as const,
      present: !!detail.mpn,
    },
    {
      key: "manufacturer",
      label: "Manufacturer",
      copyId: "modal.completePart.row-manufacturer",
      kind: "text" as const,
      present: !!detail.manufacturer,
    },
    {
      key: "description",
      label: "Value / Description",
      copyId: "modal.completePart.row-description",
      kind: "text" as const,
      present: !!detail.derived.description,
    },
    // When the FILES section is shown it owns the whole asset story (symbol, footprint,
    // and 3D model), so drop those from DETAILS to avoid the same asset word reading
    // "Added" here and "Needed" in FILES at once. DETAILS then stays metadata-only.
  ].filter(
    (r) => !(showCad && (r.key === "model" || r.key === "symbol" || r.key === "footprint")),
  );
}

function Requirement({
  req,
  busy,
  onEditField,
}: {
  req: Req;
  busy?: boolean;
  onEditField?: (field: string, value: unknown) => void;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const editable = !!onEditField && (req.kind === "url" || req.kind === "text");
  // The accessible name of a control whose visible label is the bare verb, so the name is where the
  // object of that verb is stated. The requirement's own label in the hole is registry vocabulary.
  const addName = useCopyFormatter("modal.completePart.req-add-aria", "Add {field}");

  function applyValue(field: string) {
    if (!text.trim()) return;
    onEditField?.(field, text.trim());
    setOpen(false);
    setText("");
  }

  return (
    <div className="py-2" data-dev-id="complete.requirement-row">
      <div className="flex items-center gap-2.5">
        <span
          className={
            "grid h-4 w-4 flex-none place-items-center rounded-full " +
            (req.present ? "bg-ok text-white" : "border-[1.5px] border-line2 text-transparent")
          }
        >
          <CheckMark />
        </span>
        <span className={"flex-1 text-sm " + (req.present ? "text-t2" : "font-medium text-t1")}>
          <Text id={req.copyId}>{req.label}</Text>
        </span>
        {req.present ? (
          <span className="text-2xs text-t3">
            <Text id="modal.completePart.req-added">Added</Text>
          </span>
        ) : req.kind === "cad-only" ? (
          <span className="text-2xs text-t3">
            <Text id="modal.completePart.req-from-cad">From network collection</Text>
          </span>
        ) : req.kind === "asset" ? (
          <span className="text-2xs text-t3">
            <Text id="modal.completePart.req-from-cad">From network collection</Text>
          </span>
        ) : editable ? (
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-label={open ? undefined : addName({ field: req.label })}
            className="rounded-control border border-line2 px-2.5 py-1 text-xs font-semibold text-t2 hover:border-acc hover:text-t1"
          >
            {open ? (
              <Text id="modal.completePart.req-cancel">Cancel</Text>
            ) : (
              <Text id="modal.completePart.req-add">Add</Text>
            )}
          </button>
        ) : null}
      </div>

      {open && !req.present ? (
        <div className="mt-2.5 pl-6.5">
          <div className="flex flex-wrap items-end gap-2">
            <Field
              label={req.kind === "url" ? "URL" : req.label}
              value={text}
              onChange={setText}
              placeholder={req.kind === "url" ? "https://..." : ""}
              wide
              onEnter={() => applyValue(req.key)}
            />
            <Button
              small
              variant="accent"
              disabled={busy || !text.trim()}
              onClick={() => applyValue(req.key)}
            >
              <Text id="modal.completePart.save">Save</Text>
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  placeholder,
  wide,
  onEnter,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  wide?: boolean;
  onEnter?: () => void;
}) {
  return (
    <label className={"flex flex-col gap-1 " + (wide ? "min-w-[280px] flex-1" : "")}>
      <span className="ui-property-label">{label}</span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && onEnter?.()}
        placeholder={placeholder}
        className="h-8 w-full rounded-control border border-line2 bg-field px-2.5 text-sm text-t1 outline-none placeholder:text-t3 focus:border-focus"
      />
    </label>
  );
}
