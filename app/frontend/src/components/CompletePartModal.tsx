/**
 * The Complete Part window: ONE place to get everything a landed part still needs. It is laid
 * out as two regions - FILES (the guided capture, the hero: get both the KiCad and the Altium
 * assets in one pass, watching a two-track checklist fill) and DETAILS (datasheet, part number,
 * manufacturer, value). The capture runs through the global CaptureProvider store, so "Keep
 * Working" can hand it off to the background status pill and the user can close this and keep
 * moving while the files land. Metadata rows use the normal edit-field seam; CAD assets can only
 * arrive through the network capture workflow, so the record stays the single source of truth.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { motion } from "motion/react";
import { assetPresent, assetsFor } from "../lib/edaTarget";
import type {
  CadSource,
  CompletionEvidence,
  PartDetail,
  ProviderOutcome,
  ProviderOutcomeStatus,
  Requirement,
} from "../api/types";
import { useCadSourceQuery } from "../api/queries";
import { useGuidedCapture, type GuidedStatus } from "../lib/useGuidedCapture";
import { captureAwaitsPerson, useCapture } from "../lib/capture";
import { CaptureRouteControls } from "./CaptureRouteControls";
import { useModalDismiss } from "../lib/useModalDismiss";
import { useToast } from "../lib/toast";
import { Text, useText } from "../lib/copy";
import { Button } from "./primitives";
import { Icon } from "./Icon";
import { DownloadIcon } from "./icons";

interface Props {
  detail: PartDetail;
  hasModel: boolean;
  onClose: () => void;
  onEditField?: (field: string, value: unknown) => void;
  busy?: boolean;
}

// The registry check glyph (dev-mode editable), sized for the small badge slots here.
// The preferred first browser provider, remembered. It never disables direct/keyless acquisition
// or the assisted job's subsequent provider fallback. Deliberately localStorage and not a
// machine-config field: it is
// a per-person preference that changes nothing another device renders differently.
// v2 resets the earlier SnapMagic-first default now that the owner selected Ultra Librarian's
// manufacturer-verified assets as the trust-order head.
const VENDOR_PREF_KEY = "stockroom.capture.vendor.v2";

function readVendorPref(): string | null {
  try {
    return window.localStorage.getItem(VENDOR_PREF_KEY);
  } catch {
    return null;
  }
}

function writeVendorPref(key: string): void {
  try {
    window.localStorage.setItem(VENDOR_PREF_KEY, key);
  } catch {
    /* a denied storage must not break the capture */
  }
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
          <motion.span
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
        <span className="text-2xs font-semibold uppercase tracking-[0.14em] text-t3">
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
      <motion.span
        className={
          "grid h-4 w-4 flex-none place-items-center rounded-full " +
          (done ? "bg-ok text-white" : "border-[1.5px] border-line2 text-transparent")
        }
        initial={false}
        animate={done ? { scale: [1, 1.28, 1] } : { scale: 1 }}
        transition={{ duration: 0.34, ease: "easeOut" }}
      >
        <CheckMark />
      </motion.span>
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
          (done ? "bg-ok/15 text-ok" : "bg-field text-t3")
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

// A needs-accurate one-liner: never promise KiCad when only Altium is missing (or vice versa).
/**
 * Which browser provider automatic acquisition should try first.
 *
 * This is the control the whole four-vendor module existed for and nothing rendered: the route
 * resolved a single DigiKey link, so a person who wanted Ultra Librarian's manufacturer-verified
 * model had no way to say so. The owner's trust ranking is not decoration -- SnapMagic blends
 * community and AI-generated models, which is exactly the defect that started the trust
 * workstream, so it must be VISIBLY last and never the silent default.
 *
 * The choice STICKS (localStorage), but it is optional: Stockroom still tries direct sources first.
 * If provider help is needed, this choice opens first and the same assisted job can advance to the
 * other provider without another visit to this window.
 */
function VendorPicker({
  sources,
  value,
  onChange,
  disabled,
}: {
  sources: CadSource[];
  value: string;
  onChange: (key: string) => void;
  disabled: boolean;
}) {
  if (sources.length < 2) return null;
  return (
    <div className="mt-3" data-dev-id="complete.cad-vendor">
      <div className="mb-1.5 text-2xs font-medium uppercase tracking-wide text-t3">
        <Text id="modal.completePart.vendor">Preferred Source</Text>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {sources.map((v) => {
          const active = v.key === value;
          return (
            <button
              key={v.key}
              type="button"
              disabled={disabled}
              onClick={() => onChange(v.key)}
              aria-pressed={active}
              title={v.instruction}
              className={
                "rounded-control border px-2.5 py-1 text-xs font-medium transition-colors " +
                "disabled:opacity-50 disabled:cursor-not-allowed " +
                (active
                  ? "border-acc bg-acc/[0.14] text-t1"
                  : "border-line2 bg-raise2 text-t2 hover:text-t1")
              }
            >
              {v.label}
              {v.aggregator ? (
                <span className="ml-1.5 text-2xs font-normal text-t3">
                  <Text id="modal.completePart.vendor-hosts">hosts all three</Text>
                </span>
              ) : null}
            </button>
          );
        })}
      </div>
      <p className="mt-1.5 text-2xs leading-snug text-t3">
        Stockroom checks saved evidence and every eligible source in order. This preference picks
        which provider is tried first; it never limits the fallback sources or the files retained.
      </p>
    </div>
  );
}

function needsSubline(_hasKicad: boolean, _hasAltium: boolean, vendor: string): string {
  return (
    "Reuse verified evidence, then search and rank eligible sources for one shared KiCad + " +
    `Altium + STEP package; open ${vendor} first only if assistance is needed.`
  );
}

function shortManifestDigest(value: string): string {
  const digest = value.trim();
  return digest.length > 20 ? `${digest.slice(0, 20)}...` : digest;
}

function evidenceReason(evidence: CompletionEvidence | null): string {
  return evidence?.reason.trim() ?? "";
}

const ROUTE_STATUS: Record<ProviderOutcomeStatus, { label: string; tone: string }> = {
  activated: { label: "Activated", tone: "text-[var(--c-ok-text)]" },
  "succeeded-retained": { label: "Retained", tone: "text-[var(--c-ok-text)]" },
  unavailable: { label: "Unavailable", tone: "text-t2" },
  "requires-human": { label: "Needs Your Input", tone: "text-[var(--c-warn-text)]" },
  blocked: { label: "Blocked", tone: "text-[var(--c-warn-text)]" },
  failed: { label: "Failed", tone: "text-[var(--c-err-text)]" },
  cancelled: { label: "Cancelled", tone: "text-[var(--c-warn-text)]" },
  "not-attempted": { label: "Not Attempted", tone: "text-[var(--c-warn-text)]" },
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

function routeReason(outcome: ProviderOutcome): string {
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
      return outcome.attempted
        ? "The route requires your input before collection can continue."
        : "This route requires a person-driven handoff and collection remains partial.";
    case "blocked":
      return "Provider access was blocked and collection remains partial.";
    case "failed":
      return "The route failed and collection remains partial.";
    case "cancelled":
      return "The route was cancelled and collection remains partial.";
    case "not-attempted":
      return "This route was not attempted after an earlier stop, so collection remains partial.";
  }
}

function ProviderRouteOutcomes({
  outcomes,
  collectionComplete,
}: {
  outcomes: ProviderOutcome[];
  collectionComplete: boolean | null;
}) {
  if (outcomes.length === 0) return null;
  return (
    <div className="mt-3.5 border-t border-line pt-3" data-dev-id="complete.cad-provider-outcomes">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-2xs font-semibold uppercase tracking-[0.14em] text-t2">
            Source Results
          </div>
          <p
            className={
              "mt-1 text-2xs leading-snug " +
              (collectionComplete ? "text-t2" : "text-[var(--c-warn-text)]")
            }
          >
            {collectionComplete
              ? "Collection Complete. Every route is settled. Unavailable means it was checked and had no exact deliverable."
              : "Collection Partial. A route requires human input, is blocked or failed, was cancelled, or was not attempted."}
          </p>
        </div>
        <span
          className={
            "flex-none rounded-full px-2 py-0.5 text-2xs font-semibold " +
            (collectionComplete
              ? "bg-ok/15 text-[var(--c-ok-text)]"
              : "bg-warn/15 text-[var(--c-warn-text)]")
          }
        >
          {collectionComplete ? "Complete" : "Partial"}
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
              <div className="col-span-2 text-2xs leading-snug text-t2">{routeReason(outcome)}</div>
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
      // Retrying stays automatic. Opening a provider window is now its own control, because
      // this button silently re-arming itself to assisted mode is what turned one failure into
      // a manual browser session nobody asked for.
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
      <span className="text-2xs font-semibold uppercase tracking-[0.14em] text-t3">{children}</span>
      <span className="h-px flex-1 bg-line" />
      {trailing}
    </div>
  );
}

export function CompletePartModal({ detail, hasModel, onClose, onEditField, busy }: Props) {
  const kicadAssets = assetsFor(detail, "kicad");
  const hasSymbol = assetPresent(kicadAssets.symbol);
  const hasFootprint = assetPresent(kicadAssets.footprint);
  const hasDatasheet = !!(detail.datasheet?.source_url || detail.datasheet?.file);

  const cadSource = useCadSourceQuery(detail.id, true);
  const cadSources = useMemo<CadSource[]>(() => cadSource.data?.sources ?? [], [cadSource.data]);
  const captureSources = useMemo(
    () => cadSources.filter((source) => source.capture_available),
    [cadSources],
  );
  // The chosen vendor persists across parts and across launches: over a 90-part sitting, one
  // decision beats ninety. With nothing stored this falls back to the head of the trust order,
  // which is the aggregator: it carries Ultra Librarian, SnapMagic and SamacSys downloads on one
  // page, so it reaches formats no single author offers. Preferring an unattended-capable
  // provider instead was briefly tried and is wrong for this library - the provider that can be
  // driven unaided is also the one with the narrowest catalogue.
  const [vendorPref, setVendorPref] = useState<string>(() => readVendorPref() ?? "");
  const vendorKey =
    captureSources.find((v) => v.key === vendorPref)?.key ?? captureSources[0]?.key ?? "";
  const chosen = captureSources.find((v) => v.key === vendorKey) ?? null;
  const pickVendor = useCallback((key: string) => {
    setVendorPref(key);
    writeVendorPref(key);
  }, []);
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
  reqToastRef.current = reqToast;
  // The dialog and Close accessible names live in attributes, so they resolve through useText.
  const dialogLabel = useText("modal.completePart.aria", "Complete this part");
  const closeLabel = useText("modal.completePart.close", "Close");
  const needs: Requirement[] = download.needs;
  const activeEvidenceReported =
    capture.active.partId === detail.id && capture.active.completionEvidenceReported;
  const completionEvidence = activeEvidenceReported
    ? capture.active.completionEvidence
    : (cadSource.data?.completion_evidence ?? null);
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
  const collectionPartial = download.collectionComplete === false;
  const cadBusy =
    download.status === "resolving" ||
    download.status === "window-open" ||
    download.status === "receiving" ||
    download.status === "attaching";
  // Only a person-driven lane opens a provider page in this person's own browser, so only those
  // runs have a route in front of anybody to finish or skip.
  const awaitsPerson =
    capture.active.partId === detail.id && captureAwaitsPerson(capture.active);
  const [captureElapsed, setCaptureElapsed] = useState(0);
  useEffect(() => {
    if (!cadBusy) {
      setCaptureElapsed(0);
      return;
    }
    const startedAt = Date.now();
    setCaptureElapsed(0);
    const timer = window.setInterval(() => {
      setCaptureElapsed(Math.max(0, Math.floor((Date.now() - startedAt) / 1000)));
    }, 1_000);
    return () => window.clearInterval(timer);
  }, [cadBusy]);
  // "Keep Working" only makes sense while a capture is actually in flight through the host.
  const canBackground = cadBusy;

  // Closing the window while a capture is still in flight must not lose it: hand it to the
  // background pill instead of dropping it. Every close path (Escape, backdrop, the X, Done)
  // goes here.
  function handleClose() {
    if (cadBusy) download.keepWorking();
    onClose();
  }

  // Escape + the Tab focus-trap + the focus move into the dialog: the shared idiom seven sibling
  // modals already use. This window is mounted only while it is open (DetailPanel unmounts it),
  // so `open` is true whenever it renders - the same call BenchPartModal and AboutModal make.
  const dialogRef = useModalDismiss(true, handleClose);
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

  const kicadRows = KICAD_ROWS.filter((r) => needs.includes(r.req));
  const sharedRows = SHARED_ROWS.filter((r) => needs.includes(r.req));
  const altiumRows = ALTIUM_ROWS.filter((r) => needs.includes(r.req));

  const requirements = useMemo(
    () =>
      [
        {
          key: "symbol",
          label: "Symbol",
          copyId: "modal.completePart.row-symbol",
          kind: "asset" as const,
          present: hasSymbol,
        },
        {
          key: "footprint",
          label: "Footprint",
          copyId: "modal.completePart.row-footprint",
          kind: "asset" as const,
          present: hasFootprint,
        },
        {
          key: "model",
          label: "3D Model",
          copyId: "modal.completePart.row-model",
          kind: "cad-only" as const,
          present: hasModel,
        },
        {
          key: "datasheet",
          label: "Datasheet",
          copyId: "modal.completePart.row-datasheet",
          kind: "url" as const,
          present: hasDatasheet,
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
  const completionTitle = completionVerified
    ? "Files Reverified"
    : completionNotRequired
      ? "CAD Files Not Required"
      : download.status === "error" && needs.length === 0
        ? "Completion Not Verified"
        : "Automatic Completion";
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
          : needsSubline(
              kicadRows.length > 0 || sharedRows.length > 0,
              altiumRows.length > 0,
              chosen?.label ?? "a model library",
            );
  // Stockroom holds ONE capture slot, so starting this part's capture stops the previous part's
  // run from being followed. The store names the part that was displaced; this window says it out
  // loud on the surface that caused it, rather than letting the earlier work vanish.
  const superseded = capture.active.partId === detail.id ? capture.active.superseded : null;
  const showDownloadMessage =
    Boolean(download.message) &&
    (!isDone ||
      download.providerOutcomes.length > 0 ||
      download.collectionComplete !== null);

  const statusTone = collectionPartial
    ? "text-[var(--c-warn-text)]"
    : download.status === "error"
      ? "text-[var(--c-err-text)]"
      : download.status === "timed-out"
        ? "text-[var(--c-warn-text)]"
        : isDone
          ? "text-[var(--c-ok-text)]"
          : "text-t3";

  return (
    <div
      className="fixed inset-0 z-[95] flex items-start justify-center overflow-y-auto bg-black/55 p-4 pt-[7vh]"
      role="presentation"
      // Dismiss on the PRESS, and only when the press lands on the scrim itself: the guard every
      // sibling modal uses. Closing on `click` meant a text-selection drag that began inside the
      // window and released on the scrim counted as a backdrop click and discarded what was typed.
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) handleClose();
      }}
    >
      <motion.div
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
              <Text id="modal.completePart.subtitle">
                Stockroom completes remaining data and one verified KiCad + Altium + STEP package.
              </Text>
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
            <section className="mb-5" data-dev-id="complete.cad">
              <Eyebrow>Files</Eyebrow>
              <div
                data-completion-evidence={completionEvidence?.state ?? "missing"}
                className={
                  "rounded-control border p-4 shadow-file transition-colors " +
                  (collectionPartial
                    ? "border-warn/40 bg-warn/[0.07]"
                    : isDone
                      ? "border-ok/40 bg-ok/[0.07]"
                      : "border-line2 bg-raise")
                }
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 items-start gap-2.5">
                    <span
                      className={
                        "mt-0.5 grid h-7 w-7 flex-none place-items-center rounded-control " +
                        (isDone ? "bg-ok/20 text-ok" : "bg-raise2 text-t1")
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
                        <Text id="modal.completePart.cad-title">Automatic Completion</Text>
                        )}
                      </div>
                      <div className="mt-0.5 text-2xs leading-snug text-t2">
                        {completionSubline}
                        {isDone && collectionPartial
                          ? " Exhaustive source collection still needs attention."
                          : ""}
                      </div>
                    </div>
                  </div>
                  {needs.length > 0 ? (
                    <SegmentMeter needs={needs} received={download.received} done={isDone} />
                  ) : null}
                </div>

                <VendorPicker
                  sources={captureSources}
                  value={vendorKey}
                  onChange={pickVendor}
                  disabled={cadBusy}
                />

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

                {superseded ? (
                  <p
                    data-dev-id="complete.superseded"
                    className="mt-3 text-xs leading-snug text-[var(--c-warn-text)]"
                  >
                    Completion for {superseded.partName || "the previous part"} was superseded when
                    this capture started. Stockroom follows one completion at a time, so that run is
                    no longer being followed here. Reopen that part to start it again.
                  </p>
                ) : null}

                <ProviderRouteOutcomes
                  outcomes={download.providerOutcomes}
                  collectionComplete={download.collectionComplete}
                />

                {cadBusy ? (
                  <div
                    className="mt-3 rounded-control border border-line bg-field px-3 py-2"
                    data-dev-id="complete.cad-live-status"
                    role="status"
                    aria-live="polite"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-xs font-semibold text-t1">Provider Work Is Active</span>
                      <span className="tnum font-mono text-2xs text-t3">
                        {captureElapsed < 1 ? "Starting" : `${captureElapsed}s`}
                      </span>
                    </div>
                    <p className="mt-1 text-2xs leading-snug text-t2">
                      Stockroom is checking saved evidence and every eligible source. If a
                      provider needs your sign-in or security check, its exact page opens in your
                      default browser; downloaded files return here automatically.
                    </p>
                    {vendorKey === "digikey" ? (
                      <p className="mt-1 text-2xs leading-snug text-[var(--c-warn-text)]">
                        If DigiKey repeats the same security check, close that provider window.
                        Stockroom will mark DigiKey blocked so you can continue with Ultra
                        Librarian instead of retrying the loop.
                      </p>
                    ) : null}
                    {/* The person's own end-of-route controls. Without them a route a person
                        cannot finish runs to its 600 s timeout, once per author route. */}
                    {awaitsPerson ? (
                      <div className="mt-2 border-t border-line pt-2">
                        <CaptureRouteControls partId={detail.id} />
                      </div>
                    ) : null}
                  </div>
                ) : null}

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
                      onClick={() => void download.start(vendorKey || undefined, "collect-all")}
                    >
                      {isDone ? (
                        "Check Other Sources"
                      ) : (
                        <Text id={cadButtonId(download.status)}>{cadLabel(download.status)}</Text>
                      )}
                    </Button>
                  ) : needs.length > 0 ? (
                    <p className="text-xs text-[var(--c-warn-text)]">
                      Add the manufacturer and exact part number before collecting files.
                    </p>
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
              </div>
            </section>
          ) : null}

          <section>
            <Eyebrow>Details</Eyebrow>
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
      </motion.div>
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
            aria-label={open ? undefined : `Add ${req.label}`}
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
      <span className="text-2xs font-medium uppercase tracking-wide text-t3">{label}</span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && onEnter?.()}
        placeholder={placeholder}
        className="h-8 w-full rounded-control border border-line2 bg-field px-2.5 text-sm text-t1 outline-none placeholder:text-t3 focus:border-acc"
      />
    </label>
  );
}
