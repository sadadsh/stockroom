import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ComponentDossier } from "../../api/dossierTypes";
import { useOptionalCapture } from "../../lib/capture";
import { ALTIUM_REQS, captureInFlight, KICAD_REQS } from "../../lib/captureRequirements";
import {
  recoverCaptureFiles,
  type CaptureRecoveryResult,
} from "../../lib/captureRecovery";
import { Text, useText } from "../../lib/copy";
import type { CadWorkspaceView } from "../../lib/uiSession";
import { Button } from "../primitives";
import { useScenarioUiState } from "../../design-studio/scenarioState";
import { bestCompleteProvider, orderedManageModelsProviders } from "./manageModelsModel";
import { ProviderList } from "./ProviderList";
import { ProviderBrowserFrame } from "./ProviderBrowserFrame";

export function CadWorkspaceTabs({
  view,
  onView,
}: {
  view: CadWorkspaceView;
  onView: (view: CadWorkspaceView) => void;
}) {
  const label = useText("component-browser.cad-model-tabs", "CAD Models");
  return (
    <div role="tablist" aria-label={label} className="flex items-center gap-1">
      <button
        type="button"
        role="tab"
        aria-selected={view === "models"}
        data-dev-id="component-browser.cad-tab-models"
        className={
          "ui-control-label rounded-control px-2 py-0.5 " +
          (view === "models" ? "bg-control-pressed text-t1" : "text-t2 hover:bg-control-hover")
        }
        onClick={() => onView("models")}
      >
        <Text id="component-browser.cad-tab-models">Models</Text>
      </button>
      <button
        type="button"
        role="tab"
        aria-selected={view === "manage-models"}
        data-dev-id="component-browser.cad-tab-manage-models"
        className={
          "ui-control-label rounded-control px-2 py-0.5 " +
          (view === "manage-models"
            ? "bg-control-pressed text-t1"
            : "text-t2 hover:bg-control-hover")
        }
        onClick={() => onView("manage-models")}
      >
        <Text id="component-browser.cad-tab-manage">Manage Models</Text>
      </button>
    </div>
  );
}

export function ManageModelsWorkspace({
  componentId,
  dossier,
  onView,
  onOpenProvider,
  onRecoverFiles,
  onAttached,
}: {
  componentId: string;
  dossier: ComponentDossier;
  onView: (view: CadWorkspaceView) => void;
  onOpenProvider?: (providerId: string) => void | Promise<void>;
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
  const initialProviderId = bestProvider?.row.id ?? providers[0]?.row.id ?? null;
  const [selectedProviderId, setSelectedProviderId] = useState<string | null>(initialProviderId);
  const [activityMessage, setActivityMessage] = useState<string | null>(null);
  const [recovering, setRecovering] = useState(false);
  const lastAutomaticOpen = useRef<string | null>(null);
  const ownsCapture = capture?.active.partId === componentId;

  const openProvider = useCallback(
    async (providerId: string) => {
      setActivityMessage(null);
      try {
        if (onOpenProvider) {
          await onOpenProvider(providerId);
          return;
        }
        if (!capture) return;
        await capture.start(
          componentId,
          dossier.identity.displayName,
          [...KICAD_REQS, ...ALTIUM_REQS],
          providerId,
        );
      } catch (error) {
        setActivityMessage(error instanceof Error ? error.message : "Could not open provider");
      }
    },
    [capture, componentId, dossier.identity.displayName, onOpenProvider],
  );

  useEffect(() => {
    setSelectedProviderId(initialProviderId);
    lastAutomaticOpen.current = null;
  }, [componentId, initialProviderId]);

  useEffect(() => {
    if (!bestProvider || ownsCapture || (!onOpenProvider && !capture)) return;
    const automaticOpenKey = `${componentId}:${bestProvider.row.id}`;
    if (lastAutomaticOpen.current === automaticOpenKey) return;
    lastAutomaticOpen.current = automaticOpenKey;
    void openProvider(bestProvider.row.id);
  }, [bestProvider, capture, componentId, onOpenProvider, openProvider, ownsCapture]);

  const selectedProvider =
    providers.find((provider) => provider.row.id === selectedProviderId) ?? providers[0] ?? null;
  const captureBusy = Boolean(ownsCapture && capture && captureInFlight(capture.active));
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
        error: "Models were not attached",
        "selected-file-recovery": "Choose downloaded files",
        "returned-to-stockroom": "Provider running in background",
        complete: "Models attached",
      }[scenarioProviderState] ?? scenarioProviderState
    : null;
  const captureStatus = previewStatus ?? (ownsCapture && capture
    ? {
        resolving: "Checking provider",
        "window-open": "Provider ready",
        receiving: "Downloading models",
        attaching: "Validating models",
        done: "Models attached",
        "timed-out": "Download not observed",
        unavailable: "Provider unavailable",
        error: "Models were not attached",
        idle: "Select a provider to get models",
      }[capture.active.status]
    : "Select a provider to get models");

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
            ? `${result.accepted} files added to the provider download`
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

  return (
    <section
      data-testid="manage-models-workspace"
      data-dev-id="component-browser.manage-models"
      data-component-id={componentId}
      className="flex min-h-0 flex-1 flex-col bg-surface"
    >
      <header className="flex h-[32px] flex-none items-center gap-3 border-b border-line bg-band px-3">
        <h2 className="ui-section-title">
          <Text id="component-browser.manage-models-title">CAD Models</Text>
        </h2>
        <CadWorkspaceTabs view="manage-models" onView={onView} />
      </header>
      <div className="flex min-h-0 flex-1">
        <ProviderList
          providers={providers}
          selectedId={selectedProvider?.row.id ?? null}
          disabled={captureBusy}
          onSelect={(providerId) => {
            setSelectedProviderId(providerId);
            void openProvider(providerId);
          }}
        />
        <div className="flex min-w-0 flex-1 flex-col">
          {selectedProvider ? (
            <ProviderBrowserFrame
              componentId={componentId}
              providerLabel={selectedProvider.row.label}
              url={ownsCapture ? (capture?.active.url ?? selectedProvider.row.url) : selectedProvider.row.url}
            />
          ) : (
            <div className="flex min-h-0 flex-1 items-center justify-center text-sm text-t3">
              <Text id="component-browser.manage-models-no-providers">No providers found</Text>
            </div>
          )}
          <div
            role="status"
            aria-live="polite"
            data-dev-id="component-browser.provider-status"
            data-provider-state={scenarioProviderState}
            className="flex min-h-[44px] flex-none items-center gap-2 border-t border-line bg-band px-3"
          >
            <span className="min-w-0 flex-1 truncate text-xs text-t2">
              {activityMessage ??
                captureStatus}
            </span>
            <Button
              type="button"
              small
              data-dev-id="component-browser.provider-open"
              disabled={!selectedProvider || captureBusy}
              onClick={() => selectedProvider && void openProvider(selectedProvider.row.id)}
            >
              <Text id="component-browser.manage-models-open">Open Provider</Text>
            </Button>
            <Button
              type="button"
              small
              data-dev-id="component-browser.provider-import"
              disabled={recovering}
              onClick={() => void recoverFiles()}
            >
              <Text id="component-browser.manage-models-choose-files">Choose Downloaded Files</Text>
            </Button>
          </div>
        </div>
      </div>
    </section>
  );
}
