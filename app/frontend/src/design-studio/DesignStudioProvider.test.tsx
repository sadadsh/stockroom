import { QueryClient, QueryClientProvider, QueryObserver } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useEffect } from "react";
import { api } from "../api/client";
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

vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      designStudioGet: vi.fn(),
      designStudioPut: vi.fn(),
      designStudioDelete: vi.fn(),
    },
  };
});

const mockApi = vi.mocked(api);

function fixtureDocument(): DesignDocument {
  return {
    schemaVersion: 1,
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
    targetScopes: {},
  };
}

function personalDocument(): DesignDocument {
  const document = fixtureDocument();
  document.base.copy["rail.components"] = "My Components";
  return document;
}

const ONBOARDING_STATUS: OnboardingStatus = {
  onboarded: false,
  first_run: true,
  libraries_root: "C:\\Stockroom",
  profiles: [],
  under_git: true,
  default_dir: "C:\\Stockroom\\Components",
  libraries: [],
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
  coverage: ["route:components", "state:onboarding-open"],
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
  document.targetScopes = { target: "role", target2: "screen" };
  return document;
}

interface StudioCommands {
  setCopy: (id: string, text: string) => void;
  setVariation: (id: string) => void;
  activateScenario: (scenarioId: string) => Promise<void>;
  exitScenario: () => Promise<void>;
  replaceDraft: (draft: DevModeDraft) => void;
  replaceResolvedDraftAtomically: (draft: DevModeDraft) => void;
  replaceDocumentAtomically: (document: DesignDocument) => void;
  undo: () => void;
}

function Probe({ expose }: { expose: (commands: StudioCommands) => void }) {
  const devMode = useDevMode();
  const studio = useDesignStudio();
  useEffect(() => {
    expose({
      setCopy: devMode.setCopy,
      setVariation: studio.setVariation,
      activateScenario: studio.activateScenario,
      exitScenario: studio.exitScenario,
      replaceDraft: devMode.replaceDraft,
      replaceResolvedDraftAtomically: studio.replaceResolvedDraftAtomically,
      replaceDocumentAtomically: studio.replaceDocumentAtomically,
      undo: devMode.undo,
    });
  }, [
    devMode.replaceDraft,
    devMode.setCopy,
    devMode.undo,
    expose,
    studio.activateScenario,
    studio.exitScenario,
    studio.replaceDocumentAtomically,
    studio.replaceResolvedDraftAtomically,
    studio.setVariation,
  ]);
  return (
    <>
      <span data-testid="resolved-copy"><Text id="rail.components">Components</Text></span>
      <span data-testid="personal-state">{studio.personalState}</span>
      <span data-testid="active-variation">{studio.activeVariationId}</span>
      <span data-testid="active-scenario">{studio.activeScenario?.id ?? "real-data"}</span>
      <output data-testid="studio-document">{JSON.stringify(studio.document)}</output>
      <output data-testid="studio-draft">{JSON.stringify(devMode.draft)}</output>
    </>
  );
}

function renderStudio(options: { scenarioRegistry?: ScenarioRegistry; includeOnboardingGate?: boolean } = {}) {
  const commands: Partial<StudioCommands> = {};
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const result = render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <ToastProvider>
          <DesignStudioProvider scenarioRegistry={options.scenarioRegistry}>
            <Probe expose={(next) => Object.assign(commands, next)} />
            {options.includeOnboardingGate ? <OnboardingGate status={ONBOARDING_STATUS} /> : null}
          </DesignStudioProvider>
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  );
  return {
    ...result,
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
    queryClient,
  };
}

describe("DesignStudioProvider", () => {
  beforeEach(() => {
    mockApi.designStudioGet.mockReset();
    mockApi.designStudioPut.mockReset();
    mockApi.designStudioDelete.mockReset();
  });

  afterEach(() => {
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
        schemaVersion: 1,
        base: expect.objectContaining({ copy: { "rail.about": "Information" } }),
      }),
      expected_revision: "r1",
    });
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
        base: expect.objectContaining({
          copy: expect.objectContaining({ "rail.components": "Local Components" }),
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
          schemaVersion: 1,
          base: emptyDevModeDraft(),
          variations: {},
          activeVariationId: "",
          targetScopes: {},
        });
      }

      await waitFor(() => expect(readDraft()).not.toEqual(beforeDraft));
      studio.undo();
      await waitFor(() => {
        expect(readDocument()).toEqual(beforeDocument);
        expect(readDraft()).toEqual(beforeDraft);
      });
      expect(readDocument().targetScopes).toEqual({ target: "role", target2: "screen" });
      expect(readDocument().activeVariationId).toBe("custom");
      expect(readDocument().variations.custom?.extends).toBe("parent");
    },
  );

  it("falls back to the shipped draft when persisted input is invalid", async () => {
    mockApi.designStudioGet.mockResolvedValue({
      revision: "bad",
      document: { schemaVersion: 2, base: { copy: { "rail.components": "Broken" } } },
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

    await user.click(screen.getByRole("button", { name: "Clone From Git" }));
    expect(screen.getByRole("button", { name: "Clone From Git" })).toHaveAttribute("aria-pressed", "true");

    await studio.activateScenario("global.onboarding.open");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Open Existing" })).toHaveAttribute("aria-pressed", "true"),
    );

    await studio.exitScenario();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Clone From Git" })).toHaveAttribute("aria-pressed", "true"),
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
