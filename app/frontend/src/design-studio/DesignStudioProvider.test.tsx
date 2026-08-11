import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { Text } from "../lib/copy";
import { useDevMode } from "../lib/devMode";
import { ThemeProvider } from "../lib/theme";
import type { DesignDocument } from "./document";
import { DesignStudioProvider, useDesignStudio } from "./DesignStudioProvider";

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

interface StudioCommands {
  setCopy: (id: string, text: string) => void;
  setVariation: (id: string) => void;
}

function Probe({ expose }: { expose: (commands: StudioCommands) => void }) {
  const devMode = useDevMode();
  const studio = useDesignStudio();
  expose({ setCopy: devMode.setCopy, setVariation: studio.setVariation });
  return (
    <>
      <span data-testid="resolved-copy"><Text id="rail.components">Components</Text></span>
      <span data-testid="personal-state">{studio.personalState}</span>
      <span data-testid="active-variation">{studio.activeVariationId}</span>
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
});
