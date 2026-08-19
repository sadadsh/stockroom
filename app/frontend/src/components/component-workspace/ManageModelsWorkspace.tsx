import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ComponentDossier } from "../../api/dossierTypes";
import { useOptionalCapture } from "../../lib/capture";
import {
  captureInFlight,
  captureRequirementsForEdas,
  type CaptureEda,
} from "../../lib/captureRequirements";
import {
  recoverCaptureFiles,
  type CaptureRecoveryResult,
} from "../../lib/captureRecovery";
import { Text } from "../../lib/copy";
import type { CadWorkspaceView } from "../../lib/uiSession";
import { BackIcon, BoardIcon, DownloadIcon, ExternalIcon } from "../icons";
import { Button } from "../primitives";
import { useScenarioUiState } from "../../design-studio/scenarioState";
import { bestCompleteProvider, orderedManageModelsProviders } from "./manageModelsModel";
import { ProviderList } from "./ProviderList";
import { ProviderBrowserFrame } from "./ProviderBrowserFrame";
import { ProviderCaptureGuide } from "./ProviderCaptureGuide";

export function ManageModelsWorkspace({
  componentId,
  dossier,
  onView: _onView,
  primaryEda = "kicad",
  onBack,
  onOpenProvider,
  onRecoverFiles,
  onAttached,
}: {
  componentId: string;
  dossier: ComponentDossier;
  onView?: (view: CadWorkspaceView) => void;
  primaryEda?: CaptureEda;
  onBack?: () => void;
  onOpenProvider?: (providerId: string, needs: ReturnType<typeof captureRequirementsForEdas>) => void | Promise<void>;
  onRecoverFiles?: () => Promise<CaptureRecoveryResult>;
  onAttached?: () => void;
}) {
  const capture = useOptionalCapture();
  const scenarioProviderState = useScenarioUiState().provider?.state;
  const providers = useMemo(
    () => orderedManageModelsProviders(dossier.cadSourceCoverage),
    [dossier.cadSourceCoverage],
  );
  const bestProvider = bestCompleteProvider(providers);
  const initialProviderId = bestProvider?.row.id
    ?? providers.find((provider) => provider.reachable && provider.row.captureAvailable)?.row.id
    ?? providers[0]?.row.id
    ?? null;
  const [selectedProviderId, setSelectedProviderId] = useState<string | null>(initialProviderId);
  const [activityMessage, setActivityMessage] = useState<string | null>(null);
  const [recovering, setRecovering] = useState(false);
  const [openingProviderId, setOpeningProviderId] = useState<string | null>(null);
  const openingProviderRef = useRef<string | null>(null);
  const [queuedProviderId, setQueuedProviderId] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);
  const [hiddenRouteToken, setHiddenRouteToken] = useState<string | null>(null);
  const ownsCapture = capture?.active.partId === componentId;

  useEffect(() => {
    const activeProvider = ownsCapture ? capture?.active.vendor : null;
    if (
      !queuedProviderId
      && activeProvider
      && providers.some((provider) => provider.row.id === activeProvider)
    ) {
      setSelectedProviderId(activeProvider);
    }
  }, [capture?.active.vendor, ownsCapture, providers, queuedProviderId]);

  useEffect(() => {
    setActivityMessage(null);
  }, [
    capture?.active.status,
    capture?.active.message,
    capture?.active.downloadProgress?.bytes_received,
  ]);

  useEffect(() => {
    if (!ownsCapture || !capture?.active.routeToken) return;
    openingProviderRef.current = null;
    setOpeningProviderId(null);
    setActivityMessage((current) => current?.startsWith("Opening ") ? null : current);
  }, [capture?.active.routeToken, ownsCapture]);

  const openProvider = useCallback(
    async (providerId: string) => {
      if (openingProviderRef.current) return;
      const provider = providers.find((candidate) => candidate.row.id === providerId);
      if (!provider?.row.captureAvailable) {
        setActivityMessage("This source has no task-bound Provider Visit. Open its listing instead.");
        return;
      }
      const needs = captureRequirementsForEdas([primaryEda]);
      openingProviderRef.current = providerId;
      setOpeningProviderId(providerId);
      setActivityMessage(`Opening ${provider.row.label}...`);
      try {
        if (onOpenProvider) {
          await onOpenProvider(providerId, needs);
        } else {
          if (!capture) return;
          await capture.start(
            componentId,
            dossier.identity.displayName,
            needs,
            providerId,
          );
        }
      } catch (error) {
        setActivityMessage(error instanceof Error ? error.message : "Could not open provider");
      } finally {
        openingProviderRef.current = null;
        setOpeningProviderId(null);
      }
    },
    [capture, componentId, dossier.identity.displayName, onOpenProvider, primaryEda, providers],
  );

  const selectedProvider =
    providers.find((provider) => provider.row.id === selectedProviderId) ?? providers[0] ?? null;
  const selectedProviderKey = selectedProvider
    ? `${componentId}:${selectedProvider.row.id}`
    : null;
  const captureProviderKey = ownsCapture && capture?.active.vendor
    ? `${componentId}:${capture.active.vendor}`
    : null;
  // A click shows browser chrome immediately, like an ordinary browser tab, while the exact
  // task-bound native route is leased. Controls remain disabled until that real route exists, so
  // the prompt shell cannot navigate or accept downloads outside Stockroom's staging fence.
  const activeNativeRoute = Boolean(
    captureProviderKey
      && selectedProviderKey === captureProviderKey
      && capture?.active.status === "window-open"
      && capture.active.routeToken
      && capture.active.url,
  );
  const browserOpen = Boolean(
    selectedProviderKey
      && (scenarioProviderState || (activeNativeRoute && hiddenRouteToken !== capture?.active.routeToken)),
  );
  const browserPreparing = Boolean(
    selectedProviderKey
      && !activeNativeRoute
      && openingProviderId === selectedProvider?.row.id
      && selectedProvider?.row.captureAvailable,
  );
  const anyCaptureBusy = Boolean(capture && captureInFlight(capture.active));
  const captureBusy = Boolean(ownsCapture && anyCaptureBusy);
  const anotherCaptureBusy = Boolean(anyCaptureBusy && !ownsCapture);

  useEffect(() => {
    if (!queuedProviderId || anyCaptureBusy) return;
    const nextProviderId = queuedProviderId;
    setQueuedProviderId(null);
    void openProvider(nextProviderId);
  }, [anyCaptureBusy, openProvider, queuedProviderId]);

  const previewStatus = scenarioProviderState
    ? {
        loading: "Loading provider",
        ready: "Provider ready",
        "sign-in": "Sign in on the provider page",
        "waiting-for-person": "Complete the provider step",
        "format-selection": "Choose the provider formats",
        "download-armed": "Download capture ready",
        "one-file": "One file received",
        "multiple-files": "Multiple files received",
        "partial-retained": "Partial files retained",
        unavailable: "Provider unavailable",
        timeout: "Download not observed",
        canceled: "Download canceled",
        error: "CAD assets were not attached",
        "selected-file-recovery": "Use downloaded files",
        "returned-to-stockroom": "Provider running in background",
        complete: "CAD assets attached",
      }[scenarioProviderState] ?? scenarioProviderState
    : null;
  function hideActiveProvider() {
    if (!activeNativeRoute || !capture?.active.routeToken) return;
    setHiddenRouteToken(capture.active.routeToken);
    setActivityMessage("Provider hidden. Stockroom keeps listening for this task's downloads.");
  }

  async function showActiveProvider() {
    if (!activeNativeRoute || !capture) return;
    setActivityMessage("Showing provider...");
    try {
      await capture.showProvider();
      setHiddenRouteToken(null);
      setActivityMessage("Provider ready");
    } catch (error) {
      setActivityMessage(error instanceof Error ? error.message : "Could not show provider");
    }
  }

  async function applyAttachments() {
    if (!capture?.active.attachmentProposal) return;
    setApplying(true);
    setActivityMessage("Applying the confirmed CAD attachments...");
    try {
      await capture.applyAttachments();
    } catch (error) {
      setActivityMessage(error instanceof Error ? error.message : "Could not apply attachments");
      setApplying(false);
    }
  }

  async function recoverFiles() {
    setRecovering(true);
    setActivityMessage(null);
    try {
      const result = onRecoverFiles
        ? await onRecoverFiles()
        : capture
          ? await recoverCaptureFiles(componentId, capture.active)
          : { selected: 0, accepted: 0, outcome: "canceled" as const };
      if (result.selected === 0) return;
      setActivityMessage(
        result.accepted > 0
          ? result.outcome === "queued"
            ? `${result.accepted} CAD ${result.accepted === 1 ? "file" : "files"} queued for this Provider Visit`
            : `${result.accepted} CAD roles attached`
          : "No matching CAD files were found",
      );
      if (result.accepted > 0 && result.outcome === "attached") onAttached?.();
    } catch (error) {
      setActivityMessage(error instanceof Error ? error.message : "Could not import selected files");
    } finally {
      setRecovering(false);
    }
  }

  const edaLabel = primaryEda === "altium" ? "Altium Designer" : "KiCad";
  const attachmentProposal = ownsCapture ? capture?.active.attachmentProposal ?? null : null;
  const handoffRoutes = ownsCapture ? capture?.active.handoff?.routes ?? [] : [];
  const activeGuidance = handoffRoutes.find((route) =>
    capture?.active.authorRoute ? route.route.endsWith(`:${capture.active.authorRoute}`) : false,
  ) ?? handoffRoutes[0] ?? null;
  const guideMessage = activityMessage
    ?? previewStatus
    ?? (anotherCaptureBusy
      ? `Finish the active Provider Visit for ${capture?.active.partName || "the other component"} first.`
      : selectedProvider && !selectedProvider.row.captureAvailable
        ? "This source has no task-bound Provider Visit. Open its listing instead."
        : null);
  const showActionBar = Boolean(
    (selectedProvider && !selectedProvider.row.captureAvailable && selectedProvider.row.url)
      || (activeNativeRoute && !browserOpen)
      || attachmentProposal
      || !captureBusy,
  );

  return (
    <section
      data-testid="manage-models-workspace"
      data-dev-id="component-browser.manage-models"
      data-component-id={componentId}
      className="flex min-h-0 flex-1 flex-col bg-surface"
    >
      <header className="flex h-[38px] flex-none items-center gap-2 border-b border-line bg-band px-3">
        {onBack ? (
          <Button small icon={<BackIcon className="h-3.5 w-3.5" />} onClick={onBack}>
            <Text id="component-browser.manage-models-back-assets">Back To Assets</Text>
          </Button>
        ) : null}
        <BoardIcon className="h-4 w-4 text-t3" />
        <h2 className="ui-section-title">{dossier.identity.mpn || dossier.identity.displayName}</h2>
        <span className="ml-auto text-xs text-t3" data-dev-id="component-browser.eda-selection">
          <Text id="component-browser.manage-models-eda-prefix">Downloads follow</Text> {edaLabel} · <Text id="component-browser.manage-models-eda-settings">selected in Settings</Text>
        </span>
      </header>

      <ProviderList
        providers={providers}
        selectedId={selectedProvider?.row.id ?? null}
        disabled={anotherCaptureBusy || openingProviderId !== null}
        onSelect={(providerId) => {
          setSelectedProviderId(providerId);
          const provider = providers.find((candidate) => candidate.row.id === providerId);
          if (!provider?.row.captureAvailable) {
            setActivityMessage("This source has no task-bound Provider Visit. Open its listing instead.");
            return;
          }
          if (captureBusy && capture) {
            if (providerId === capture.active.vendor) {
              if (hiddenRouteToken === capture.active.routeToken) void showActiveProvider();
              return;
            }
            setQueuedProviderId(providerId);
            setOpeningProviderId(providerId);
            setActivityMessage(`Switching to ${provider.row.label}...`);
            const endCurrentRoute = capture.skipProvider();
            void endCurrentRoute.catch((error: unknown) => {
              setQueuedProviderId(null);
              setOpeningProviderId(null);
              setActivityMessage(error instanceof Error ? error.message : "Could not switch provider");
            });
            return;
          }
          setActivityMessage(null);
          void openProvider(providerId);
        }}
      />

      {selectedProvider ? (
        <ProviderCaptureGuide
          providerLabel={selectedProvider.row.label}
          preparing={browserPreparing}
          ready={Boolean(activeNativeRoute || scenarioProviderState)}
          requiredFiles={activeGuidance?.required_files ?? []}
          progress={ownsCapture ? capture?.active.downloadProgress : null}
          navigationError={ownsCapture ? capture?.active.browserState?.navigation_error : ""}
          attachmentCount={attachmentProposal?.attachments.length ?? 0}
          message={guideMessage}
        />
      ) : null}

      <div className="flex min-h-0 min-w-0 flex-1 flex-col bg-technical">
        {attachmentProposal ? (
          <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-4 px-6 py-5">
            <div className="w-full max-w-2xl rounded-panel border border-line bg-surface p-4 shadow-panel">
              <p className="ui-eyebrow mb-1">
                <Text id="component-browser.manage-models-proposal-eyebrow">Attachment Proposal</Text>
              </p>
              <h3 className="text-sm font-semibold text-t1">
                <Text id="component-browser.manage-models-proposal-title">Review attachments for</Text>{" "}
                {attachmentProposal.primary_tool === "both"
                  ? "KiCad And Altium"
                  : attachmentProposal.primary_tool === "altium"
                    ? "Altium Designer"
                    : "KiCad"}
              </h3>
              <p className="mt-1 text-xs text-t3">
                <Text id="component-browser.manage-models-proposal-help">
                  Verified files remain inactive until attachment confirmation.
                </Text>
              </p>
              <dl className="mt-3 divide-y divide-line border-y border-line">
                {attachmentProposal.attachments.map((item) => (
                  <div key={`${item.role}:${item.file_name}`} className="grid grid-cols-[7rem_1fr_1fr] gap-3 py-2 text-xs">
                    <dt className="font-semibold text-t1">{item.role}</dt>
                    <dd className="truncate font-mono text-t2">{item.file_name}</dd>
                    <dd className="text-t2">{item.target}</dd>
                  </div>
                ))}
              </dl>
              {attachmentProposal.inactive_evidence.length > 0 ? (
                <p className="mt-3 text-xs text-t3">
                  <Text id="component-browser.manage-models-proposal-inactive">
                    Other-tool files retained as inactive evidence:
                  </Text>{" "}
                  {attachmentProposal.inactive_evidence.length}
                </p>
              ) : null}
            </div>
          </div>
        ) : selectedProvider ? (
          browserOpen || browserPreparing ? (
            <ProviderBrowserFrame
              componentId={componentId}
              providerLabel={selectedProvider.row.label}
              url={activeNativeRoute
                ? capture?.active.browserState?.url ?? capture!.active.url!
                : selectedProvider.row.url}
              ready={Boolean(activeNativeRoute || scenarioProviderState)}
              canGoBack={capture?.active.browserState?.can_go_back}
              canGoForward={capture?.active.browserState?.can_go_forward}
              loading={browserPreparing || capture?.active.browserState?.loading}
              navigationError={capture?.active.browserState?.navigation_error}
              onClose={activeNativeRoute ? hideActiveProvider : undefined}
            />
          ) : (
            <div className="flex min-h-0 flex-1 items-center justify-center" aria-hidden="true">
              <BoardIcon className="h-9 w-9 text-t4" />
            </div>
          )
        ) : (
          <div className="flex min-h-0 flex-1 items-center justify-center text-sm text-t3">
            <Text id="component-browser.manage-models-no-providers">No providers found</Text>
          </div>
        )}
      </div>

      {showActionBar ? (
      <footer
        data-dev-id="component-browser.provider-status"
        data-provider-state={scenarioProviderState}
        className="flex min-h-[40px] flex-none items-center justify-end gap-2 border-t border-line bg-band px-3"
      >
        {selectedProvider && !selectedProvider.row.captureAvailable && selectedProvider.row.url ? (
          <a
            href={selectedProvider.row.url}
            target="_blank"
            rel="noreferrer"
            className="ui-control-label inline-flex items-center gap-1.5 rounded-control border border-line2 bg-control px-2 py-1 text-t2 hover:bg-control-hover hover:text-t1"
          >
            <ExternalIcon className="h-3.5 w-3.5" />
            <Text id="component-browser.manage-models-open-listing">Open Listing</Text>
          </a>
        ) : null}
        {activeNativeRoute && !browserOpen ? (
          <Button
            type="button"
            small
            icon={<ExternalIcon className="h-3.5 w-3.5" />}
            onClick={() => void showActiveProvider()}
          >
            <Text id="component-browser.manage-models-show">Show Provider</Text>
          </Button>
        ) : null}
        {attachmentProposal ? (
          <Button
            type="button"
            small
            variant="accent"
            disabled={applying}
            onClick={() => void applyAttachments()}
          >
            <Text id="component-browser.manage-models-apply-attachments">Commit Attachments</Text>
          </Button>
        ) : null}
        {!captureBusy && !attachmentProposal ? (
          <Button
            type="button"
            small
            icon={<DownloadIcon className="h-3.5 w-3.5" />}
            data-dev-id="component-browser.provider-import"
            disabled={recovering || anotherCaptureBusy}
            onClick={() => void recoverFiles()}
          >
            <Text id="component-browser.manage-models-choose-files">Import Existing CAD Files</Text>
          </Button>
        ) : null}
      </footer>
      ) : null}
    </section>
  );
}
