import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { DevModeProvider, useDevMode } from "../lib/devMode";
import { committedDevModeDraft, type DevModeDraft } from "../lib/devModeDraft";
import {
  DESIGN_DOCUMENT_SCHEMA_VERSION,
  builtInVariationDocument,
  diffDesignDraft,
  parseDesignDocument,
  resolveDesign,
  type DesignDocument,
} from "./document";
import {
  createPersonalDesignController,
  type PersonalDesignState,
} from "./personalDesign";
import {
  installApiRequestAdapter,
  previewAdapter,
} from "./requestAdapter";
import type { DesignScenario } from "./scenario";
import {
  resetCadPresentationDocument,
  updateCadPresentationDocument,
  updateCadPresentationThemeDocument,
  type CadPresentationKind,
  type CadPresentationPatchByKind,
} from "./cadPresentation";
import type { CadPresentationOverride } from "./document";
import { installPreviewEffectGuard } from "./previewEffects";
import { bootstrapScenarioRegistry } from "./scenarios";
import type { ScenarioRegistry } from "./scenarioRegistry";
import { injectedPrefs } from "../lib/uiPrefs";
import { ScenarioUiProvider } from "./scenarioState";
import {
  runPersonalDesignPromotion,
  sourcePromotionStatus,
  type PromotionResult,
  type PromotionStatus,
} from "./promotion";

export interface DesignStudioContextValue {
  open: () => void;
  close: () => Promise<void>;
  enabled: boolean;
  document: DesignDocument;
  replaceDocument: (document: DesignDocument) => void;
  replaceDocumentAtomically: (document: DesignDocument) => void;
  replaceResolvedDraftAtomically: (draft: DevModeDraft) => void;
  activeVariationId: string;
  setVariation: (variationId: string) => void;
  personalState: PersonalDesignState;
  lastValidDocument: DesignDocument;
  activeScenario: DesignScenario | null;
  activeScenarioId: string | null;
  activateScenario: (scenarioId: string) => Promise<void>;
  exitScenario: () => Promise<void>;
  promotionStatus: PromotionStatus;
  promotePersonalDesign: (message: string) => Promise<PromotionResult>;
  appliedRevision: string | null;
  appliedState: "loading" | "ready" | "applying" | "error";
  appliedMatchesDraft: boolean;
  applyLocal: () => Promise<boolean>;
  resetAppliedLocal: () => Promise<boolean>;
  resolvedCadPresentation: Record<string, CadPresentationOverride>;
  setCadPresentation: <K extends CadPresentationKind>(
    targetId: string,
    kind: K,
    patch: CadPresentationPatchByKind[K],
    themeSpecific?: boolean,
  ) => void;
  resetCadPresentation: (targetId: string) => void;
}

const DesignStudioContext = createContext<DesignStudioContextValue | null>(null);

function initialDocument(): DesignDocument {
  return {
    schemaVersion: DESIGN_DOCUMENT_SCHEMA_VERSION,
    base: committedDevModeDraft(),
    variations: builtInVariationDocument(),
    activeVariationId: "full-data",
    globalTargets: {},
    orphanedEdits: {},
    cadPresentation: {},
  };
}

function sameDraft(left: DevModeDraft, right: DevModeDraft): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function cloneDraft(draft: DevModeDraft): DevModeDraft {
  return {
    tokens: {
      root: { ...draft.tokens.root },
      light: { ...draft.tokens.light },
    },
    copy: { ...draft.copy },
    icons: Object.fromEntries(
      Object.entries(draft.icons).map(([id, icon]) => [id, { ...icon }]),
    ),
    elements: Object.fromEntries(
      Object.entries(draft.elements).map(([id, props]) => [id, { ...props }]),
    ),
    behaviors: Object.fromEntries(
      Object.entries(draft.behaviors).map(([id, behavior]) => [id, { ...behavior }]),
    ),
    layout: draft.layout ? structuredClone(draft.layout) : null,
  };
}

interface RealRouteContext {
  href: string;
  historyState: unknown;
}

function isProductQuery(query: { queryKey: readonly unknown[] }): boolean {
  const root = query.queryKey[0];
  return root !== "design-studio" && root !== "dev-status";
}

function replaceBrowserLocation(href: string, historyState: unknown): void {
  if (typeof window === "undefined") return;
  window.history.replaceState(historyState, "", href);
  window.dispatchEvent(new PopStateEvent("popstate", { state: historyState }));
}

function mountScenarioRoute(route: DesignScenario["route"]): void {
  if (typeof window === "undefined") return;
  const next = new URL(window.location.href);
  next.hash = `#route=${route}`;
  replaceBrowserLocation(next.href, window.history.state);
}

/** Build a complete v2 document from the one working Dev Mode draft. */
function withWorkingDraft(document: DesignDocument, draft: DevModeDraft): DesignDocument {
  if (!document.activeVariationId || !document.variations[document.activeVariationId]) {
    return { ...document, base: cloneDraft(draft) };
  }
  const active = document.variations[document.activeVariationId];
  return {
    ...document,
    variations: {
      ...document.variations,
      [active.id]: {
        ...active,
        patch: {
          ...cloneDraft(draft),
          cadPresentation: active.patch.cadPresentation,
        },
      },
    },
  };
}

function withExactWorkingDraft(document: DesignDocument, draft: DevModeDraft, theme: "dark" | "light"): DesignDocument {
  if (!document.activeVariationId || !document.variations[document.activeVariationId]) {
    return { ...document, base: cloneDraft(draft) };
  }
  const active = document.variations[document.activeVariationId];
  const themes = { ...active.themes };
  delete themes[theme];
  const baselineDocument: DesignDocument = {
    ...document,
    variations: {
      ...document.variations,
      [active.id]: { ...active, themes },
    },
  };
  const baseline = resolveDesign(baselineDocument, active.id, theme);
  return {
    ...document,
    variations: {
      ...document.variations,
      [active.id]: {
        ...active,
        themes: {
          ...themes,
          [theme]: {
            ...diffDesignDraft(baseline, draft),
            cadPresentation: active.themes?.[theme]?.cadPresentation,
          },
        },
      },
    },
  };
}

function DesignStudioBridge({
  children,
  scenarioRegistry,
}: {
  children: ReactNode;
  scenarioRegistry: ScenarioRegistry;
}) {
  const devMode = useDevMode();
  const queryClient = useQueryClient();
  const controller = useMemo(() => createPersonalDesignController(initialDocument()), []);
  const shippedDocument = useMemo(() => initialDocument(), []);
  const snapshot = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
    controller.getSnapshot,
  );
  const applyingDraft = useRef<string | null>(null);
  const [activeScenario, setActiveScenario] = useState<DesignScenario | null>(null);
  const [scenarioUiState, setScenarioUiState] = useState<DesignScenario["initialUi"]>({});
  const [promotionStatus, setPromotionStatus] = useState<PromotionStatus>({
    state: "checking",
    message: "Checking source promotion availability.",
  });
  const [appliedDocument, setAppliedDocument] = useState<DesignDocument | null>(null);
  const [appliedRevision, setAppliedRevision] = useState<string | null>(null);
  const [appliedState, setAppliedState] = useState<"loading" | "ready" | "applying" | "error">("loading");
  const restoreAdapter = useRef<(() => void) | null>(null);
  const restoreEffectGuard = useRef<(() => void) | null>(null);
  const realRouteContext = useRef<RealRouteContext | null>(null);
  const transition = useRef<Promise<void> | undefined>(undefined);
  const mounted = useRef(false);
  const lifecycleGeneration = useRef(0);

  useEffect(() => {
    controller.activate();
    void controller.hydrate();
    return () => controller.dispose();
  }, [controller]);

  useEffect(() => {
    let current = true;
    if (injectedPrefs().design_bypass_applied) {
      setAppliedDocument(null);
      setAppliedRevision(null);
      setAppliedState("ready");
      return () => {
        current = false;
      };
    }
    void api.designStudioAppliedGet()
      .then((response) => {
        if (!current) return;
        if (response.document === null) {
          setAppliedDocument(null);
          setAppliedRevision(response.revision);
          setAppliedState("ready");
          return;
        }
        const parsed = parseDesignDocument(response.document);
        if (!parsed.ok) {
          setAppliedState("error");
          return;
        }
        setAppliedDocument(parsed.document);
        setAppliedRevision(response.revision);
        setAppliedState("ready");
      })
      .catch(() => {
        if (current) setAppliedState("error");
      });
    return () => {
      current = false;
    };
  }, []);

  useEffect(() => {
    const flushForPageExit = () => {
      controller.flushForPageExit();
    };
    window.addEventListener("pagehide", flushForPageExit);
    return () => window.removeEventListener("pagehide", flushForPageExit);
  }, [controller]);

  useEffect(
    () => devMode.registerHistoryParticipant("design-document", {
      read: () => JSON.stringify(controller.getSnapshot().document),
      restore: (raw) => controller.replaceDocument(JSON.parse(raw) as DesignDocument),
    }),
    [controller, devMode.registerHistoryParticipant],
  );

  useEffect(() => {
    mounted.current = true;
    lifecycleGeneration.current += 1;
    return () => {
      mounted.current = false;
      lifecycleGeneration.current += 1;
      restoreAdapter.current?.();
      restoreAdapter.current = null;
      restoreEffectGuard.current?.();
      restoreEffectGuard.current = null;
      const real = realRouteContext.current;
      if (real) replaceBrowserLocation(real.href, real.historyState);
      realRouteContext.current = null;
    };
  }, []);

  const activeDesignDocument = devMode.enabled
    ? snapshot.document
    : (appliedDocument ?? shippedDocument);
  const resolved = useMemo(
    () => resolveDesign(activeDesignDocument, activeDesignDocument.activeVariationId, devMode.theme),
    [activeDesignDocument, devMode.theme],
  );
  const resolvedDraft = useMemo(() => cloneDraft(resolved), [resolved]);
  const resolvedSignature = useMemo(() => JSON.stringify(resolvedDraft), [resolvedDraft]);
  const draftSignature = useMemo(() => JSON.stringify(devMode.draft), [devMode.draft]);
  const previousResolvedSignature = useRef(resolvedSignature);

  useEffect(() => {
    const documentResolutionChanged = previousResolvedSignature.current !== resolvedSignature;
    previousResolvedSignature.current = resolvedSignature;
    if (!documentResolutionChanged || draftSignature === resolvedSignature) return;
    applyingDraft.current = resolvedSignature;
    devMode.replaceDraft(resolvedDraft);
  }, [devMode.replaceDraft, draftSignature, resolvedDraft, resolvedSignature]);

  useEffect(() => {
    if (!devMode.enabled) return;
    if (applyingDraft.current !== null) {
      if (applyingDraft.current === draftSignature) applyingDraft.current = null;
      return;
    }
    if (sameDraft(devMode.draft, resolvedDraft)) return;
    controller.replaceDocument(withWorkingDraft(snapshot.document, devMode.draft));
  }, [controller, devMode.draft, devMode.enabled, draftSignature, resolvedDraft, snapshot.document]);

  const open = useCallback(() => {
    if (!devMode.enabled) devMode.toggle();
  }, [devMode.enabled, devMode.toggle]);
  const replaceDocument = useCallback(
    (document: DesignDocument) => {
      controller.replaceDocument(document);
    },
    [controller],
  );
  const replaceDocumentAtomically = useCallback(
    (document: DesignDocument) => {
      const nextDraft = resolveDesign(document, document.activeVariationId, devMode.theme);
      devMode.replaceDraftAtomically(
        cloneDraft(nextDraft),
        "design-document",
        JSON.stringify(document),
      );
    },
    [devMode.replaceDraftAtomically, devMode.theme],
  );
  const replaceResolvedDraftAtomically = useCallback(
    (draft: DevModeDraft) => {
      const document = withExactWorkingDraft(snapshot.document, draft, devMode.theme);
      devMode.replaceDraftAtomically(
        draft,
        "design-document",
        JSON.stringify(document),
      );
    },
    [devMode.replaceDraftAtomically, devMode.theme, snapshot.document],
  );
  const setCadPresentation = useCallback(
    <K extends CadPresentationKind>(
      targetId: string,
      kind: K,
      patch: CadPresentationPatchByKind[K],
      themeSpecific = false,
    ) => {
      replaceDocumentAtomically(
        themeSpecific
          ? updateCadPresentationThemeDocument(snapshot.document, targetId, kind, patch, devMode.theme)
          : updateCadPresentationDocument(snapshot.document, targetId, kind, patch),
      );
    },
    [devMode.theme, replaceDocumentAtomically, snapshot.document],
  );
  const resetCadPresentation = useCallback(
    (targetId: string) => {
      replaceDocumentAtomically(resetCadPresentationDocument(snapshot.document, targetId));
    },
    [replaceDocumentAtomically, snapshot.document],
  );
  const setVariation = useCallback(
    (variationId: string) => {
      controller.replaceDocument({ ...snapshot.document, activeVariationId: variationId });
    },
    [controller, snapshot.document],
  );

  useEffect(() => {
    const simulated = activeScenario?.initialUi.sourcePromotion?.state;
    if (activeScenario) {
      const status: PromotionStatus = simulated === "ready"
        ? { state: "ready", message: "Fixture preview simulates a ready source checkout." }
        : simulated === "success"
          ? { state: "success", message: "Fixture preview simulates a successful promotion." }
          : simulated === "failure"
            ? { state: "failure", message: "Fixture preview simulates a failed promotion." }
            : simulated === "blocked"
              ? { state: "blocked", message: "Fixture preview simulates a blocked source checkout." }
              : { state: "blocked", message: "Return to Real Data to check source promotion." };
      setPromotionStatus(status);
      return;
    }
    if (!devMode.enabled) return;
    let current = true;
    setPromotionStatus({ state: "checking", message: "Checking source promotion availability." });
    void sourcePromotionStatus().then((status) => {
      if (current) setPromotionStatus(status);
    });
    return () => {
      current = false;
    };
  }, [activeScenario, devMode.enabled]);

  const promotePersonalDesign = useCallback(
    async (message: string): Promise<PromotionResult> => {
      const activeScenarioId = activeScenario?.id ?? null;
      if (activeScenarioId !== null) {
        return {
          state: "blocked",
          message: "Return to Real Data before making this design the app default.",
        };
      }
      setPromotionStatus({ state: "running", message: "Making this design the app default." });
      const result = await runPersonalDesignPromotion({
        document: snapshot.document,
        activeScenarioId,
        theme: devMode.theme,
        message,
      });
      setPromotionStatus({ state: result.state, message: result.message });
      return result;
    },
    [activeScenario, devMode.theme, snapshot.document],
  );

  const appliedMatchesDraft = useMemo(() => {
    if (!appliedDocument) return false;
    const current = withWorkingDraft(snapshot.document, devMode.draft);
    return JSON.stringify(appliedDocument) === JSON.stringify(current);
  }, [appliedDocument, devMode.draft, snapshot.document]);

  const applyLocal = useCallback(async (): Promise<boolean> => {
    if (activeScenario) return false;
    setAppliedState("applying");
    const document = withWorkingDraft(controller.getSnapshot().document, devMode.draft);
    controller.replaceDocument(document);
    await controller.flush();
    try {
      const response = await api.designStudioApplyLocal({ document });
      const parsed = parseDesignDocument(response.document);
      if (!parsed.ok) {
        setAppliedState("error");
        return false;
      }
      setAppliedDocument(parsed.document);
      setAppliedRevision(response.revision);
      setAppliedState("ready");
      return true;
    } catch {
      setAppliedState("error");
      return false;
    }
  }, [activeScenario, controller, devMode.draft]);

  const resetAppliedLocal = useCallback(async (): Promise<boolean> => {
    setAppliedState("applying");
    try {
      await api.designStudioResetLocal();
      setAppliedDocument(null);
      setAppliedRevision(null);
      setAppliedState("ready");
      return true;
    } catch {
      setAppliedState("error");
      return false;
    }
  }, []);

  const beginTransition = useCallback(
    (operation: () => Promise<void>): Promise<void> => {
      const pending = (transition.current ?? Promise.resolve()).then(operation, operation);
      transition.current = pending.catch(() => undefined);
      return pending;
    },
    [],
  );
  const clearInactiveProductQueries = useCallback(() => {
    queryClient.removeQueries({
      predicate: (query) => isProductQuery(query) && !query.isActive(),
    });
  }, [queryClient]);
  const refreshActiveProductQueries = useCallback(
    () =>
      queryClient.resetQueries({
        predicate: isProductQuery,
        type: "active",
      }),
    [queryClient],
  );
  const activateScenarioInternal = useCallback(
    (scenario: DesignScenario) =>
      beginTransition(async () => {
        if (!mounted.current) return;
        const generation = lifecycleGeneration.current;
        await queryClient.cancelQueries({ predicate: isProductQuery });
        if (!mounted.current || lifecycleGeneration.current !== generation) return;
        clearInactiveProductQueries();
        restoreAdapter.current?.();
        restoreEffectGuard.current?.();
        if (!realRouteContext.current && typeof window !== "undefined") {
          realRouteContext.current = {
            href: window.location.href,
            historyState: window.history.state,
          };
        }
        restoreEffectGuard.current = installPreviewEffectGuard(scenario.id);
        restoreAdapter.current = installApiRequestAdapter(previewAdapter(scenario));
        setScenarioUiState(scenario.initialUi);
        setActiveScenario(scenario);
        mountScenarioRoute(scenario.route);
        // A loading scenario deliberately owns queries whose fixture never settles. The scenario
        // transition is complete once the adapter and UI state are installed; awaiting its query
        // refresh would keep the catalog locked forever and make the next scenario unreachable.
        void refreshActiveProductQueries();
      }),
    [beginTransition, clearInactiveProductQueries, queryClient, refreshActiveProductQueries],
  );
  const exitScenario = useCallback(
    () =>
      beginTransition(async () => {
        if (!mounted.current) return;
        const generation = lifecycleGeneration.current;
        await queryClient.cancelQueries({ predicate: isProductQuery });
        if (!mounted.current || lifecycleGeneration.current !== generation) return;
        clearInactiveProductQueries();
        restoreAdapter.current?.();
        restoreAdapter.current = null;
        restoreEffectGuard.current?.();
        restoreEffectGuard.current = null;
        setScenarioUiState({});
        setActiveScenario(null);
        const real = realRouteContext.current;
        realRouteContext.current = null;
        if (real) replaceBrowserLocation(real.href, real.historyState);
        await refreshActiveProductQueries();
      }),
    [beginTransition, clearInactiveProductQueries, queryClient, refreshActiveProductQueries],
  );
  const close = useCallback(async () => {
    if (activeScenario) await exitScenario();
    await controller.flush();
    if (devMode.enabled) devMode.toggle();
  }, [activeScenario, controller, devMode.enabled, devMode.toggle, exitScenario]);
  const activateScenario = useCallback(
    (scenarioId: string) => {
      if (scenarioId === "global.real-data") return exitScenario();
      const scenario = scenarioRegistry.scenarioById(scenarioId);
      if (!scenario) return Promise.reject(new Error(`Unknown Design Studio scenario '${scenarioId}'.`));
      return activateScenarioInternal(scenario);
    },
    [activateScenarioInternal, exitScenario, scenarioRegistry],
  );

  const value = useMemo<DesignStudioContextValue>(
    () => ({
      open,
      close,
      enabled: devMode.enabled,
      document: snapshot.document,
      replaceDocument,
      replaceDocumentAtomically,
      replaceResolvedDraftAtomically,
      activeVariationId: snapshot.document.activeVariationId,
      setVariation,
      personalState: snapshot.personalState,
      lastValidDocument: snapshot.lastValidDocument,
      activeScenario,
      activeScenarioId: activeScenario?.id ?? null,
      activateScenario,
      exitScenario,
      promotionStatus,
      promotePersonalDesign,
      appliedRevision,
      appliedState,
      appliedMatchesDraft,
      applyLocal,
      resetAppliedLocal,
      resolvedCadPresentation: resolved.cadPresentation,
      setCadPresentation,
      resetCadPresentation,
    }),
    [
      open,
      close,
      devMode.enabled,
      snapshot.document,
      snapshot.personalState,
      snapshot.lastValidDocument,
      replaceDocument,
      replaceDocumentAtomically,
      replaceResolvedDraftAtomically,
      setVariation,
      activeScenario,
      activateScenario,
      exitScenario,
      promotionStatus,
      promotePersonalDesign,
      appliedRevision,
      appliedState,
      appliedMatchesDraft,
      applyLocal,
      resetAppliedLocal,
      resolved.cadPresentation,
      setCadPresentation,
      resetCadPresentation,
    ],
  );

  return (
    <DesignStudioContext.Provider value={value}>
      <ScenarioUiProvider state={scenarioUiState}>{children}</ScenarioUiProvider>
    </DesignStudioContext.Provider>
  );
}

/** Installs the existing Dev Mode provider and adds machine-local document orchestration around it. */
export function DesignStudioProvider({
  children,
  scenarioRegistry = bootstrapScenarioRegistry,
}: {
  children: ReactNode;
  scenarioRegistry?: ScenarioRegistry;
}) {
  return (
    <DevModeProvider>
      <DesignStudioBridge scenarioRegistry={scenarioRegistry}>{children}</DesignStudioBridge>
    </DevModeProvider>
  );
}

export function useDesignStudio(): DesignStudioContextValue {
  const context = useContext(DesignStudioContext);
  if (!context) throw new Error("useDesignStudio must be used within a DesignStudioProvider");
  return context;
}

/** Existing isolated Dev Mode tests may mount no studio wrapper; inspector features degrade safely. */
export function useOptionalDesignStudio(): DesignStudioContextValue | null {
  return useContext(DesignStudioContext);
}
