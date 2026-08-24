import { QueryClient, QueryClientProvider, QueryObserver } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useEffect, useState } from "react";
import { ApiError, api } from "../api/client";
import { OnboardingGate } from "../components/OnboardingGate";
import { Text } from "../lib/copy";
import { useDevMode } from "../lib/devMode";
import {
  emptyDevModeDraft,
  resetDraftElementProperty,
  resetDraftTargets,
  type DevModeDraft,
} from "../lib/devModeDraft";
import { ThemeProvider } from "../lib/theme";
import { ToastProvider } from "../lib/toast";
import type { OnboardingStatus } from "../api/types";
import type { DesignDocument } from "./document";
import { DesignStudioProvider, useDesignStudio } from "./DesignStudioProvider";
import { registerScenarios, type ScenarioRegistry } from "./scenarioRegistry";
import type { DesignScenario } from "./scenario";
import { runtimeDesignId } from "../lib/designIdentity";
import { guidedSetupAt } from "./fixtures/onboardingFixtures";

vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      designStudioGet: vi.fn(),
      designStudioPut: vi.fn(),
      designStudioPutForPageExit: vi.fn(),
      designStudioDelete: vi.fn(),
      designStudioAppliedGet: vi.fn(),
      designStudioApplyLocal: vi.fn(),
      designStudioResetLocal: vi.fn(),
      devStatus: vi.fn(),
      devPromote: vi.fn(),
      devSave: vi.fn(),
      devPublish: vi.fn(),
    },
  };
});

const mockApi = vi.mocked(api);

function fixtureDocument(): DesignDocument {
  return {
    schemaVersion: 2,
    base: {
      tokens: { root: {}, light: {} },
      copy: {},
      icons: {},
      elements: {},
      behaviors: {},
      layout: null,
    },
    variations: {},
    activeVariationId: "",
    globalTargets: {},
    orphanedEdits: {},
    cadPresentation: {},
  };
}

function personalDocument(): DesignDocument {
  const document = fixtureDocument();
  document.base.copy["rail.components"] = "My Components";
  return document;
}

const ONBOARDING_STATUS: OnboardingStatus = {
  primary_eda: "kicad",
  primary_eda_pending: null,
  primary_eda_confirmation_required: false,
  recommended_primary_eda: "kicad",
  primary_eda_requirements: ["symbol", "footprint", "model"],
  retained_optional_eda: ["altium"],
  eda_tools: [],
  onboarded: false,
  first_run: true,
  libraries_root: "C:\\Stockroom",
  profiles: [],
  under_git: true,
  default_dir: "C:\\Stockroom\\Components",
  libraries: [],
  guided_setup: guidedSetupAt("catalog_repository", {
    ready: false,
    repository_ready: false,
    repository: null,
  }),
};

const DUPLICATE_ONBOARDING_SCENARIO: DesignScenario = {
  id: "global.onboarding.open",
  title: "Duplicate onboarding",
  area: "global",
  group: "Test",
  route: "components",
  fixtures: [{
    method: "GET",
    path: "/api/onboarding",
    params: {},
    body: undefined,
    response: ONBOARDING_STATUS,
  }],
  initialUi: { onboarding: { mode: "open" } },
  expectedTargets: ["onboarding.gate"],
};

function themedVariationDocument(): DesignDocument {
  const document = fixtureDocument();
  document.variations.custom = {
    id: "custom",
    title: "Custom",
    patch: { copy: { "rail.components": "Variation Components" } },
    themes: {
      dark: { elements: { "shell.root": { opacity: "0.9" } } },
      light: { elements: { "shell.root": { opacity: "0.8" } } },
    },
  };
  document.activeVariationId = "custom";
  return document;
}

function historyDocument(): DesignDocument {
  const document = fixtureDocument();
  document.base.copy["target.copy"] = "Base copy";
  document.base.icons["target.icon"] = { body: '<path d="M1 1h2" />' };
  document.base.elements.target = { width: "100px" };
  document.base.elements["target::text"] = { fontSize: "14px" };
  document.base.elements["target::icon"] = { color: "#111111" };
  document.base.elements.target2 = { width: "200px" };
  document.variations.parent = {
    id: "parent",
    title: "Parent",
    patch: { elements: { target: { minWidth: "80px" } } },
  };
  document.variations.custom = {
    id: "custom",
    title: "Custom",
    extends: "parent",
    patch: {
      copy: { "target.copy": "Variation copy" },
      elements: { target: { width: "300px" }, target2: { width: "400px" } },
    },
    themes: {
      dark: { elements: { target: { color: "#abcdef" } } },
      light: { elements: { target: { color: "#fedcba" } } },
    },
  };
  document.activeVariationId = "custom";
  document.globalTargets = {
    target: { id: "target", identity: "authored" },
    target2: { id: "target2", identity: "authored" },
  };
  return document;
}

interface StudioCommands {
  open: () => void;
  close: () => Promise<boolean>;
  setCopy: (id: string, text: string) => void;
  setVariation: (id: string) => void;
  activateScenario: (scenarioId: string) => Promise<void>;
  exitScenario: () => Promise<void>;
  replaceDraft: (draft: DevModeDraft) => void;
  replaceResolvedDraftAtomically: (draft: DevModeDraft) => void;
  replaceDocumentAtomically: (document: DesignDocument) => void;
  undo: () => void;
  promotePersonalDesign: (message: string) => Promise<unknown>;
  applyLocal: () => Promise<unknown>;
  resetAppliedLocal: () => Promise<unknown>;
}

function Probe({
  expose,
  startOpen,
}: {
  expose: (commands: StudioCommands) => void;
  startOpen: boolean;
}) {
  const devMode = useDevMode();
  const studio = useDesignStudio();
  const [closeResult, setCloseResult] = useState("not-run");
  useEffect(() => {
    expose({
      open: studio.open,
      close: studio.close,
      setCopy: devMode.setCopy,
      setVariation: studio.setVariation,
      activateScenario: studio.activateScenario,
      exitScenario: studio.exitScenario,
      replaceDraft: devMode.replaceDraft,
      replaceResolvedDraftAtomically: studio.replaceResolvedDraftAtomically,
      replaceDocumentAtomically: studio.replaceDocumentAtomically,
      undo: devMode.undo,
      promotePersonalDesign: studio.promotePersonalDesign,
      applyLocal: studio.applyLocal,
      resetAppliedLocal: studio.resetAppliedLocal,
    });
  }, [
    devMode.replaceDraft,
    devMode.setCopy,
    devMode.undo,
    expose,
    studio.activateScenario,
    studio.close,
    studio.exitScenario,
    studio.open,
    studio.replaceDocumentAtomically,
    studio.replaceResolvedDraftAtomically,
    studio.setVariation,
    studio.promotePersonalDesign,
    studio.applyLocal,
    studio.resetAppliedLocal,
  ]);
  useEffect(() => {
    if (startOpen) studio.open();
  }, [startOpen, studio.open]);
  return (
    <>
      <span data-testid="resolved-copy"><Text id="rail.components">Components</Text></span>
      <button
        type="button"
        onClick={() => void studio.close().then((closed) => setCloseResult(String(closed)))}
      >
        Close Provider Studio
      </button>
      <output data-testid="close-result">{closeResult}</output>
      <span data-testid="resolved-missing"><Text id="component-browser.cad-missing">Missing</Text></span>
      <span data-testid="personal-state">{studio.personalState}</span>
      <span data-testid="studio-enabled">{String(studio.enabled)}</span>
      <span data-testid="active-variation">{studio.activeVariationId}</span>
      <span data-testid="active-scenario">{studio.activeScenario?.id ?? "real-data"}</span>
      <span data-testid="applied-matches">{String(studio.appliedMatchesDraft)}</span>
      <output data-testid="studio-document">{JSON.stringify(studio.document)}</output>
      <output data-testid="studio-draft">{JSON.stringify(devMode.draft)}</output>
      <output data-testid="resolved-cad">{JSON.stringify(studio.resolvedCadPresentation)}</output>
    </>
  );
}

function renderStudio(options: {
  scenarioRegistry?: ScenarioRegistry;
  includeOnboardingGate?: boolean;
  startOpen?: boolean;
} = {}) {
  const commands: Partial<StudioCommands> = {};
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const result = render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <ToastProvider>
          <DesignStudioProvider scenarioRegistry={options.scenarioRegistry}>
            <Probe
              expose={(next) => Object.assign(commands, next)}
              startOpen={options.startOpen ?? true}
            />
            {options.includeOnboardingGate ? <OnboardingGate status={ONBOARDING_STATUS} /> : null}
          </DesignStudioProvider>
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  );
  return {
    ...result,
    open() {
      act(() => commands.open?.());
    },
    async close() {
      let closed = false;
      await act(async () => {
        closed = await commands.close?.() ?? false;
      });
      return closed;
    },
    setCopy(id: string, text: string) {
      act(() => commands.setCopy?.(id, text));
    },
    setVariation(id: string) {
      act(() => commands.setVariation?.(id));
    },
    activateScenario(scenarioId: string) {
      return act(async () => commands.activateScenario?.(scenarioId));
    },
    startScenario(scenarioId: string) {
      return commands.activateScenario?.(scenarioId) ?? Promise.resolve();
    },
    exitScenario() {
      return act(async () => commands.exitScenario?.());
    },
    replaceDraft(draft: DevModeDraft) {
      act(() => commands.replaceDraft?.(draft));
    },
    replaceDocumentAtomically(document: DesignDocument) {
      act(() => commands.replaceDocumentAtomically?.(document));
    },
    replaceResolvedDraftAtomically(draft: DevModeDraft) {
      act(() => commands.replaceResolvedDraftAtomically?.(draft));
    },
    undo() {
      act(() => commands.undo?.());
    },
    promotePersonalDesign(message: string) {
      return act(async () => commands.promotePersonalDesign?.(message));
    },
    applyLocal() {
      return act(async () => commands.applyLocal?.());
    },
    resetAppliedLocal() {
      return act(async () => commands.resetAppliedLocal?.());
    },
    queryClient,
  };
}

describe("DesignStudioProvider", () => {
  beforeEach(() => {
    window.__STOCKROOM_UI__ = {};
    mockApi.designStudioGet.mockReset();
    mockApi.designStudioPut.mockReset();
    mockApi.designStudioPutForPageExit.mockReset();
    mockApi.designStudioDelete.mockReset();
    mockApi.designStudioAppliedGet.mockReset();
    mockApi.designStudioApplyLocal.mockReset();
    mockApi.designStudioResetLocal.mockReset();
    mockApi.designStudioAppliedGet.mockResolvedValue({ revision: null, document: null });
    mockApi.designStudioPut.mockImplementation(async ({ document }) => ({
      revision: "draft-r2",
      document,
    }));
    mockApi.devStatus.mockReset();
    mockApi.devPromote.mockReset();
    mockApi.devSave.mockReset();
    mockApi.devPublish.mockReset();
  });

  afterEach(() => {
    delete window.__STOCKROOM_UI__;
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("hydrates the personal document before applying its resolved draft", async () => {
    mockApi.designStudioGet.mockResolvedValue({ revision: "r1", document: personalDocument() });

    renderStudio();

    await waitFor(() =>
      expect(screen.getByTestId("resolved-copy")).toHaveTextContent("My Components"),
    );
    expect(screen.getByTestId("personal-state")).toHaveTextContent("ready");
    expect(mockApi.designStudioPut).not.toHaveBeenCalled();
  });

  it("keeps personal edits draft-only until Apply, then uses them after Studio closes", async () => {
    const shipped = fixtureDocument();
    const draft = personalDocument();
    mockApi.designStudioGet.mockResolvedValue({ revision: "draft-r1", document: draft });
    mockApi.designStudioAppliedGet.mockResolvedValue({ revision: null, document: null });
    mockApi.designStudioApplyLocal.mockImplementation(async ({ document }) => ({
      revision: "applied-r1",
      document,
    }));
    const studio = renderStudio({ startOpen: false });

    await waitFor(() => expect(screen.getByTestId("personal-state")).toHaveTextContent("ready"));
    expect(screen.getByTestId("resolved-copy")).toHaveTextContent("Components");

    studio.open();
    await waitFor(() => expect(screen.getByTestId("resolved-copy")).toHaveTextContent("My Components"));
    studio.setCopy("rail.components", "Applied Components");
    expect(screen.getByTestId("resolved-copy")).toHaveTextContent("Applied Components");

    await studio.applyLocal();
    expect(mockApi.designStudioApplyLocal).toHaveBeenCalledWith({
      document: expect.objectContaining({
        base: expect.objectContaining({
          copy: expect.objectContaining({ "rail.components": "Applied Components" }),
        }),
      }),
    });
    await studio.close();
    expect(screen.getByTestId("resolved-copy")).toHaveTextContent("Applied Components");
    expect(shipped.base.copy["rail.components"]).toBeUndefined();
  });

  it("commits mixed copy, icon, element, and CAD presentation edits as the normal-app design", async () => {
    mockApi.designStudioGet.mockResolvedValue({ revision: "draft-r1", document: fixtureDocument() });
    mockApi.designStudioAppliedGet.mockResolvedValue({ revision: null, document: null });
    mockApi.designStudioApplyLocal.mockImplementation(async ({ document }) => ({
      revision: "applied-mixed",
      document,
    }));
    const studio = renderStudio({ startOpen: true });
    await waitFor(() => expect(screen.getByTestId("personal-state")).toHaveTextContent("ready"));

    const mixed = fixtureDocument();
    mixed.base.copy["component-browser.cad-missing"] = "";
    mixed.base.icons["art.symbol"] = { strokeWidth: 1.25, alignment: "middle" };
    mixed.base.elements[runtimeDesignId("icon", "art.symbol")] = { width: "40px", height: "40px" };
    mixed.base.elements[runtimeDesignId("copy", "component-browser.cad-missing")] = {
      visibility: "hidden",
    };
    mixed.cadPresentation["cad.symbol"] = { symbol: { stroke: "#d8dde5", names: false } };
    studio.replaceDocumentAtomically(mixed);
    await waitFor(() => expect(screen.getByTestId("studio-document")).toHaveTextContent(runtimeDesignId("icon", "art.symbol")));
    expect(screen.getByTestId("applied-matches")).toHaveTextContent("false");

    await studio.applyLocal();
    expect(mockApi.designStudioApplyLocal).toHaveBeenCalledWith({
      document: expect.objectContaining({
        base: expect.objectContaining({
          copy: expect.objectContaining(mixed.base.copy),
          icons: expect.objectContaining(mixed.base.icons),
          elements: expect.objectContaining(mixed.base.elements),
        }),
        cadPresentation: mixed.cadPresentation,
      }),
    });
    expect(screen.getByTestId("applied-matches")).toHaveTextContent("true");
    await studio.close();

    expect(screen.getByTestId("studio-draft")).toHaveTextContent(runtimeDesignId("icon", "art.symbol"));
    expect(screen.getByTestId("studio-draft")).toHaveTextContent("component-browser.cad-missing");
    expect(screen.getByTestId("resolved-missing")).toHaveTextContent(/^$/);
    expect(screen.getByTestId("resolved-cad")).toHaveTextContent("#d8dde5");
  });

  it("loads an existing applied design outside Studio and resets only that activation", async () => {
    const applied = fixtureDocument();
    applied.base.copy["rail.components"] = "Existing Applied Components";
    mockApi.designStudioGet.mockResolvedValue({ revision: "draft-r1", document: personalDocument() });
    mockApi.designStudioAppliedGet.mockResolvedValue({ revision: "applied-r1", document: applied });
    mockApi.designStudioResetLocal.mockResolvedValue({ ok: true });
    const studio = renderStudio({ startOpen: false });

    await waitFor(() => expect(screen.getByTestId("resolved-copy")).toHaveTextContent("Existing Applied Components"));
    await studio.resetAppliedLocal();
    expect(mockApi.designStudioResetLocal).toHaveBeenCalledOnce();
    expect(screen.getByTestId("resolved-copy")).toHaveTextContent("Components");
    expect(screen.getByTestId("studio-document")).toHaveTextContent("My Components");
  });

  it("bypasses an applied design when the host captured Ctrl+Shift during launch", async () => {
    const applied = fixtureDocument();
    applied.base.copy["rail.components"] = "Hidden Applied Components";
    window.__STOCKROOM_UI__ = { design_bypass_applied: true };
    mockApi.designStudioGet.mockResolvedValue({ revision: "draft-r1", document: personalDocument() });
    mockApi.designStudioAppliedGet.mockResolvedValue({ revision: "applied-r1", document: applied });

    renderStudio({ startOpen: false });

    await waitFor(() => expect(screen.getByTestId("personal-state")).toHaveTextContent("ready"));
    expect(screen.getByTestId("resolved-copy")).toHaveTextContent("Components");
    expect(mockApi.designStudioAppliedGet).not.toHaveBeenCalled();
  });

  it.each(["success", "promotion-failure"] as const)(
    "promotes through one backend transaction and retains the personal document after %s",
    async (outcome) => {
      const personal = personalDocument();
      const calls: string[] = [];
      mockApi.designStudioGet.mockResolvedValue({ revision: "r1", document: personal });
      mockApi.devStatus.mockImplementation(async () => {
        calls.push("status");
        return {
          available: true,
          branch: "main",
          revision: "a".repeat(40),
          dirty: [],
          can_publish: false,
          publish_blocker: "Save a Dev Mode change before publishing.",
        };
      });
      mockApi.devPromote.mockImplementation(async () => {
        calls.push("promote");
        if (outcome === "promotion-failure") throw new Error("Source recovered after GitHub push refusal.");
        return {
          ok: true,
          commit: "b".repeat(40),
          branch: "main",
          message: "Promote personal design",
          checks: ["typecheck", "production build"],
          pushed: true,
          themes: ["dark", "light"],
          variations: Object.keys(personal.variations).length,
        };
      });
      const studio = renderStudio();
      await waitFor(() => expect(screen.getByTestId("personal-state")).toHaveTextContent("ready"));
      const before = screen.getByTestId("studio-document").textContent;

      const result = await studio.promotePersonalDesign("Promote personal design");

      expect(calls[calls.length - 1]).toBe("promote");
      expect(calls.slice(0, -1).every((call) => call === "status")).toBe(true);
      expect(result).toEqual(
        outcome === "success"
          ? expect.objectContaining({ state: "success", commit: "b".repeat(40) })
          : { state: "failure", message: "Source recovered after GitHub push refusal." },
      );
      expect(screen.getByTestId("studio-document").textContent).toBe(before);
      expect(screen.getByTestId("resolved-copy")).toHaveTextContent("My Components");
      expect(mockApi.designStudioDelete).not.toHaveBeenCalled();
    },
  );

  it("debounces edits and saves the complete document with the current revision", async () => {
    vi.useFakeTimers();
    mockApi.designStudioGet.mockResolvedValue({ revision: "r1", document: fixtureDocument() });
    mockApi.designStudioPut.mockImplementation(async ({ document }) => ({
      revision: "r2",
      document,
    }));
    const studio = renderStudio();
    await act(async () => Promise.resolve());

    studio.setCopy("rail.about", "Information");
    await vi.advanceTimersByTimeAsync(400);

    expect(mockApi.designStudioPut).toHaveBeenCalledWith({
      document: expect.objectContaining({
        schemaVersion: 2,
        base: expect.objectContaining({
          copy: expect.objectContaining({ "rail.about": "Information" }),
        }),
      }),
      expected_revision: "r1",
    });
  });

  it("flushes an accepted edit before an immediate close and restores it after restart", async () => {
    vi.useFakeTimers();
    let stored = fixtureDocument();
    let revision = "r1";
    mockApi.designStudioGet.mockImplementation(async () => ({ revision, document: stored }));
    mockApi.designStudioPut.mockImplementation(async ({ document, expected_revision }) => {
      expect(expected_revision).toBe(revision);
      stored = document;
      revision = "r2";
      return { revision, document: stored };
    });
    const first = renderStudio();
    await act(async () => Promise.resolve());
    first.open();
    await act(async () => Promise.resolve());
    expect(screen.getByTestId("studio-enabled")).toHaveTextContent("true");

    first.setCopy("rail.about", "Restart Safe");
    expect(await first.close()).toBe(true);
    expect(mockApi.designStudioPut).toHaveBeenCalledOnce();
    expect(stored.base.copy["rail.about"]).toBe("Restart Safe");
    first.unmount();

    const second = renderStudio();
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByTestId("studio-document")).toHaveTextContent("Restart Safe");
    second.unmount();
  });

  it.each([
    ["transport error", new ApiError(503, "unavailable"), "error"],
    ["revision conflict", new ApiError(409, "revision conflict"), "conflict"],
  ])("blocks immediate close on %s and keeps the unsaved draft visible", async (_name, failure, state) => {
    mockApi.designStudioGet.mockResolvedValue({ revision: "r1", document: fixtureDocument() });
    mockApi.designStudioPut.mockRejectedValue(failure);
    const studio = renderStudio();
    await waitFor(() => expect(screen.getByTestId("personal-state")).toHaveTextContent("ready"));
    await waitFor(() => expect(screen.getByTestId("studio-enabled")).toHaveTextContent("true"));

    studio.setCopy("rail.about", "Unsaved Local Edit");
    await userEvent.setup().click(screen.getByRole("button", { name: "Close Provider Studio" }));

    expect(screen.getByTestId("close-result")).toHaveTextContent("false");
    expect(screen.getByTestId("studio-enabled")).toHaveTextContent("true");
    expect(screen.getByTestId("personal-state")).toHaveTextContent(state);
    expect(screen.getByTestId("studio-document")).toHaveTextContent("Unsaved Local Edit");
  });

  it("starts a keepalive save when pagehide fires inside the debounce window", async () => {
    vi.useFakeTimers();
    mockApi.designStudioGet.mockResolvedValue({ revision: "r1", document: fixtureDocument() });
    const pageExitDocument = fixtureDocument();
    pageExitDocument.base.copy["rail.about"] = "Page Exit Safe";
    mockApi.designStudioPutForPageExit.mockResolvedValue({
      revision: "r2",
      document: pageExitDocument,
    });
    const studio = renderStudio();
    await act(async () => Promise.resolve());

    studio.setCopy("rail.about", "Page Exit Safe");
    window.dispatchEvent(new PageTransitionEvent("pagehide"));

    expect(mockApi.designStudioPut).not.toHaveBeenCalled();
    expect(mockApi.designStudioPutForPageExit).toHaveBeenCalledWith({
      document: expect.objectContaining({
        base: expect.objectContaining({
          copy: expect.objectContaining({ "rail.about": "Page Exit Safe" }),
        }),
      }),
      expected_revision: "r1",
      superseded_document: null,
    });
    studio.unmount();
  });

  it("keeps a pre-hydration edit instead of applying a late server draft over it", async () => {
    vi.useFakeTimers();
    let resolveHydration!: (value: { revision: string; document: DesignDocument }) => void;
    mockApi.designStudioGet.mockImplementation(
      () => new Promise((resolve) => { resolveHydration = resolve; }),
    );
    mockApi.designStudioPut.mockImplementation(async ({ document }) => ({
      revision: "r2",
      document,
    }));
    const studio = renderStudio();

    studio.setCopy("rail.components", "Local Components");
    await vi.advanceTimersByTimeAsync(400);
    expect(mockApi.designStudioPut).not.toHaveBeenCalled();

    await act(async () => {
      resolveHydration({ revision: "r1", document: personalDocument() });
      await Promise.resolve();
    });
    expect(screen.getByTestId("resolved-copy")).toHaveTextContent("Local Components");

    await vi.advanceTimersByTimeAsync(400);
    expect(mockApi.designStudioPut).toHaveBeenCalledWith({
      document: expect.objectContaining({
        variations: expect.objectContaining({
          "full-data": expect.objectContaining({
            patch: expect.objectContaining({
              copy: expect.objectContaining({ "rail.components": "Local Components" }),
            }),
          }),
        }),
      }),
      expected_revision: "r1",
    });
  });

  it("preserves both theme patches when editing an unrelated active-variation value", async () => {
    vi.useFakeTimers();
    const personal = themedVariationDocument();
    mockApi.designStudioGet.mockResolvedValue({ revision: "r1", document: personal });
    mockApi.designStudioPut.mockImplementation(async ({ document }) => ({
      revision: "r2",
      document,
    }));
    const studio = renderStudio();
    await act(async () => Promise.resolve());

    studio.setCopy("rail.about", "Information");
    await vi.advanceTimersByTimeAsync(400);

    const saved = mockApi.designStudioPut.mock.calls[0][0].document;
    expect(saved.variations.custom.themes).toEqual(personal.variations.custom.themes);
  });

  it.each(["property", "target", "screen", "variation", "theme", "full"] as const)(
    "restores document metadata and resolved values after a %s reset is undone",
    async (resetKind) => {
      const initialDocument = historyDocument();
      mockApi.designStudioGet.mockResolvedValue({ revision: "r1", document: initialDocument });
      mockApi.designStudioPut.mockImplementation(async ({ document }) => ({ revision: "r2", document }));
      const studio = renderStudio();
      await waitFor(() => expect(screen.getByTestId("personal-state")).toHaveTextContent("ready"));
      const readDocument = () => JSON.parse(screen.getByTestId("studio-document").textContent ?? "{}") as DesignDocument;
      const readDraft = () => JSON.parse(screen.getByTestId("studio-draft").textContent ?? "{}") as DevModeDraft;
      const beforeDocument = readDocument();
      const beforeDraft = readDraft();

      if (resetKind === "property") {
        studio.replaceResolvedDraftAtomically(
          resetDraftElementProperty(beforeDraft, ["target"], "width"),
        );
      } else if (resetKind === "target") {
        studio.replaceResolvedDraftAtomically(resetDraftTargets(beforeDraft, {
          targetIds: ["target"], copyIds: ["target.copy"], iconIds: ["target.icon"],
        }));
      } else if (resetKind === "screen") {
        studio.replaceResolvedDraftAtomically(resetDraftTargets(beforeDraft, {
          targetIds: ["target", "target2"], copyIds: ["target.copy"], iconIds: ["target.icon"],
        }));
      } else if (resetKind === "variation") {
        const active = beforeDocument.variations.custom!;
        studio.replaceDocumentAtomically({
          ...beforeDocument,
          variations: {
            ...beforeDocument.variations,
            custom: { ...active, patch: {}, themes: {} },
          },
        });
      } else if (resetKind === "theme") {
        const active = beforeDocument.variations.custom!;
        studio.replaceDocumentAtomically({
          ...beforeDocument,
          variations: {
            ...beforeDocument.variations,
            custom: { ...active, themes: { light: active.themes?.light ?? {} } },
          },
        });
      } else {
        studio.replaceDocumentAtomically({
          schemaVersion: 2,
          base: emptyDevModeDraft(),
          variations: {},
          activeVariationId: "",
          globalTargets: {},
          orphanedEdits: {},
          cadPresentation: {},
        });
      }

      await waitFor(() => expect(readDraft()).not.toEqual(beforeDraft));
      studio.undo();
      await waitFor(() => {
        expect(readDocument()).toEqual(beforeDocument);
        expect(readDraft()).toEqual(beforeDraft);
      });
      expect(readDocument().globalTargets).toEqual({
        target: { id: "target", identity: "authored" },
        target2: { id: "target2", identity: "authored" },
      });
      expect(readDocument().activeVariationId).toBe("custom");
      expect(readDocument().variations.custom?.extends).toBe("parent");
    },
  );

  it("falls back to the shipped draft when persisted input is invalid", async () => {
    mockApi.designStudioGet.mockResolvedValue({
      revision: "bad",
      document: { schemaVersion: 2, base: [] },
    });

    renderStudio();

    await waitFor(() => expect(screen.getByTestId("personal-state")).toHaveTextContent("invalid"));
    expect(screen.getByTestId("resolved-copy")).toHaveTextContent("Components");
    expect(mockApi.designStudioPut).not.toHaveBeenCalled();
  });

  it("restores the saved design when a fresh provider mounts", async () => {
    const initial = fixtureDocument();
    let saved = initial;
    let revision = "r1";
    mockApi.designStudioGet.mockImplementation(async () => ({ revision, document: saved }));
    mockApi.designStudioPut.mockImplementation(async ({ document }) => {
      saved = document;
      revision = "r2";
      return { revision, document: saved };
    });
    vi.useFakeTimers();
    const first = renderStudio();
    await act(async () => Promise.resolve());
    first.setCopy("rail.components", "My Components");
    await vi.advanceTimersByTimeAsync(400);
    await act(async () => Promise.resolve());
    first.unmount();

    renderStudio();
    await act(async () => Promise.resolve());

    expect(screen.getByTestId("resolved-copy")).toHaveTextContent("My Components");
  });

  it("clears and refetches product queries for preview entry and exact real-context exit", async () => {
    mockApi.designStudioGet.mockResolvedValue({ revision: "r1", document: fixtureDocument() });
    window.history.replaceState({ workspace: "real" }, "", "#route=projects");
    const studio = renderStudio();
    const queryClient = studio.queryClient;
    let source = "real-before";
    const observer = new QueryObserver(queryClient, {
      queryKey: ["parts"],
      queryFn: async () => source,
    });
    const unsubscribe = observer.subscribe(() => undefined);
    await observer.refetch();
    queryClient.setQueryData(["design-studio", "personal"], "keep-me");

    source = "fixture-components";
    await studio.activateScenario("global.onboarding.open");
    await waitFor(() => expect(queryClient.getQueryData(["parts"])).toBe("fixture-components"));
    expect(queryClient.getQueryData(["design-studio", "personal"])).toBe("keep-me");
    expect(window.location.hash).toBe("#route=components");

    source = "real-after";
    await studio.exitScenario();
    await waitFor(() => expect(queryClient.getQueryData(["parts"])).toBe("real-after"));
    expect(window.location.hash).toBe("#route=projects");
    expect(window.history.state).toEqual({ workspace: "real" });
    expect(screen.getByTestId("active-scenario")).toHaveTextContent("real-data");
    unsubscribe();
  });

  it("does not install preview state after unmount during pending query cancellation", async () => {
    mockApi.designStudioGet.mockResolvedValue({ revision: "r1", document: fixtureDocument() });
    window.history.replaceState({ workspace: "real" }, "", "#route=projects");
    const studio = renderStudio();
    let releaseCancellation!: () => void;
    const cancellation = new Promise<void>((resolve) => {
      releaseCancellation = resolve;
    });
    vi.spyOn(studio.queryClient, "cancelQueries").mockReturnValueOnce(cancellation);

    const activation = studio.startScenario("global.onboarding.open");
    await waitFor(() => expect(studio.queryClient.cancelQueries).toHaveBeenCalled());
    studio.unmount();
    releaseCancellation();
    await activation;

    expect(window.location.hash).toBe("#route=projects");
    expect(window.history.state).toEqual({ workspace: "real" });

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ parts: [{ id: "live" }], count: 1 }),
    });
    vi.stubGlobal("fetch", fetchMock);
    await expect(api.listParts({})).resolves.toEqual({
      parts: [{ id: "live" }],
      count: 1,
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("restores the existing onboarding mode after a scenario exits", async () => {
    mockApi.designStudioGet.mockResolvedValue({ revision: "r1", document: fixtureDocument() });
    const studio = renderStudio({ includeOnboardingGate: true });
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Create New" }));
    expect(screen.getByRole("button", { name: "Create New" })).toHaveAttribute("aria-pressed", "true");

    await studio.activateScenario("global.onboarding.open");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Connect Existing" })).toHaveAttribute("aria-pressed", "true"),
    );

    await studio.exitScenario();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Create New" })).toHaveAttribute("aria-pressed", "true"),
    );
  });

  it("rejects an excluded duplicate through the public activation API without transition side effects", async () => {
    mockApi.designStudioGet.mockResolvedValue({ revision: "r1", document: fixtureDocument() });
    window.history.replaceState({ workspace: "real" }, "", "#route=projects");
    const duplicateRegistry = registerScenarios([
      DUPLICATE_ONBOARDING_SCENARIO,
      { ...DUPLICATE_ONBOARDING_SCENARIO, title: "Duplicate onboarding again" },
    ]);
    const studio = renderStudio({ scenarioRegistry: duplicateRegistry });
    const cancelQueries = vi.spyOn(studio.queryClient, "cancelQueries");

    await expect(studio.startScenario("global.onboarding.open")).rejects.toThrow(
      "Unknown Design Studio scenario 'global.onboarding.open'.",
    );

    expect(window.location.hash).toBe("#route=projects");
    expect(window.history.state).toEqual({ workspace: "real" });
    expect(screen.getByTestId("active-scenario")).toHaveTextContent("real-data");
    expect(cancelQueries).not.toHaveBeenCalled();
  });
});
