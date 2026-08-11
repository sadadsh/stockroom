import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useSyncExternalStore,
  type ReactNode,
} from "react";
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
        themes: undefined,
      },
    },
  };
}

function DesignStudioBridge({ children }: { children: ReactNode }) {
  const devMode = useDevMode();
  const controller = useMemo(() => createPersonalDesignController(initialDocument()), []);
  const snapshot = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
    controller.getSnapshot,
  );
  const applyingDraft = useRef<string | null>(null);

  useEffect(() => {
    controller.activate();
    void controller.hydrate();
    return () => controller.dispose();
  }, [controller]);

  const resolved = useMemo(
    () => resolveDesign(snapshot.document, snapshot.document.activeVariationId, devMode.theme),
    [snapshot.document, devMode.theme],
  );

  useEffect(() => {
    if (sameDraft(devMode.draft, resolved)) return;
    applyingDraft.current = JSON.stringify(resolved);
    devMode.replaceDraft(resolved);
  }, [devMode.replaceDraft, resolved]);

  useEffect(() => {
    const draftSignature = JSON.stringify(devMode.draft);
    if (applyingDraft.current !== null) {
      if (applyingDraft.current === draftSignature) applyingDraft.current = null;
      return;
    }
    if (sameDraft(devMode.draft, resolved)) return;
    controller.replaceDocument(withWorkingDraft(snapshot.document, devMode.draft));
  }, [controller, devMode.draft, resolved, snapshot.document]);

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
    ],
  );

  return <DesignStudioContext.Provider value={value}>{children}</DesignStudioContext.Provider>;
}

/** Installs the existing Dev Mode provider and adds machine-local document orchestration around it. */
export function DesignStudioProvider({ children }: { children: ReactNode }) {
  return (
    <DevModeProvider>
      <DesignStudioBridge>{children}</DesignStudioBridge>
    </DevModeProvider>
  );
}

export function useDesignStudio(): DesignStudioContextValue {
  const context = useContext(DesignStudioContext);
  if (!context) throw new Error("useDesignStudio must be used within a DesignStudioProvider");
  return context;
}
