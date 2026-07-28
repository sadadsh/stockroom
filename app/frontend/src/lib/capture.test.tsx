import { createElement, type ReactNode } from "react";
import { act, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { api } from "../api/client";
import { CaptureProvider, useCapture } from "./capture";
import { mockCapture, sseStream } from "../test/captureMocks";

function wrap(qc: QueryClient) {
  return ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, createElement(CaptureProvider, null, children));
}

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

function mockSource(url: string | null = "https://app.ultralibrarian.com/x") {
  vi.spyOn(api, "partCadSource").mockResolvedValue({
    url,
    mpn: "M",
    vendor: "Ultra Librarian",
    needs: [],
    sources: _cadSources(url),
  } as never);
}

afterEach(() => {
  vi.restoreAllMocks();
  delete (window as { pywebview?: unknown }).pywebview;
  delete window.__STOCKROOM_CAD_DOWNLOAD__;
});

describe("CaptureProvider store", () => {
  it("holds one active capture and replaces it when a different part starts", async () => {
    mockSource();
    mockCapture();
    const { result } = renderHook(() => useCapture(), { wrapper: wrap(new QueryClient()) });

    await act(async () => {
      await result.current.start("p1", "Part One", ["kicad_symbol"]);
    });
    expect(result.current.active.partId).toBe("p1");
    expect(result.current.active.partName).toBe("Part One");
    // `start` now awaits the whole job, so a finished run reports `done`. It used to hand off to a
    // Windows-only host callback and sit in `receiving` waiting to be told.
    expect(result.current.active.status).toBe("done");

    await act(async () => {
      await result.current.start("p2", "Part Two", ["kicad_symbol"]);
    });
    expect(result.current.active.partId).toBe("p2"); // replaced, never two at once
    expect(result.current.active.partName).toBe("Part Two");
  });

  it("keepWorking backgrounds the active capture so the pill can take over", async () => {
    mockSource();
    mockCapture();
    const { result } = renderHook(() => useCapture(), { wrapper: wrap(new QueryClient()) });

    await act(async () => {
      await result.current.start("p1", "One", ["kicad_symbol"]);
    });
    expect(result.current.active.backgrounded).toBe(false);
    act(() => {
      result.current.keepWorking();
    });
    expect(result.current.active.backgrounded).toBe(true);
  });

  it("requestReopen exposes the part id and unbackgrounds; clearReopen clears it", async () => {
    mockSource();
    mockCapture();
    const { result } = renderHook(() => useCapture(), { wrapper: wrap(new QueryClient()) });

    await act(async () => {
      await result.current.start("p1", "One", ["kicad_symbol"]);
    });
    act(() => {
      result.current.keepWorking();
    });
    act(() => {
      result.current.requestReopen();
    });
    expect(result.current.reopenPartId).toBe("p1");
    expect(result.current.active.backgrounded).toBe(false);

    act(() => {
      result.current.clearReopen();
    });
    expect(result.current.reopenPartId).toBeNull();
  });

  it("reset clears the active capture back to idle", async () => {
    mockSource();
    mockCapture();
    const { result } = renderHook(() => useCapture(), { wrapper: wrap(new QueryClient()) });

    await act(async () => {
      await result.current.start("p1", "One", ["kicad_symbol"]);
    });
    act(() => {
      result.current.reset();
    });
    expect(result.current.active.partId).toBeNull();
    expect(result.current.active.status).toBe("idle");
  });

  // -- The behaviours that still matter now the host callback is gone -----------------------
  //
  // The old tests here drove `window.__STOCKROOM_CAD_DOWNLOAD__`: a token-guarded "done" signal
  // forwarded from a Windows-only host. That protocol no longer exists - the backend owns the
  // capture and reports through the job stream. What DOES still matter is kept, driven through
  // the real route.

  it("captures through the cross-platform route, not a Windows-only host object", async () => {
    mockSource();
    const capture = mockCapture();
    const { result } = renderHook(() => useCapture(), { wrapper: wrap(new QueryClient()) });

    await act(async () => {
      await result.current.start("p1", "Part One", ["kicad_symbol"]);
    });

    expect(capture.run).toHaveBeenCalledWith(
      expect.objectContaining({ partIds: ["p1"], vendor: "ultralibrarian" }),
    );
    // and nothing reached for the host bridge that used to exist
    expect((window as { pywebview?: unknown }).pywebview).toBeUndefined();
  });

  it("a capture whose part was replaced mid-flight never marks the new part", async () => {
    // The B4 guard, preserved. Its mechanism changed (a token from the host -> comparing the part
    // the run was started for) but the failure it prevents is identical: one part's result landing
    // on another part's checklist.
    mockSource();
    vi.spyOn(api, "runCapture").mockResolvedValue({ job_id: "job-1" });
    let release: (() => void) | null = null;
    vi.spyOn(api, "openJobStream").mockImplementation(
      () =>
        new Promise((resolve) => {
          release = () => resolve(sseStream([{ event: "done", data: {} }]) as never);
        }) as never,
    );

    const { result } = renderHook(() => useCapture(), { wrapper: wrap(new QueryClient()) });
    let first: Promise<void>;
    await act(async () => {
      first = result.current.start("p1", "Part One", ["kicad_symbol"]);
      await Promise.resolve();
    });
    // a second part takes over while the first run is still streaming
    mockCapture();
    await act(async () => {
      await result.current.start("p2", "Part Two", ["kicad_symbol"]);
    });
    await act(async () => {
      release?.();
      await first!;
    });

    expect(result.current.active.partId).toBe("p2");
    expect(result.current.active.partName).toBe("Part Two");
  });

  it("an error frame from the run surfaces as an error, never a silent done", async () => {
    mockSource();
    mockCapture([
      { event: "error", data: { detail: "Ultra Librarian has no model for this part." } },
      { event: "done", data: {} },
    ]);
    const { result } = renderHook(() => useCapture(), { wrapper: wrap(new QueryClient()) });

    await act(async () => {
      await result.current.start("p1", "Part One", ["kicad_symbol"]);
    });

    expect(result.current.active.status).toBe("error");
    expect(result.current.active.message).toContain("no model");
  });

  it("an unchanged completion report never renders Files Complete", async () => {
    mockSource();
    mockCapture([
      {
        event: "result",
        data: {
          result: {
            items: [
              {
                part_id: "p1",
                mpn: "M",
                display_name: "Part One",
                category: "ICs",
                status: "unchanged",
                needed: ["kicad_symbol"],
                satisfied: [],
                remaining: ["kicad_symbol"],
                sources: [],
                notes: [],
                error: "No provider delivered an exact model.",
              },
            ],
            counts: { unchanged: 1 },
            stopped: false,
            stop_reason: "",
          },
        },
      },
      { event: "done", data: {} },
    ]);
    const { result } = renderHook(() => useCapture(), { wrapper: wrap(new QueryClient()) });

    await act(async () => {
      await result.current.start("p1", "Part One", ["kicad_symbol"]);
    });

    expect(result.current.active.status).toBe("error");
    expect(result.current.active.message).toContain("No provider delivered");
  });

  it("shows non-error provider explanations before the remaining CAD gaps", async () => {
    mockSource();
    mockCapture([
      {
        event: "result",
        data: {
          result: {
            items: [
              {
                part_id: "p1",
                mpn: "M",
                display_name: "Part One",
                category: "ICs",
                status: "unchanged",
                needed: ["kicad_symbol"],
                satisfied: [],
                remaining: ["kicad_symbol"],
                sources: [],
                notes: ["snapmagic: no exact CAD model was found"],
                error: "",
              },
            ],
            counts: { unchanged: 1 },
            stopped: false,
            stop_reason: "",
          },
        },
      },
      { event: "done", data: {} },
    ]);
    const { result } = renderHook(() => useCapture(), { wrapper: wrap(new QueryClient()) });

    await act(async () => {
      await result.current.start("p1", "Part One", ["kicad_symbol"]);
    });

    expect(result.current.active.status).toBe("error");
    expect(result.current.active.message).toContain("snapmagic: no exact CAD model was found");
    expect(result.current.active.message).toContain("Still missing: KiCad Symbol");
    expect(result.current.active.message?.indexOf("snapmagic")).toBeLessThan(
      result.current.active.message?.indexOf("Still missing") ?? 0,
    );
  });
});
