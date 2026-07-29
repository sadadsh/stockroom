import { createElement, type ReactNode } from "react";
import { act, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Requirement } from "../api/types";
import { useGuidedCapture } from "./useGuidedCapture";
import { mockCapture } from "../test/captureMocks";
import { CaptureProvider } from "./capture";

function wrapperWith(qc: QueryClient) {
  return ({ children }: { children: ReactNode }) =>
    createElement(
      QueryClientProvider,
      { client: qc },
      createElement(CaptureProvider, null, children),
    );
}

const UL_URL = "https://app.ultralibrarian.com/search?queryText=BQ24074";


// partCadSource still resolves the URL; needs are now passed into the hook by the caller.
function _cadSources(url: string | null) {
  // The real DTO shape: a list in the backend's trust order, plus the flattened head. A mock that
  // still returned only `url`/`vendor` would pass while the code reads `sources`.
  return url === null
    ? []
    : [
        {
          key: "ultralibrarian",
          label: "Ultra Librarian",
          url,
          tools: ["kicad", "altium"],
          aggregator: false,
          instruction: "Pick the part, choose KiCad and Altium, then Download.",
        },
      ];
}

function mockCadSourceUrl(url: string | null = UL_URL) {
  vi.spyOn(api, "partCadSource").mockResolvedValue({
    url,
    mpn: "BQ24074",
    vendor: "Ultra Librarian",
    needs: [],
    sources: _cadSources(url),
  } as never);
}

function render(needs: Requirement[], qc = new QueryClient()) {
  return {
    qc,
    ...renderHook(() => useGuidedCapture("part1", needs), { wrapper: wrapperWith(qc) }),
  };
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
  delete (window as { pywebview?: unknown }).pywebview;
});

describe("useGuidedCapture", () => {
  it("runs a capture for its own part through the cross-platform route", async () => {
    mockCadSourceUrl();
    const capture = mockCapture();
    const { result } = render(["kicad_symbol", "kicad_footprint"]);

    await act(async () => {
      await result.current.start();
    });

    expect(capture.run).toHaveBeenCalledWith(
      expect.objectContaining({
        partIds: ["part1"],
        vendor: undefined,
        mode: "automatic",
      }),
    );
    expect(result.current.status).toBe("done");
  });

  it("passes the preferred provider while keeping the first attempt automatic", async () => {
    mockCadSourceUrl();
    const capture = mockCapture();
    const { result } = render(["kicad_symbol", "kicad_footprint"]);

    await act(async () => {
      await result.current.start("ultralibrarian");
    });

    expect(capture.run).toHaveBeenCalledWith(
      expect.objectContaining({
        vendor: "ultralibrarian",
        mode: "automatic",
      }),
    );
  });

  it("still runs direct automatic acquisition when no provider URL resolves", async () => {
    mockCadSourceUrl(null);
    const capture = mockCapture();
    const { result } = render(["kicad_symbol", "kicad_footprint"]);

    await act(async () => {
      await result.current.start();
    });

    expect(result.current.status).toBe("done");
    expect(capture.run).toHaveBeenCalledWith(
      expect.objectContaining({
        partIds: ["part1"],
        vendor: undefined,
        mode: "automatic",
      }),
    );
  });

  it("forwards an explicit assisted retry for the selected provider", async () => {
    mockCadSourceUrl();
    const capture = mockCapture();
    const { result } = render(["kicad_symbol", "kicad_footprint"]);

    await act(async () => {
      await result.current.start("snapmagic", "assisted");
    });

    expect(capture.run).toHaveBeenCalledWith(
      expect.objectContaining({
        partIds: ["part1"],
        vendor: "snapmagic",
        mode: "assisted",
      }),
    );
  });

  it("forwards exhaustive collection without narrowing it to the preferred provider", async () => {
    mockCadSourceUrl();
    const capture = mockCapture([
      {
        event: "result",
        data: {
          result: {
            items: [
              {
                part_id: "part1",
                mpn: "BQ24074",
                display_name: "BQ24074",
                category: "ICs",
                status: "already-complete",
                needed: [],
                satisfied: [],
                remaining: [],
                retained: 2,
                sources: ["guided"],
                notes: [],
                error: "",
                collection_complete: true,
                provider_outcomes: [
                  {
                    route_id: "digikey:digikey-ultralibrarian",
                    provider_key: "digikey",
                    author_key: "digikey-ultralibrarian",
                    label: "DigiKey / Ultra Librarian",
                    status: "succeeded-retained",
                    attempted: true,
                    retained: 2,
                    activated: false,
                    reason: "Retained two exact files.",
                  },
                ],
              },
            ],
            counts: { "already-complete": 1 },
            retained: 2,
            collection_complete: true,
            stopped: false,
            stop_reason: "",
          },
        },
      },
      { event: "done", data: {} },
    ]);
    const { result } = render([]);

    await act(async () => {
      await result.current.start("digikey", "collect-all");
    });

    expect(capture.run).toHaveBeenCalledWith(
      expect.objectContaining({
        partIds: ["part1"],
        vendor: "digikey",
        mode: "collect-all",
      }),
    );
    expect(result.current.collectionComplete).toBe(true);
    expect(result.current.providerOutcomes).toHaveLength(1);
  });

  it("surfaces a failed run as an error rather than a quiet done", async () => {
    mockCadSourceUrl();
    mockCapture([
      { event: "error", data: { detail: "Ultra Librarian has no model for this part." } },
      { event: "done", data: {} },
    ]);
    const { result } = render(["kicad_symbol", "kicad_footprint"]);

    await act(async () => {
      await result.current.start();
    });

    expect(result.current.status).toBe("error");
  });

  it("projects idle for a part that is not the active capture", async () => {
    mockCadSourceUrl();
    mockCapture();
    const { result } = render(["kicad_symbol", "kicad_footprint"]);
    expect(result.current.status).toBe("idle");
    // and it still exposes the caller's needs, so the checklist renders before any run starts
    expect(result.current.needs).toEqual(["kicad_symbol", "kicad_footprint"]);
  });

  it("reset returns the hook to idle", async () => {
    mockCadSourceUrl();
    mockCapture();
    const { result } = render(["kicad_symbol", "kicad_footprint"]);
    await act(async () => {
      await result.current.start();
    });
    act(() => {
      result.current.reset();
    });
    expect(result.current.status).toBe("idle");
  });

});
