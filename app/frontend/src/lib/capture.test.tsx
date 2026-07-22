import { createElement, type ReactNode } from "react";
import { act, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { api } from "../api/client";
import { CaptureProvider, useCapture } from "./capture";

function wrap(qc: QueryClient) {
  return ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, createElement(CaptureProvider, null, children));
}

function mockSource(url: string | null = "https://app.ultralibrarian.com/x") {
  vi.spyOn(api, "partCadSource").mockResolvedValue({
    url,
    mpn: "M",
    vendor: "UltraLibrarian",
    needs: [],
  } as never);
}

function mockHost() {
  const open = vi.fn().mockResolvedValue("tok");
  (window as unknown as { pywebview: { api: { open_cad_download: typeof open } } }).pywebview = {
    api: { open_cad_download: open },
  };
  return open;
}

afterEach(() => {
  vi.restoreAllMocks();
  delete (window as { pywebview?: unknown }).pywebview;
  delete window.__STOCKROOM_CAD_DOWNLOAD__;
});

describe("CaptureProvider store", () => {
  it("holds one active capture and replaces it when a different part starts", async () => {
    mockSource();
    mockHost();
    const { result } = renderHook(() => useCapture(), { wrapper: wrap(new QueryClient()) });

    await act(async () => {
      await result.current.start("p1", "Part One", ["kicad_symbol"]);
    });
    expect(result.current.active.partId).toBe("p1");
    expect(result.current.active.partName).toBe("Part One");
    expect(result.current.active.status).toBe("receiving");

    await act(async () => {
      await result.current.start("p2", "Part Two", ["kicad_symbol"]);
    });
    expect(result.current.active.partId).toBe("p2"); // replaced, never two at once
    expect(result.current.active.partName).toBe("Part Two");
  });

  it("keepWorking backgrounds the active capture so the pill can take over", async () => {
    mockSource();
    mockHost();
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
    mockHost();
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
    mockHost();
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
});
