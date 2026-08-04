/**
 * Complete Component: one place to get everything this component still needs, from ONE provider.
 *
 * It replaces the Complete Part window Slice 2 removed from the component route, and it is built
 * around the product rule rather than around a file list: Stockroom does not mix CAD across
 * providers, so the person's job is to find a provider that can supply the whole set, go there,
 * download it, and come back. Every band on this sheet serves one step of that trip:
 *
 *   Providers   which provider can supply everything, and how to reach each one
 *   The Trip    which component and which provider are in hand, and what the browser is doing
 *   Progress    what has landed so far, and the report when a run ends well or badly
 *   Sets        the retained provider sets, the candidates behind them, and which one is in force
 *
 * Nothing here is a second capture state machine: the ONE global capture store owns the run, and
 * `useGuidedCapture` is the same adapter every other completion surface binds to. The retained-set
 * chooser is `CadVariantSection` unchanged, because a second chooser is a second answer to "which
 * files are active" waiting to disagree with the first.
 *
 * Stockroom never operates a provider page. It opens the one the person asked for; they sign in if
 * the provider asks, choose the formats, and download.
 */
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { useCadSourceQuery, useSetProviderCoverage } from "../../api/queries";
import { invalidatePartCadProjection } from "../../api/partCadProjectionQueries";
import type { ProviderOutcome, ProviderOutcomeStatus, Requirement } from "../../api/types";
import type {
  ComponentIdentityView,
  ComponentProvidersView,
  CoverageArtifact,
  ProviderCoverageRow,
} from "../../api/workspaceTypes";
import { captureInFlight, useCapture, REQ_LABELS } from "../../lib/capture";
import { useGuidedCapture } from "../../lib/useGuidedCapture";
import { pickHostFiles } from "../../lib/hostFilePicker";
import { Text, useCopyFormatter, useText } from "../../lib/copy";
import { useToast } from "../../lib/toast";
import { CadVariantSection } from "../CadVariantSection";
import { Badge, Button } from "../primitives";
import {
  ProviderCoverageMatrix,
  useProviderMatrixLabels,
  type UserCoverageStatus,
} from "./ProviderCoverageMatrix";

/** What one provider route ended up doing. Presentation labels only; the verdict is the backend's. */
const OUTCOME_LABEL: Record<ProviderOutcomeStatus, string> = {
  activated: "Activated",
  "succeeded-retained": "Retained",
  unavailable: "Unavailable",
  "requires-human": "Needs Your Input",
  blocked: "Blocked",
  failed: "Failed",
  cancelled: "Cancelled",
  "not-attempted": "Not Attempted",
};

/** The eight route verdicts, resolved through the copy layer in one fixed hook order. */
function useOutcomeLabels(): Record<ProviderOutcomeStatus, string> {
  return {
    activated: useText("component-browser.provider-outcome-activated", OUTCOME_LABEL.activated),
    "succeeded-retained": useText(
      "component-browser.provider-outcome-retained",
      OUTCOME_LABEL["succeeded-retained"],
    ),
    unavailable: useText(
      "component-browser.provider-outcome-unavailable",
      OUTCOME_LABEL.unavailable,
    ),
    "requires-human": useText(
      "component-browser.provider-outcome-requires-human",
      OUTCOME_LABEL["requires-human"],
    ),
    blocked: useText("component-browser.provider-outcome-blocked", OUTCOME_LABEL.blocked),
    failed: useText("component-browser.provider-outcome-failed", OUTCOME_LABEL.failed),
    cancelled: useText("component-browser.provider-outcome-cancelled", OUTCOME_LABEL.cancelled),
    "not-attempted": useText(
      "component-browser.provider-outcome-not-attempted",
      OUTCOME_LABEL["not-attempted"],
    ),
  };
}

const OUTCOME_TONE: Record<ProviderOutcomeStatus, string> = {
  activated: "text-ok",
  "succeeded-retained": "text-ok",
  unavailable: "text-t2",
  "requires-human": "text-warn",
  blocked: "text-warn",
  failed: "text-err",
  cancelled: "text-warn",
  "not-attempted": "text-warn",
};

// `devId` is optional because the Providers band's addressable element is the MATRIX inside it,
// not the frame around it: two ids for one thing is two answers to "what did I click".
function Band({
  devId,
  title,
  copyId,
  trailing,
  children,
}: {
  devId?: string;
  title: string;
  copyId: string;
  trailing?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section
      data-dev-id={devId}
      aria-label={title}
      className="rounded-card border border-line bg-raise px-3 py-2.5"
    >
      <header className="mb-2 flex flex-wrap items-center gap-2">
        <h3 className="min-w-0 truncate text-xs font-semibold text-t1">
          <Text id={copyId}>{title}</Text>
        </h3>
        {trailing}
      </header>
      {children}
    </section>
  );
}

export function CompleteComponentSheet({
  componentId,
  identity,
  providers,
  onClose,
}: {
  componentId: string;
  identity: ComponentIdentityView;
  providers: ComponentProvidersView;
  /** Leaving for the workspace is a real step of the trip, so this sheet can take it. */
  onClose: () => void;
}) {
  const capture = useCapture();
  const cadSource = useCadSourceQuery(componentId, true);
  const needs: Requirement[] = cadSource.data?.needs ?? [];
  const download = useGuidedCapture(componentId, needs, identity.displayName);
  const correction = useSetProviderCoverage(componentId);
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const matrixLabels = useProviderMatrixLabels();
  const outcomeLabels = useOutcomeLabels();
  const [importing, setImporting] = useState(false);

  // Every requirement label resolved up front: hooks run unconditionally, in a fixed order, and
  // the capture store's own defaults stay the fallbacks.
  const reqLabels: Record<Requirement, string> = {
    kicad_symbol: useText("component-browser.provider-req-kicad-symbol", REQ_LABELS.kicad_symbol),
    kicad_footprint: useText(
      "component-browser.provider-req-kicad-footprint",
      REQ_LABELS.kicad_footprint,
    ),
    kicad_model: useText("component-browser.provider-req-model", REQ_LABELS.kicad_model),
    altium_symbol: useText(
      "component-browser.provider-req-altium-symbol",
      REQ_LABELS.altium_symbol,
    ),
    altium_footprint: useText(
      "component-browser.provider-req-altium-footprint",
      REQ_LABELS.altium_footprint,
    ),
  };

  const componentLabel = useText("component-browser.provider-component", "Component");
  const providerLabel = useText("component-browser.provider-provider", "Provider");
  const browserLabel = useText("component-browser.provider-browser-state", "Provider Page");
  const noProvider = useText("component-browser.provider-none-active", "None open");
  const receivedLabel = useText("component-browser.provider-received", "Received");
  const neededLabel = useText("component-browser.provider-needed", "Needed");
  const noNeeds = useText(
    "component-browser.provider-no-needs",
    "Stockroom is not waiting on any file for this component.",
  );
  const noReport = useText(
    "component-browser.provider-no-report",
    "No provider run has reported for this component yet.",
  );
  const identityMissing = useText(
    "component-browser.provider-identity-missing",
    "Add the manufacturer and the exact part number before going to a provider.",
  );
  const anotherRunning = useText(
    "component-browser.provider-another-running",
    "Another component's provider trip is still running.",
  );
  const importFailed = useText(
    "component-browser.provider-import-failed",
    "Could not import the selected files.",
  );
  // Placeholder entries, not fragments: the count used to be concatenated onto a headless phrase,
  // which meant the word order lived in the JavaScript and nobody could reword the sentence.
  const importQueued = useCopyFormatter(
    "component-browser.provider-import-queued",
    "Added {count} files to the open provider task",
  );
  const importAttached = useCopyFormatter(
    "component-browser.provider-import-attached",
    "Attached {count} CAD roles",
  );
  const importIgnored = useText(
    "component-browser.provider-import-ignored",
    "Nothing in the selection belonged to this component.",
  );
  const showFailed = useText(
    "component-browser.provider-show-failed",
    "Could not bring the provider page back.",
  );
  const openFailed = useText(
    "component-browser.provider-open-failed",
    "Could not open that provider.",
  );
  const correctionFailed = useText(
    "component-browser.provider-correction-failed",
    "Could not record your answer.",
  );
  const correctionSaved = useCopyFormatter(
    "component-browser.provider-correction-saved",
    "Your answer was recorded for {provider}",
  );

  const busy = captureInFlight(capture.active);
  const ownsCapture = capture.active.partId === componentId;
  const tripBusy = ownsCapture && busy;
  const hasExactIdentity = Boolean(identity.manufacturer.trim() && identity.mpn.trim());
  const openDisabledReason = !hasExactIdentity
    ? identityMissing
    : busy && !ownsCapture
      ? anotherRunning
      : "";

  const browserState = useBrowserState(download.status, tripBusy);

  function openProvider(row: ProviderCoverageRow) {
    void download.start(row.id).catch((error) => {
      toast(error instanceof Error ? error.message : openFailed, "err");
    });
  }

  function correct(
    row: ProviderCoverageRow,
    artifact: CoverageArtifact,
    status: UserCoverageStatus,
  ) {
    correction.mutate(
      { provider: row.id, artifact, status },
      {
        onSuccess: () => toast(correctionSaved({ provider: row.label }), "ok"),
        onError: (error) =>
          toast(error instanceof Error ? error.message : correctionFailed, "err"),
      },
    );
  }

  async function showProvider() {
    try {
      await capture.showProvider();
    } catch (error) {
      toast(error instanceof Error ? error.message : showFailed, "err");
    }
  }

  /**
   * Bring the person back to Stockroom without losing the trip.
   *
   * The provider page covers the whole window while it is up, so "back" is not a browser action
   * here: it is handing the running capture to the background status pill and returning to the
   * component. The capture keeps running and keeps capturing what is downloaded.
   */
  function returnToStockroom() {
    download.keepWorking();
    onClose();
  }

  async function importFiles() {
    setImporting(true);
    try {
      const paths = await pickHostFiles("cad-recovery");
      if (paths.length === 0) return;
      const active = capture.active;
      if (
        ownsCapture &&
        active.workflowItemId &&
        active.vendor &&
        active.url &&
        active.routeToken
      ) {
        const result = await api.attachSelectedCaptureFiles({
          partId: componentId,
          workflowItemId: active.workflowItemId,
          paths,
          vendor: active.vendor,
          detailUrl: active.url,
          routeToken: active.routeToken,
        });
        toast(importQueued({ count: result.queued_files }), "ok");
        return;
      }
      const result = await api.addPartFiles({ partId: componentId, paths });
      await invalidatePartCadProjection(queryClient, componentId);
      toast(
        result.attached.length
          ? importAttached({ count: result.attached.length })
          : importIgnored,
        result.attached.length ? "ok" : "err",
      );
    } catch (error) {
      toast(error instanceof Error ? error.message : importFailed, "err");
    } finally {
      setImporting(false);
    }
  }

  const outcomes: ProviderOutcome[] = download.providerOutcomes;
  const receivedCount = needs.filter((need) => download.received[need]).length;

  return (
    <div data-dev-id="component-browser.complete-component" className="flex flex-col gap-3">
      <p className="text-2xs leading-snug text-t2">
        <Text id="component-browser.provider-lede">
          A component's CAD comes from one provider's verified set. Find a provider that can
          supply all three, open it, sign in if it asks, choose the formats you need, and download.
        </Text>
      </p>

      <Band
        title="Providers"
        copyId="component-browser.provider-band-providers"
        trailing={
          providers.completeProviders.length > 0 ? (
            <Badge tone="ok" size="sm">
              <Text
                id="component-browser.provider-complete-count"
                values={{ count: providers.completeProviders.length }}
              >
                {"{count} Complete Set"}
              </Text>
            </Badge>
          ) : (
            <span className="text-2xs text-t3">
              <Text id="component-browser.provider-none-complete">
                No provider can supply the whole set yet.
              </Text>
            </span>
          )
        }
      >
        <ProviderCoverageMatrix
          componentId={componentId}
          coverage={providers}
          labels={matrixLabels}
          onOpenProvider={openProvider}
          onCorrect={correct}
          openDisabledReason={openDisabledReason}
          correcting={
            correction.isPending && correction.variables
              ? {
                  provider: correction.variables.provider,
                  artifact: correction.variables.artifact,
                }
              : null
          }
        />
      </Band>

      <Band
        devId="component-browser.provider-browser"
        title="The Provider Trip"
        copyId="component-browser.provider-band-trip"
      >
        <dl className="grid grid-cols-1 gap-x-4 gap-y-1 @lg:grid-cols-3">
          <TripFact label={componentLabel} value={identity.displayName} detail={identity.mpn} />
          <TripFact
            label={providerLabel}
            value={(ownsCapture && capture.active.vendor) || noProvider}
            detail={ownsCapture ? (capture.active.url ?? "") : ""}
          />
          <TripFact label={browserLabel} value={browserState.title} detail={browserState.detail} />
        </dl>
        <div className="mt-2.5 flex flex-wrap items-center gap-2">
          <Button
            type="button"
            data-dev-id="component-browser.provider-show"
            small
            disabled={!ownsCapture || !capture.active.workflowItemId}
            onClick={() => void showProvider()}
          >
            <Text id="component-browser.provider-show-label">Show Provider Page</Text>
          </Button>
          <Button
            type="button"
            data-dev-id="component-browser.provider-return"
            small
            disabled={!tripBusy}
            onClick={returnToStockroom}
          >
            <Text id="component-browser.provider-return-label">Return To Stockroom</Text>
          </Button>
          <Button
            type="button"
            data-dev-id="component-browser.provider-import"
            small
            disabled={importing}
            onClick={() => void importFiles()}
          >
            <Text id="component-browser.provider-import-label">Import Downloaded Files</Text>
          </Button>
        </div>
      </Band>

      <Band
        devId="component-browser.provider-progress"
        title="Download Progress"
        copyId="component-browser.provider-band-progress"
        trailing={
          needs.length > 0 ? (
            <span className="tnum font-mono text-2xs text-t2">
              <Text
                id="component-browser.provider-progress-count"
                values={{ received: receivedCount, total: needs.length }}
              >
                {"{received}/{total}"}
              </Text>
            </span>
          ) : null
        }
      >
        {needs.length === 0 ? (
          <p className="text-2xs text-t3">{noNeeds}</p>
        ) : (
          <ul className="flex flex-col divide-y divide-line">
            {needs.map((need) => (
              <li key={need} className="flex items-center gap-2 py-1" data-requirement={need}>
                <span className="min-w-0 flex-1 truncate text-2xs text-t1">
                  {reqLabels[need] ?? need}
                </span>
                <Badge tone={download.received[need] ? "ok" : "neutral"} size="sm">
                  {download.received[need] ? receivedLabel : neededLabel}
                </Badge>
              </li>
            ))}
          </ul>
        )}
      </Band>

      <Band
        devId="component-browser.provider-report"
        title="Run Report"
        copyId="component-browser.provider-band-report"
      >
        {download.message ? (
          <p className="mb-2 text-2xs leading-snug text-t2" role="status">
            {download.message}
          </p>
        ) : null}
        {outcomes.length === 0 ? (
          <p className="text-2xs text-t3">{!download.message ? noReport : ""}</p>
        ) : (
          <ul className="flex flex-col divide-y divide-line">
            {outcomes.map((outcome) => (
              <li key={outcome.route_id} className="py-1.5" data-route-id={outcome.route_id}>
                <div className="flex items-center gap-2">
                  <span className="min-w-0 flex-1 truncate text-2xs font-medium text-t1">
                    {outcome.label}
                  </span>
                  <span className={"text-2xs font-semibold " + OUTCOME_TONE[outcome.status]}>
                    {outcomeLabels[outcome.status]}
                  </span>
                </div>
                {outcome.reason ? (
                  <p className="mt-0.5 text-2xs leading-snug text-t2">{outcome.reason}</p>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </Band>

      <Band
        devId="component-browser.provider-sets"
        title="Verified Sets"
        copyId="component-browser.provider-band-sets"
      >
        <p className="mb-2 text-2xs leading-snug text-t2">
          <Text id="component-browser.provider-sets-help">
            One verified set per provider. Choosing a set puts that provider's KiCad and Altium
            files in force together; Stockroom never combines files from two downloads and never
            activates one design tool alone.
          </Text>
        </p>
        <CadVariantSection partId={componentId} enabled />
      </Band>
    </div>
  );
}

function TripFact({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail?: string;
}) {
  return (
    <div className="min-w-0">
      <dt className="text-2xs text-t3">{label}</dt>
      <dd className="min-w-0 truncate text-2xs font-medium text-t1" title={value}>
        {value}
      </dd>
      {detail ? (
        <dd className="min-w-0 truncate text-2xs text-t3" title={detail}>
          {detail}
        </dd>
      ) : null}
    </div>
  );
}

/** What the provider page is doing, in the person's terms rather than the state machine's. */
function useBrowserState(
  status: ReturnType<typeof useGuidedCapture>["status"],
  owns: boolean,
): { title: string; detail: string } {
  const idle = useText("component-browser.provider-state-idle", "Not open");
  const idleDetail = useText(
    "component-browser.provider-state-idle-detail",
    "Open a provider from the table above.",
  );
  const preparing = useText("component-browser.provider-state-preparing", "Preparing");
  const preparingDetail = useText(
    "component-browser.provider-state-preparing-detail",
    "Checking saved evidence and the exact identity.",
  );
  const open = useText("component-browser.provider-state-open", "Open");
  const openDetail = useText(
    "component-browser.provider-state-open-detail",
    "Sign in if the provider asks, choose the formats you need, and download.",
  );
  const processing = useText("component-browser.provider-state-processing", "Processing");
  const processingDetail = useText(
    "component-browser.provider-state-processing-detail",
    "Stockroom is validating and attaching what you downloaded.",
  );
  const finished = useText("component-browser.provider-state-finished", "Finished");
  const finishedDetail = useText(
    "component-browser.provider-state-finished-detail",
    "The last trip reported. See the run report below.",
  );

  if (!owns && status === "idle") return { title: idle, detail: idleDetail };
  if (status === "resolving") return { title: preparing, detail: preparingDetail };
  if (status === "window-open" || status === "receiving") {
    return { title: open, detail: openDetail };
  }
  if (status === "attaching") return { title: processing, detail: processingDetail };
  if (status === "idle") return { title: idle, detail: idleDetail };
  return { title: finished, detail: finishedDetail };
}
