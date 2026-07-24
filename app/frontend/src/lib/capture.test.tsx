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

  // -- Phase 3 (DONE-02, HUD-01): the host done signal + the part-name pass-through --

  it("a done signal lands done only after every need actually attached", async () => {
    mockSource();
    mockHost();
    const { result } = renderHook(() => useCapture(), { wrapper: wrap(new QueryClient()) });

    vi.spyOn(api, "altiumAttach").mockResolvedValue({} as never);
    vi.spyOn(api, "altiumRegenerate").mockResolvedValue({} as never);
    await act(async () => {
      await result.current.start("p1", "One", ["altium_symbol"]);
    });
    expect(result.current.active.status).toBe("receiving");

    // the file ATTACHES via the per-file forward: that alone completes the capture
    // (the host's later done signal is redundant by then, and its absence can no
    // longer fabricate one)
    await act(async () => {
      await window.__STOCKROOM_CAD_DOWNLOAD__!({
        path: "C:/dl/a.SchLib", token: "tok",
        requirements: ["altium_symbol"], altiumPaths: ["C:/dl/a.SchLib"],
      });
    });

    expect(result.current.active.status).toBe("done");
    expect(window.__STOCKROOM_CAD_DOWNLOAD__).toBeUndefined();
  });

  it("a done signal with needs still unattached is honest, never a fabricated done (live 2026-07-24)", async () => {
    mockSource();
    mockHost();
    const { result } = renderHook(() => useCapture(), { wrapper: wrap(new QueryClient()) });

    vi.spyOn(api, "altiumAttach").mockResolvedValue({} as never);
    vi.spyOn(api, "altiumRegenerate").mockResolvedValue({} as never);
    await act(async () => {
      await result.current.start("p1", "One", ["kicad_symbol", "altium_symbol", "altium_footprint"]);
    });
    // only the altium files ever attached; the host still closes the window and says done
    await act(async () => {
      await window.__STOCKROOM_CAD_DOWNLOAD__!({
        path: "C:/dl/a.zip", token: "tok",
        requirements: ["altium_symbol", "altium_footprint"],
        altiumPaths: ["C:/x/a.SchLib", "C:/x/a.PcbLib"],
      });
    });
    await act(async () => {
      window.__STOCKROOM_CAD_DOWNLOAD__!({ signal: "done", token: "tok" });
      await Promise.resolve();
    });

    expect(result.current.active.status).toBe("receiving");
    expect(result.current.active.message).toMatch(/KiCad Symbol/);
    // the handler stays armed so a late forward / Browse For Files can still finish it
    expect(window.__STOCKROOM_CAD_DOWNLOAD__).toBeDefined();
  });

  it("ignores a done whose token does not match the active capture (B4 guard)", async () => {
    mockSource();
    mockHost();
    const { result } = renderHook(() => useCapture(), { wrapper: wrap(new QueryClient()) });

    await act(async () => {
      await result.current.start("p1", "One", ["kicad_symbol"]);
    });
    await act(async () => {
      window.__STOCKROOM_CAD_DOWNLOAD__!({ signal: "done", token: "STALE" });
      await Promise.resolve();
    });

    expect(result.current.active.status).toBe("receiving"); // never marked the replaced part done
  });

  it("treats a repeated done as a no-op once the capture is already done", async () => {
    mockSource();
    mockHost();
    vi.spyOn(api, "altiumAttach").mockResolvedValue({} as never);
    vi.spyOn(api, "altiumRegenerate").mockResolvedValue({} as never);
    const { result } = renderHook(() => useCapture(), { wrapper: wrap(new QueryClient()) });

    await act(async () => {
      await result.current.start("p1", "One", ["altium_symbol"]);
    });
    const handler = window.__STOCKROOM_CAD_DOWNLOAD__!;
    await act(async () => {
      await handler({
        path: "C:/dl/a.SchLib", token: "tok",
        requirements: ["altium_symbol"], altiumPaths: ["C:/dl/a.SchLib"],
      });
    });
    expect(result.current.active.status).toBe("done");
    // a LATE host done (the handler reference survived in the host) stays a no-op
    await act(async () => {
      handler({ signal: "done", token: "tok" });
      await Promise.resolve();
    });
    expect(result.current.active.status).toBe("done");

    await act(async () => {
      handler({ signal: "done", token: "tok" }); // a duplicate late done must not corrupt the state
      await Promise.resolve();
    });
    expect(result.current.active.status).toBe("done");
  });

  it("passes the active part name to the host open so the HUD can show it (HUD-01)", async () => {
    mockSource();
    const open = mockHost();
    const { result } = renderHook(() => useCapture(), { wrapper: wrap(new QueryClient()) });

    await act(async () => {
      await result.current.start("p1", "BQ24074", ["kicad_symbol"]);
    });

    expect(open).toHaveBeenCalledWith("https://app.ultralibrarian.com/x", ["kicad_symbol"], "BQ24074");
  });
});
