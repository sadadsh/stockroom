import { QueryClient, QueryClientProvider, QueryObserver } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useEffect } from "react";
import { api } from "../api/client";
import { Text } from "../lib/copy";
import { useDevMode } from "../lib/devMode";
import { ThemeProvider } from "../lib/theme";
import type { DesignDocument } from "./document";
import { DesignStudioProvider, useDesignStudio } from "./DesignStudioProvider";
import type { DesignScenario } from "./requestAdapter";

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

interface StudioCommands {
  setCopy: (id: string, text: string) => void;
  setVariation: (id: string) => void;
  activateScenario: (scenario: DesignScenario) => Promise<void>;
  exitScenario: () => Promise<void>;
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
    });
  }, [devMode.setCopy, expose, studio.activateScenario, studio.exitScenario, studio.setVariation]);
  return (
    <>
      <span data-testid="resolved-copy"><Text id="rail.components">Components</Text></span>
      <span data-testid="personal-state">{studio.personalState}</span>
      <span data-testid="active-variation">{studio.activeVariationId}</span>
      <span data-testid="active-scenario">{studio.activeScenario?.id ?? "real-data"}</span>
    </>
  );
}

function renderStudio() {
  const commands: Partial<StudioCommands> = {};
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const result = render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <DesignStudioProvider>
          <Probe expose={(next) => Object.assign(commands, next)} />
        </DesignStudioProvider>
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
    activateScenario(scenario: DesignScenario) {
      return act(async () => commands.activateScenario?.(scenario));
    },
    exitScenario() {
      return act(async () => commands.exitScenario?.());
    },
    queryClient,
  };
}

function fixtureScenario(
  route: DesignScenario["route"] = "components",
): DesignScenario {
  return {
    id: `${route}.fixture`,
    title: `${route} fixture`,
    area: route,
    group: "Test",
    route,
    fixtures: [],
    initialUi: {},
    expectedTargets: ["shell.root"],
    coverage: [`route:${route}`],
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
    await studio.activateScenario(fixtureScenario("components"));
    await waitFor(() => expect(queryClient.getQueryData(["parts"])).toBe("fixture-components"));
    expect(queryClient.getQueryData(["design-studio", "personal"])).toBe("keep-me");
    expect(window.location.hash).toBe("#route=components");

    source = "fixture-settings";
    await studio.activateScenario(fixtureScenario("settings"));
    await waitFor(() => expect(queryClient.getQueryData(["parts"])).toBe("fixture-settings"));
    expect(window.location.hash).toBe("#route=settings");

    source = "real-after";
    await studio.exitScenario();
    await waitFor(() => expect(queryClient.getQueryData(["parts"])).toBe("real-after"));
    expect(window.location.hash).toBe("#route=projects");
    expect(window.history.state).toEqual({ workspace: "real" });
    expect(screen.getByTestId("active-scenario")).toHaveTextContent("real-data");
    unsubscribe();
  });
});
