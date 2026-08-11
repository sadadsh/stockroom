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
import { DevModeProvider, useDevMode } from "../lib/devMode";
import { committedDevModeDraft, type DevModeDraft } from "../lib/devModeDraft";
import {
  DESIGN_DOCUMENT_SCHEMA_VERSION,
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
import { bootstrapScenarioRegistry } from "./scenarios";
import type { ScenarioRegistry } from "./scenarioRegistry";
import { ScenarioUiProvider } from "./scenarioState";

export interface DesignStudioContextValue {
  open: () => void;
  close: () => void;
  enabled: boolean;
  document: DesignDocument;
  replaceDocument: (document: DesignDocument) => void;
  activeVariationId: string;
  setVariation: (variationId: string) => void;
  personalState: PersonalDesignState;
  lastValidDocument: DesignDocument;
  activeScenario: DesignScenario | null;
  activateScenario: (scenarioId: string) => Promise<void>;
  exitScenario: () => Promise<void>;
}

const DesignStudioContext = createContext<DesignStudioContextValue | null>(null);

function initialDocument(): DesignDocument {
  return {
    schemaVersion: DESIGN_DOCUMENT_SCHEMA_VERSION,
    base: committedDevModeDraft(),
    variations: {},
    activeVariationId: "",
    targetScopes: {},
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

/** Build a complete v1 document from the one working Dev Mode draft. */
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
        patch: cloneDraft(draft),
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
  const snapshot = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
    controller.getSnapshot,
  );
  const applyingDraft = useRef<string | null>(null);
  const [activeScenario, setActiveScenario] = useState<DesignScenario | null>(null);
  const [scenarioUiState, setScenarioUiState] = useState<DesignScenario["initialUi"]>({});
  const restoreAdapter = useRef<(() => void) | null>(null);
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
    mounted.current = true;
    lifecycleGeneration.current += 1;
    return () => {
      mounted.current = false;
      lifecycleGeneration.current += 1;
      restoreAdapter.current?.();
      restoreAdapter.current = null;
      const real = realRouteContext.current;
      if (real) replaceBrowserLocation(real.href, real.historyState);
      realRouteContext.current = null;
    };
  }, []);

  const resolved = useMemo(
    () => resolveDesign(snapshot.document, snapshot.document.activeVariationId, devMode.theme),
    [snapshot.document, devMode.theme],
  );
  const resolvedSignature = useMemo(() => JSON.stringify(resolved), [resolved]);
  const draftSignature = useMemo(() => JSON.stringify(devMode.draft), [devMode.draft]);
  const previousResolvedSignature = useRef(resolvedSignature);

  useEffect(() => {
    const documentResolutionChanged = previousResolvedSignature.current !== resolvedSignature;
    previousResolvedSignature.current = resolvedSignature;
    if (!documentResolutionChanged || draftSignature === resolvedSignature) return;
    applyingDraft.current = resolvedSignature;
    devMode.replaceDraft(resolved);
  }, [devMode.replaceDraft, draftSignature, resolved, resolvedSignature]);

  useEffect(() => {
    if (applyingDraft.current !== null) {
      if (applyingDraft.current === draftSignature) applyingDraft.current = null;
      return;
    }
    if (sameDraft(devMode.draft, resolved)) return;
    controller.replaceDocument(withWorkingDraft(snapshot.document, devMode.draft));
  }, [controller, devMode.draft, draftSignature, resolved, snapshot.document]);

  const open = useCallback(() => {
    if (!devMode.enabled) devMode.toggle();
  }, [devMode.enabled, devMode.toggle]);
  const close = useCallback(() => {
    if (devMode.enabled) devMode.toggle();
  }, [devMode.enabled, devMode.toggle]);
  const replaceDocument = useCallback(
    (document: DesignDocument) => {
      controller.replaceDocument(document);
    },
    [controller],
  );
  const setVariation = useCallback(
    (variationId: string) => {
      controller.replaceDocument({ ...snapshot.document, activeVariationId: variationId });
    },
    [controller, snapshot.document],
  );

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
        if (!realRouteContext.current && typeof window !== "undefined") {
          realRouteContext.current = {
            href: window.location.href,
            historyState: window.history.state,
          };
        }
        restoreAdapter.current = installApiRequestAdapter(previewAdapter(scenario));
        setScenarioUiState(scenario.initialUi);
        setActiveScenario(scenario);
        mountScenarioRoute(scenario.route);
        await refreshActiveProductQueries();
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
        setScenarioUiState({});
        setActiveScenario(null);
        const real = realRouteContext.current;
        realRouteContext.current = null;
        if (real) replaceBrowserLocation(real.href, real.historyState);
        await refreshActiveProductQueries();
      }),
    [beginTransition, clearInactiveProductQueries, queryClient, refreshActiveProductQueries],
  );
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
      activeVariationId: snapshot.document.activeVariationId,
      setVariation,
      personalState: snapshot.personalState,
      lastValidDocument: snapshot.lastValidDocument,
      activeScenario,
      activateScenario,
      exitScenario,
    }),
    [
      open,
      close,
      devMode.enabled,
      snapshot.document,
      snapshot.personalState,
      snapshot.lastValidDocument,
      replaceDocument,
      setVariation,
      activeScenario,
      activateScenario,
      exitScenario,
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
