import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ComponentDossier } from "../../api/dossierTypes";
import { api } from "../../api/client";
import type {
  CaptureAttachmentProposal,
  ManualCadReady,
  ManualProviderBrowserSession,
} from "../../api/types";
import { useOptionalCapture } from "../../lib/capture";
import {
  captureInFlight,
  captureRequirementsForEdas,
  CAPTURE_EDAS,
  type CaptureEda,
} from "../../lib/captureRequirements";
import {
  recoverCaptureFiles,
  type CaptureRecoveryResult,
} from "../../lib/captureRecovery";
import { Text, useText } from "../../lib/copy";
import type { CadWorkspaceView } from "../../lib/uiSession";
import { BackIcon, BoardIcon } from "../icons";
import { Icon } from "../Icon";
import { Button } from "../primitives";
import { useScenarioUiState } from "../../design-studio/scenarioState";
import type { ProviderBrowserIdentity } from "../../lib/hostProviderViewport";
import { bestCompleteProvider, orderedManageModelsProviders } from "./manageModelsModel";
import { ProviderList } from "./ProviderList";
import { ProviderBrowserModal } from "./ProviderBrowserModal";
import { ProviderCaptureGuide } from "./ProviderCaptureGuide";

const MANUAL_BROWSER_REQUEST_TIMEOUT_MS = 8_000;

async function withinManualBrowserDeadline<T>(promise: Promise<T>, message: string): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | null = null;
  try {
    return await Promise.race([
      promise,
      new Promise<T>((_resolve, reject) => {
        timer = setTimeout(() => reject(new Error(message)), MANUAL_BROWSER_REQUEST_TIMEOUT_MS);
      }),
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

function joinRoles(roles: string[]): string {
  if (roles.length < 2) return roles[0] ?? "";
  if (roles.length === 2) return roles.join(" and ");
  return `${roles.slice(0, -1).join(", ")}, and ${roles[roles.length - 1]}`;
}

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
  const dashboardLabel = useText(
    "component-browser.manage-models-dashboard-aria",
    "CAD acquisition overview",
  );
  const attachedFilesLabel = useText(
    "component-browser.manage-models-attached-files-aria",
    "Attached provider files",
  );
  const landedFilesLabel = useText(
    "component-browser.manage-models-landed-files-aria",
    "Landed provider files",
  );
  const inactiveEvidenceLabel = useText(
    "component-browser.manage-models-inactive-evidence-aria",
    "Inactive CAD evidence",
  );
  const ownsCapture = capture?.active.partId === componentId;
  const scenarioProviderState = useScenarioUiState().provider?.state;
  const providers = useMemo(
    () => orderedManageModelsProviders(dossier.cadSourceCoverage),
    [dossier.cadSourceCoverage],
  );
  const bestProvider = bestCompleteProvider(providers);
  const restoredProviderId = ownsCapture && capture?.active.vendor
    && providers.some((provider) => provider.row.id === capture.active.vendor)
    ? capture.active.vendor
    : scenarioProviderState
      ? bestProvider?.row.id
        ?? providers.find((provider) => provider.reachable)?.row.id
        ?? providers[0]?.row.id
        ?? null
      : null;
  const [selectedProviderId, setSelectedProviderId] = useState<string | null>(restoredProviderId);
  const [activityMessage, setActivityMessage] = useState<string | null>(null);
  const [recovering, setRecovering] = useState(false);
  const [openingProviderId, setOpeningProviderId] = useState<string | null>(null);
  const openingProviderRef = useRef<string | null>(null);
  const [queuedProviderId, setQueuedProviderId] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);
  const [hiddenRouteToken, setHiddenRouteToken] = useState<string | null>(null);
  const [manualBrowser, setManualBrowser] = useState<ManualProviderBrowserSession | null>(null);
  const manualBrowserRef = useRef<ManualProviderBrowserSession | null>(null);
  const reportedReadySessionsRef = useRef(new Set<string>());
  const [cadReady, setCadReady] = useState<ManualCadReady | null>(null);
  const [hiddenManualSessionId, setHiddenManualSessionId] = useState<string | null>(null);
  const [scenarioBrowserDismissed, setScenarioBrowserDismissed] = useState(false);
  const [selectedEdas, setSelectedEdas] = useState<CaptureEda[]>([primaryEda]);
  const [manualAttachmentProposal, setManualAttachmentProposal] =
    useState<CaptureAttachmentProposal | null>(null);
  useEffect(() => {
    manualBrowserRef.current = manualBrowser;
  }, [manualBrowser]);

  const acceptManualSnapshot = useCallback((next: ManualProviderBrowserSession) => {
    manualBrowserRef.current = next;
    setManualBrowser(next);
    if (next.proposal) setManualAttachmentProposal(next.proposal);
    if (next.cad_ready) {
      setManualAttachmentProposal(null);
      setCadReady(next.cad_ready);
      if (!reportedReadySessionsRef.current.has(next.session_id)) {
        reportedReadySessionsRef.current.add(next.session_id);
        onAttached?.();
      }
    }
  }, [onAttached]);

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
        if (!provider?.row.url) {
          setActivityMessage("This provider has no verified page for this component.");
          return;
        }
        const sessionId = crypto.randomUUID();
        const routeId = `manual:${providerId}`;
        const browserOwnerId = `${componentId}:${providerId}:${routeId}:${sessionId}`;
        const starting: ManualProviderBrowserSession = {
          session_id: sessionId,
          part_id: componentId,
          provider_id: providerId,
          url: provider.row.url,
          browser_owner_id: browserOwnerId,
          state: "starting",
          proposal: null,
          error: "",
          browser_state: null,
        };
        manualBrowserRef.current = starting;
        setManualBrowser(starting);
        setManualAttachmentProposal(null);
        setHiddenManualSessionId(null);
        setActivityMessage(`Opening ${provider.row.label}...`);
        try {
          const opened = await withinManualBrowserDeadline(
            api.startManualProviderBrowser({
              partId: componentId,
              sessionId,
              providerId,
              url: provider.row.url,
              edas: selectedEdas,
              browserOwnerId,
            }),
            "Provider opening stalled. Retry, choose another provider, or close the browser.",
          );
          if (manualBrowserRef.current?.session_id !== sessionId) return;
          acceptManualSnapshot(opened);
          setActivityMessage(opened.error || (opened.state === "ready" ? "CAD Ready" : "Provider ready"));
        } catch (error) {
          if (manualBrowserRef.current?.session_id !== sessionId) return;
          const failed = {
            ...starting,
            state: (
              error instanceof Error && error.message.includes("stalled")
                ? "stalled"
                : "failed"
            ) as "stalled" | "failed",
            error: error instanceof Error ? error.message : "Could not open provider",
          };
          acceptManualSnapshot(failed);
          setActivityMessage(failed.error);
        }
        return;
      }
      const priorManual = manualBrowserRef.current;
      if (priorManual && ["starting", "active", "stalled"].includes(priorManual.state)) {
        try {
          await api.stopManualProviderBrowser({
            partId: componentId,
            sessionId: priorManual.session_id,
          });
        } catch {
          // Starting the task-bound adapter below is authoritative; its lease acquisition still
          // fails closed if the compatibility host cannot release the prior manual session.
        }
        manualBrowserRef.current = null;
        setManualBrowser(null);
      }
      const needs = captureRequirementsForEdas(selectedEdas);
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
    [
      acceptManualSnapshot,
      capture,
      componentId,
      dossier.identity.displayName,
      onOpenProvider,
      providers,
      selectedEdas,
    ],
  );

  const selectedProvider =
    providers.find((provider) => provider.row.id === selectedProviderId) ?? null;
  useEffect(() => {
    const session = manualBrowser;
    if (!session || !["starting", "active", "stalled"].includes(session.state)) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const poll = async () => {
      try {
        const next = await withinManualBrowserDeadline(
          api.manualProviderBrowserStatus({
            partId: componentId,
            sessionId: session.session_id,
          }),
          "Provider status stalled. Retry, choose another provider, or close the browser.",
        );
        if (disposed || manualBrowserRef.current?.session_id !== session.session_id) return;
        acceptManualSnapshot(next);
        if (next.error) setActivityMessage(next.error);
        else if (next.state === "ready") setActivityMessage("CAD Ready");
        if (["starting", "active", "stalled"].includes(next.state)) {
          timer = setTimeout(() => void poll(), 250);
        }
      } catch (error) {
        if (disposed || manualBrowserRef.current?.session_id !== session.session_id) return;
        const current = manualBrowserRef.current;
        if (current) {
          const stalled: ManualProviderBrowserSession = {
            ...current,
            state: "stalled",
            error: error instanceof Error ? error.message : "Provider status is unavailable",
          };
          acceptManualSnapshot(stalled);
          setActivityMessage(stalled.error);
        }
        timer = setTimeout(() => void poll(), 1000);
      }
    };
    timer = setTimeout(() => void poll(), 250);
    return () => {
      disposed = true;
      if (timer) clearTimeout(timer);
    };
  }, [acceptManualSnapshot, componentId, manualBrowser?.session_id, manualBrowser?.state]);
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
  const activeScenarioBrowserStates = new Set([
    "loading",
    "ready",
    "sign-in",
    "waiting-for-person",
    "format-selection",
    "download-armed",
    "one-file",
    "multiple-files",
    "partial-retained",
  ]);
  const scenarioBrowserVisible = Boolean(
    scenarioProviderState
      && !scenarioBrowserDismissed
      && activeScenarioBrowserStates.has(scenarioProviderState),
  );
  const activeManualBrowser = Boolean(
    manualBrowser
      && manualBrowser.provider_id === selectedProvider?.row.id
      && ["starting", "active", "stalled"].includes(manualBrowser.state),
  );
  const manualSurfaceReady = Boolean(
    activeManualBrowser
      && (
        manualBrowser?.state === "active"
        || (manualBrowser?.state === "stalled" && manualBrowser.browser_state !== null)
      ),
  );
  const browserOpen = Boolean(
    selectedProviderKey
      && (
        (activeManualBrowser && hiddenManualSessionId !== manualBrowser?.session_id)
        || scenarioBrowserVisible
        || (activeNativeRoute && hiddenRouteToken !== capture?.active.routeToken)
      ),
  );
  const browserPreparing = Boolean(
    selectedProviderKey
      && !activeNativeRoute
      && (
        (openingProviderId === selectedProvider?.row.id && selectedProvider?.row.captureAvailable)
        || (activeManualBrowser && manualBrowser?.state === "starting")
      ),
  );
  const browserIdentity = useMemo<ProviderBrowserIdentity | null>(() => {
    if (!selectedProvider) return null;
    if (activeManualBrowser && manualBrowser) {
      return {
        componentId: manualBrowser.browser_owner_id,
        providerId: manualBrowser.provider_id,
        routeId: `manual:${manualBrowser.provider_id}`,
        sessionId: manualBrowser.session_id,
      };
    }
    if (activeNativeRoute && capture?.active.routeToken) {
      return {
        componentId,
        providerId: capture.active.vendor ?? selectedProvider.row.id,
        routeId: capture.active.authorRoute ?? capture.active.vendor ?? selectedProvider.row.id,
        sessionId: capture.active.routeToken,
      };
    }
    return {
      componentId,
      providerId: selectedProvider.row.id,
      routeId: scenarioBrowserVisible ? "scenario" : "opening",
      sessionId: scenarioBrowserVisible
        ? `scenario:${scenarioProviderState}`
        : `opening:${selectedProvider.row.id}`,
    };
  }, [
    activeManualBrowser,
    activeNativeRoute,
    capture?.active.authorRoute,
    capture?.active.routeToken,
    capture?.active.vendor,
    componentId,
    manualBrowser,
    scenarioBrowserVisible,
    scenarioProviderState,
    selectedProvider,
  ]);
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
    setScenarioBrowserDismissed(true);
    if (activeManualBrowser && manualBrowser) {
      setHiddenManualSessionId(manualBrowser.session_id);
    }
    if (activeNativeRoute && capture?.active.routeToken) {
      setHiddenRouteToken(capture.active.routeToken);
    }
    setActivityMessage("Provider hidden. Stockroom keeps listening for this task's downloads.");
  }

  async function showActiveProvider() {
    if (activeManualBrowser && manualBrowser) {
      setHiddenManualSessionId(null);
      setActivityMessage("Provider ready");
      return;
    }
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

  function retryManualProvider() {
    if (!selectedProvider) return;
    setHiddenManualSessionId(null);
    void openProvider(selectedProvider.row.id);
  }

  function chooseAnotherProvider() {
    if (activeManualBrowser) hideActiveProvider();
    else {
      setManualBrowser(null);
      manualBrowserRef.current = null;
    }
    setActivityMessage("Choose another provider above.");
  }

  async function applyAttachments() {
    const captureProposal = ownsCapture ? capture?.active.attachmentProposal ?? null : null;
    const proposal = captureProposal ?? manualAttachmentProposal;
    if (!proposal) return;
    setApplying(true);
    setActivityMessage("Applying the confirmed CAD attachments...");
    try {
      if (captureProposal && capture) {
        await capture.applyAttachments();
      } else {
        const result = await api.applyPartFiles({
          partId: componentId,
          proposalToken: proposal.proposal_token,
        });
        setManualAttachmentProposal(null);
        manualBrowserRef.current = null;
        setManualBrowser(null);
        setHiddenManualSessionId(null);
        setActivityMessage(
          result.attached.length > 0
            ? `${result.attached.length} CAD ${result.attached.length === 1 ? "role" : "roles"} attached`
            : "No CAD roles were attached",
        );
        onAttached?.();
      }
    } catch (error) {
      setActivityMessage(error instanceof Error ? error.message : "Could not apply attachments");
    } finally {
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
          ? await recoverCaptureFiles(componentId, capture.active, undefined, selectedEdas)
          : { selected: 0, accepted: 0, outcome: "canceled" as const };
      if (result.selected === 0) return;
      if (result.outcome === "proposed" && result.proposal) {
        setManualAttachmentProposal(result.proposal);
        setActivityMessage(
          result.accepted > 0
            ? `Review ${result.accepted} proposed CAD ${result.accepted === 1 ? "attachment" : "attachments"}`
            : "No matching CAD files were found",
        );
        return;
      }
      setActivityMessage(
        result.accepted > 0
          ? `${result.accepted} CAD ${result.accepted === 1 ? "file" : "files"} queued for this Provider Visit`
          : "No matching CAD files were found",
      );
    } catch (error) {
      setActivityMessage(error instanceof Error ? error.message : "Could not import selected files");
    } finally {
      setRecovering(false);
    }
  }

  const attachmentProposal = (ownsCapture ? capture?.active.attachmentProposal ?? null : null)
    ?? manualAttachmentProposal;
  const handoffRoutes = ownsCapture ? capture?.active.handoff?.routes ?? [] : [];
  const activeGuidance = handoffRoutes.find((route) =>
    capture?.active.authorRoute ? route.route.endsWith(`:${capture.active.authorRoute}`) : false,
  ) ?? handoffRoutes[0] ?? null;
  const guideMessage = activityMessage
    ?? previewStatus
    ?? (anotherCaptureBusy
      ? `Finish the active Provider Visit for ${capture?.active.partName || "the other component"} first.`
      : selectedProvider && !selectedProvider.row.captureAvailable
        ? "Complete exact packages attach automatically. Partial downloads wait for review."
        : null);
  const showActionBar = Boolean(
    (selectedProvider && !selectedProvider.row.captureAvailable && selectedProvider.row.url)
      || ((activeNativeRoute || activeManualBrowser) && !browserOpen)
      || attachmentProposal
      || cadReady
      || manualBrowser?.state === "failed"
      || !captureBusy,
  );
  const showIdleDashboard = Boolean(
    providers.length > 0
      && !selectedProvider
      && !cadReady
      && !attachmentProposal
      && !manualBrowser
      && !anyCaptureBusy
      && !scenarioProviderState
      && openingProviderId === null,
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
        <fieldset
          className="ml-auto flex items-center gap-3 text-xs text-t2"
          data-dev-id="component-browser.eda-selection"
        >
          <legend className="sr-only">
            <Text id="component-browser.manage-models-requested-eda-files">Requested EDA files</Text>
          </legend>
          {CAPTURE_EDAS.map((eda) => {
            const checked = selectedEdas.includes(eda.key);
            return (
              <label key={eda.key} className="flex items-center gap-1.5">
                <input
                  type="checkbox"
                  checked={checked}
                  disabled={
                    anyCaptureBusy
                    || activeManualBrowser
                    || openingProviderId !== null
                    || (checked && selectedEdas.length === 1)
                  }
                  onChange={() => {
                    setSelectedEdas((current) => checked
                      ? current.filter((item) => item !== eda.key)
                      : [...current, eda.key]);
                  }}
                />
                {eda.key === "altium" ? (
                  <Text id="component-browser.manage-models-eda-altium-designer">Altium Designer</Text>
                ) : eda.label}
              </label>
            );
          })}
          <span className="text-t3">
            <Text id="component-browser.manage-models-shared-3d-note">+ shared 3D</Text>
          </span>
        </fieldset>
      </header>

      <ProviderList
        providers={providers}
        selectedId={selectedProvider?.row.id ?? null}
        disabled={anotherCaptureBusy || openingProviderId !== null}
        onSelect={(providerId) => {
          setSelectedProviderId(providerId);
          setScenarioBrowserDismissed(false);
          const provider = providers.find((candidate) => candidate.row.id === providerId);
          if (captureBusy && capture) {
            if (providerId === capture.active.vendor) {
              if (hiddenRouteToken === capture.active.routeToken) void showActiveProvider();
              return;
            }
            setQueuedProviderId(providerId);
            setOpeningProviderId(providerId);
            setActivityMessage(`Switching to ${provider?.row.label ?? "provider"}...`);
            const endCurrentRoute = capture.skipProvider();
            void endCurrentRoute.catch((error: unknown) => {
              setQueuedProviderId(null);
              setOpeningProviderId(null);
              setActivityMessage(error instanceof Error ? error.message : "Could not switch provider");
            });
            return;
          }
          if (!provider?.row.captureAvailable) {
            if (provider?.row.url) {
              setManualBrowser(null);
              setHiddenManualSessionId(null);
              void openProvider(providerId);
            } else {
              setActivityMessage("This provider has no verified page for this component.");
            }
            return;
          }
          setManualBrowser(null);
          setHiddenManualSessionId(null);
          setActivityMessage(null);
          void openProvider(providerId);
        }}
      />

      {selectedProvider || anotherCaptureBusy ? (
        <ProviderCaptureGuide
          providerLabel={selectedProvider?.row.label ?? ""}
          preparing={browserPreparing}
          ready={Boolean(
            activeNativeRoute
              || scenarioBrowserVisible
              || manualSurfaceReady
          )}
          requiredFiles={activeGuidance?.required_files ?? []}
          progress={ownsCapture
            ? capture?.active.downloadProgress
            : manualBrowser?.download_progress ?? null}
          navigationError={ownsCapture
            ? capture?.active.browserState?.navigation_error
            : manualBrowser?.browser_state?.navigation_error ?? ""}
          attachmentCount={attachmentProposal?.attachments.length ?? 0}
          message={guideMessage}
        />
      ) : null}

      {showIdleDashboard ? (
        <div className="flex min-h-0 flex-1 flex-col bg-surface">
          <section
            aria-label={dashboardLabel}
            data-dev-id="component-browser.provider-dashboard"
            className="grid flex-none gap-x-8 gap-y-3 border-b border-line px-4 py-3 sm:grid-cols-2"
          >
            <div>
              <h3 className="ui-eyebrow">
                <Text id="component-browser.manage-models-requested-files">Requested Files</Text>
              </h3>
              <ul className="mt-1.5 space-y-1 text-xs text-t2">
                {selectedEdas.map((eda) => (
                  <li key={eda}>
                    {eda === "altium" ? (
                      <Text id="component-browser.manage-models-dashboard-altium-designer">Altium Designer</Text>
                    ) : (
                      <Text id="component-browser.manage-models-kicad">KiCad</Text>
                    )}{" "}
                    <Text id="component-browser.manage-models-symbol-footprint">Symbol + Footprint</Text>
                  </li>
                ))}
                <li><Text id="component-browser.manage-models-shared-3d">Shared 3D Model</Text></li>
              </ul>
            </div>
            <div>
              <h3 className="ui-eyebrow">
                <Text id="component-browser.manage-models-download-staging">Download And Staging</Text>
              </h3>
              <p className="mt-1.5 text-xs font-semibold text-t1">
                <Text id="component-browser.manage-models-no-files-staged">No Files Staged</Text>
              </p>
              <p className="mt-1 text-xs text-t3">
                <Text id="component-browser.manage-models-staging-help">Provider downloads and imported files are checked against this exact part.</Text>
              </p>
            </div>
          </section>
          <div className="flex min-h-0 flex-1 items-center justify-center px-6 py-8">
            <p className="max-w-lg text-center text-sm leading-6 text-t3">
              <Text id="component-browser.manage-models-next-step">
                Choose a provider above to download CAD, or import files on this PC.
              </Text>
            </p>
          </div>
        </div>
      ) : (
      <div className="flex min-h-0 min-w-0 flex-1 flex-col bg-technical">
        {cadReady && !attachmentProposal ? (
          <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 px-6 py-5">
            <div role="status" className="w-full max-w-2xl rounded-panel border border-ok bg-ok/10 p-5 shadow-panel">
              <p className="ui-eyebrow mb-1 text-ok-text">
                <Text id="component-browser.manage-models-provider-download">Provider Download</Text>
              </p>
              <h3 className="text-base font-semibold text-t1">
                <Text id="component-browser.manage-models-cad-ready">CAD Ready</Text>
              </h3>
              <p className="mt-1 text-xs text-t2">
                The validated {cadReady.edas.join(" and ")} package is attached to this exact part.
                {cadReady.part_complete ? " This part is complete." : " Other EDA providers are optional."}
              </p>
              <ul aria-label={attachedFilesLabel} className="mt-3 space-y-1 text-xs text-t2">
                {cadReady.landed_files.map((fileName) => (
                  <li key={fileName} className="truncate font-mono">{fileName}</li>
                ))}
              </ul>
              {cadReady.warning ? (
                <p className="mt-3 text-xs font-semibold text-warn-text">{cadReady.warning}</p>
              ) : null}
            </div>
          </div>
        ) : attachmentProposal ? (
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
              {attachmentProposal.landed_files?.length ? (
                <ul aria-label={landedFilesLabel} className="mt-3 space-y-1 text-xs text-t2">
                  {attachmentProposal.landed_files.map((fileName) => (
                    <li key={fileName} className="truncate font-mono">{fileName}</li>
                  ))}
                </ul>
              ) : null}
              <dl className="mt-3 divide-y divide-line border-y border-line">
                {attachmentProposal.attachments.map((item) => (
                  <div key={`${item.role}:${item.file_name}`} className="grid grid-cols-[7rem_1fr_1fr] gap-3 py-2 text-xs">
                    <dt className="font-semibold text-t1">{item.role}</dt>
                    <dd className="truncate font-mono text-t2">{item.file_name}</dd>
                    <dd className="text-t2">{item.target}</dd>
                  </div>
                ))}
              </dl>
              {attachmentProposal.remaining_roles?.length ? (
                <p className="mt-3 text-xs font-semibold text-warn-text">
                  Still needed: {joinRoles(attachmentProposal.remaining_roles)}
                </p>
              ) : null}
              {attachmentProposal.inactive_evidence.length > 0 ? (
                <div className="mt-3 text-xs text-t3">
                  <p>
                    <Text id="component-browser.manage-models-proposal-inactive">
                      Other-tool files retained as inactive evidence:
                    </Text>
                  </p>
                  <ul aria-label={inactiveEvidenceLabel} className="mt-1 space-y-1">
                    {attachmentProposal.inactive_evidence.map((item) => (
                      <li key={`${item.tool}:${item.file_name}`} className="flex gap-2">
                        <span className="w-14 flex-none font-semibold uppercase">{item.tool}</span>
                        <span className="truncate font-mono">{item.file_name}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          </div>
        ) : selectedProvider ? (
          <div className="flex min-h-0 flex-1 items-center justify-center" aria-hidden="true">
            <BoardIcon className="h-9 w-9 text-t4" />
          </div>
        ) : (
          <div className="flex min-h-0 flex-1 items-center justify-center text-sm text-t3">
            <Text id="component-browser.manage-models-no-providers">No providers found</Text>
          </div>
        )}
      </div>
      )}

      {showActionBar ? (
      <footer
        data-dev-id="component-browser.provider-status"
        data-provider-state={scenarioProviderState}
        className="flex min-h-[40px] flex-none items-center justify-end gap-2 border-t border-line bg-band px-3"
      >
        {(activeNativeRoute || activeManualBrowser) && !browserOpen ? (
          <Button
            type="button"
            small
            icon={<Icon id="action.show-provider" className="h-3.5 w-3.5" />}
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
            disabled={applying || attachmentProposal.attachments.length === 0}
            onClick={() => void applyAttachments()}
          >
            <Text id="component-browser.manage-models-apply-attachments">Apply Attachments</Text>
          </Button>
        ) : null}
        {manualBrowser?.state === "failed" ? (
          <>
            <Button type="button" small onClick={retryManualProvider}>
              <Text id="component-browser.manage-models-retry">Retry</Text>
            </Button>
            <Button type="button" small onClick={chooseAnotherProvider}>
              <Text id="component-browser.manage-models-choose-another">Choose Another Provider</Text>
            </Button>
          </>
        ) : null}
        {!captureBusy && !attachmentProposal ? (
          <Button
            type="button"
            small
            icon={<Icon id="action.import-files" className="h-3.5 w-3.5" />}
            data-dev-id="component-browser.provider-import"
            disabled={recovering || anotherCaptureBusy}
            onClick={() => void recoverFiles()}
          >
            <Text id="component-browser.manage-models-choose-files">Import Existing CAD Files</Text>
          </Button>
        ) : null}
      </footer>
      ) : null}
      {selectedProvider && browserIdentity && (browserOpen || browserPreparing) ? (
        <ProviderBrowserModal
          identity={browserIdentity}
          providerLabel={selectedProvider.row.label}
          url={activeNativeRoute
            ? capture?.active.browserState?.url ?? capture!.active.url!
            : manualBrowser?.browser_state?.url ?? manualBrowser?.url ?? selectedProvider.row.url}
          ready={Boolean(
            activeNativeRoute
              || scenarioBrowserVisible
              || manualSurfaceReady
          )}
          canGoBack={activeNativeRoute
            ? capture?.active.browserState?.can_go_back
            : manualBrowser?.browser_state?.can_go_back}
          canGoForward={activeNativeRoute
            ? capture?.active.browserState?.can_go_forward
            : manualBrowser?.browser_state?.can_go_forward}
          loading={browserPreparing || (activeNativeRoute
            ? capture?.active.browserState?.loading
            : manualBrowser?.browser_state?.loading)}
          navigationError={activeNativeRoute
            ? capture?.active.browserState?.navigation_error
            : manualBrowser?.browser_state?.navigation_error || manualBrowser?.error}
          stalled={manualBrowser?.state === "stalled"}
          onRetry={retryManualProvider}
          onChooseAnother={chooseAnotherProvider}
          onClose={hideActiveProvider}
        />
      ) : null}
    </section>
  );
}
