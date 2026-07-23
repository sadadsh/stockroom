import { createElement, type ReactNode } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Requirement, StagingCandidate } from "../api/types";
import { useGuidedCapture } from "./useGuidedCapture";
import { CaptureProvider } from "./capture";

function wrapperWith(qc: QueryClient) {
  return ({ children }: { children: ReactNode }) =>
    createElement(
      QueryClientProvider,
      { client: qc },
      createElement(CaptureProvider, null, children),
    );
}

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) controller.enqueue(enc.encode(c));
      controller.close();
    },
  });
}

const CANDIDATE: StagingCandidate = {
  vendor: "ultralibrarian",
  symbol_lib_path: "/tmp/staging/x.kicad_sym",
  symbol_name: "BQ24074",
  footprint_variants: ["/tmp/staging/BQ24074.pretty/QFN-16.kicad_mod"],
  chosen_footprint_index: 0,
  model_path: "/tmp/staging/BQ24074.step",
  datasheet_path: null,
  display_name: "BQ24074",
  entry_name: "BQ24074",
  category: "IC",
  mpn: "BQ24074",
  manufacturer: "Texas Instruments",
  description: "Li-Ion charger",
  tags: [],
  purchase: [],
  gaps: [],
};

function inspectResultStream(candidates: StagingCandidate[]): ReadableStream<Uint8Array> {
  return streamOf([
    `event: result\ndata: {"result":${JSON.stringify(candidates)}}\n\n`,
    "event: done\ndata: {}\n\n",
  ]);
}

const UL_URL = "https://app.ultralibrarian.com/search?queryText=BQ24074";
const KICAD_NEEDS: Requirement[] = ["kicad_symbol", "kicad_footprint", "kicad_model"];
const ALL_NEEDS: Requirement[] = [
  "kicad_symbol",
  "kicad_footprint",
  "kicad_model",
  "altium_symbol",
  "altium_footprint",
];

function mockHost(returnToken: string | undefined = "tok") {
  const open = vi.fn().mockResolvedValue(returnToken);
  (window as unknown as { pywebview: { api: { open_cad_download: typeof open } } }).pywebview = {
    api: { open_cad_download: open },
  };
  return open;
}

// partCadSource still resolves the URL; needs are now passed into the hook by the caller.
function mockCadSourceUrl(url: string | null = UL_URL) {
  vi.spyOn(api, "partCadSource").mockResolvedValue({
    url,
    mpn: "BQ24074",
    vendor: "UltraLibrarian",
    needs: [],
  } as never);
}

function mockKicadAttach() {
  vi.spyOn(api, "assetsInspect").mockResolvedValue({ job_id: "j1" });
  vi.spyOn(api, "openJobStream").mockResolvedValue(inspectResultStream([CANDIDATE]));
  vi.spyOn(api, "assetsCommit").mockResolvedValue({} as never);
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
  delete window.__STOCKROOM_CAD_DOWNLOAD__;
});

describe("useGuidedCapture", () => {
  it("resolves the page, opens it through the host bridge, and waits (receiving)", async () => {
    const open = mockHost("tok");
    mockCadSourceUrl();
    const { result } = render(KICAD_NEEDS);

    await act(async () => {
      await result.current.start();
    });

    expect(api.partCadSource).toHaveBeenCalledWith("part1");
    // start() now threads the part name (empty here, since this adapter render passes none) as the
    // third arg so the HUD can display part name + DigiKey (HUD-01).
    expect(open).toHaveBeenCalledWith(UL_URL, KICAD_NEEDS, "");
    expect(result.current.status).toBe("receiving");
    expect(result.current.needs).toEqual(KICAD_NEEDS);
    expect(typeof window.__STOCKROOM_CAD_DOWNLOAD__).toBe("function");
  });

  it("transitions to timed-out when nothing lands within the watchdog window (B1 fix)", async () => {
    vi.useFakeTimers();
    mockHost("tok");
    mockCadSourceUrl();
    const { result } = render(KICAD_NEEDS);

    await act(async () => {
      await result.current.start();
    });
    expect(result.current.status).toBe("receiving");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(180_001);
    });
    expect(result.current.status).toBe("timed-out");
  });

  it("marks KiCad requirements received and attaches via the ingest pipeline", async () => {
    mockHost("tok");
    mockCadSourceUrl();
    mockKicadAttach();
    const { result, qc } = render(KICAD_NEEDS);
    const invalidateSpy = vi.spyOn(qc, "invalidateQueries");

    await act(async () => {
      await result.current.start();
    });
    await act(async () => {
      window.__STOCKROOM_CAD_DOWNLOAD__!({
        path: "C:\\Downloads\\BQ24074.zip",
        token: "tok",
        requirements: ["kicad_symbol", "kicad_footprint", "kicad_model"],
      });
      await Promise.resolve();
    });

    await waitFor(() => expect(result.current.status).toBe("done"));
    expect(api.assetsInspect).toHaveBeenCalledWith("part1", ["C:\\Downloads\\BQ24074.zip"]);
    expect(api.assetsCommit).toHaveBeenCalledWith("part1", CANDIDATE);
    expect(result.current.received.kicad_symbol).toBe(true);
    expect(result.current.received.kicad_model).toBe(true);
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["cad-source", "part1"] });
    expect(window.__STOCKROOM_CAD_DOWNLOAD__).toBeUndefined();
  });

  it("attaches Altium requirements via altiumAttach with the extracted loose paths", async () => {
    mockHost("tok");
    mockCadSourceUrl();
    const altiumSpy = vi.spyOn(api, "altiumAttach").mockResolvedValue(undefined);
    const { result } = render(["altium_symbol", "altium_footprint"]);

    await act(async () => {
      await result.current.start();
    });
    await act(async () => {
      window.__STOCKROOM_CAD_DOWNLOAD__!({
        path: "C:\\Downloads\\BQ24074.zip",
        token: "tok",
        requirements: ["altium_symbol", "altium_footprint"],
        altiumPaths: ["C:\\tmp\\BQ24074.SchLib", "C:\\tmp\\BQ24074.PcbLib"],
      });
      await Promise.resolve();
    });

    await waitFor(() => expect(result.current.status).toBe("done"));
    expect(altiumSpy).toHaveBeenCalledWith("part1", [
      "C:\\tmp\\BQ24074.SchLib",
      "C:\\tmp\\BQ24074.PcbLib",
    ]);
    expect(result.current.altiumComplete).toBe(true);
  });

  it("ignores a capture whose session token does not match (B4 guard)", async () => {
    mockHost("tok");
    mockCadSourceUrl();
    const inspectSpy = vi.spyOn(api, "assetsInspect");
    const { result } = render(["kicad_symbol"]);

    await act(async () => {
      await result.current.start();
    });
    await act(async () => {
      window.__STOCKROOM_CAD_DOWNLOAD__!({
        path: "stale.zip",
        token: "STALE",
        requirements: ["kicad_symbol"],
      });
      await Promise.resolve();
    });

    expect(inspectSpy).not.toHaveBeenCalled();
    expect(result.current.status).toBe("receiving");
    expect(result.current.received.kicad_symbol).toBeUndefined();
  });

  it("honors a host timeout signal forward", async () => {
    mockHost("tok");
    mockCadSourceUrl();
    const { result } = render(["kicad_symbol"]);

    await act(async () => {
      await result.current.start();
    });
    await act(async () => {
      window.__STOCKROOM_CAD_DOWNLOAD__!({ signal: "timeout", token: "tok" });
      await Promise.resolve();
    });

    expect(result.current.status).toBe("timed-out");
  });

  it("projects the terminal done state when the host forwards a done signal (DONE-02)", async () => {
    mockHost("tok");
    mockCadSourceUrl();
    const { result } = render(["kicad_symbol"]);

    await act(async () => {
      await result.current.start();
    });
    await act(async () => {
      window.__STOCKROOM_CAD_DOWNLOAD__!({ signal: "done", token: "tok" });
      await Promise.resolve();
    });

    expect(result.current.status).toBe("done");
  });

  it("accepts a legacy bare-path forward and runs the KiCad pipeline", async () => {
    mockHost(undefined); // an old host that echoes no token and forwards a bare path
    mockCadSourceUrl();
    mockKicadAttach();
    const { result } = render(KICAD_NEEDS);

    await act(async () => {
      await result.current.start();
    });
    await act(async () => {
      window.__STOCKROOM_CAD_DOWNLOAD__!("C:\\Downloads\\legacy.zip");
      await Promise.resolve();
    });

    await waitFor(() => expect(result.current.status).toBe("done"));
    expect(api.assetsInspect).toHaveBeenCalledWith("part1", ["C:\\Downloads\\legacy.zip"]);
  });

  it("reports unavailable and never opens the host bridge when no source resolves", async () => {
    const open = mockHost("tok");
    mockCadSourceUrl(null);
    const { result } = render([]);

    await act(async () => {
      await result.current.start();
    });

    expect(result.current.status).toBe("unavailable");
    expect(open).not.toHaveBeenCalled();
  });

  it("submitPaths serves the manual-pick fallback through the KiCad pipeline", async () => {
    mockKicadAttach();
    const { result } = render(KICAD_NEEDS);

    await act(async () => {
      await result.current.submitPaths(["C:\\manual\\pick.zip"]);
    });

    expect(api.assetsInspect).toHaveBeenCalledWith("part1", ["C:\\manual\\pick.zip"]);
    expect(result.current.status).toBe("done");
  });

  it("browse-first stays receiving (not falsely done) and re-arms the watchdog", async () => {
    // A part missing BOTH KiCad and Altium: a manual KiCad browse must mark only the
    // KiCad rows, report "receiving" (not "done"), and re-arm the watchdog so the
    // remaining Altium file can never hang forever.
    vi.useFakeTimers();
    mockKicadAttach();
    const { result } = render(ALL_NEEDS);

    await act(async () => {
      await result.current.submitPaths(["k.zip"]);
    });
    expect(result.current.status).toBe("receiving");
    expect(result.current.received.kicad_symbol).toBe(true);
    expect(result.current.received.altium_symbol).toBeUndefined();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(180_001);
    });
    expect(result.current.status).toBe("timed-out");
  });

  it("surfaces an empty inspect result as an honest error instead of attaching nothing", async () => {
    vi.spyOn(api, "assetsInspect").mockResolvedValue({ job_id: "j3" });
    vi.spyOn(api, "openJobStream").mockResolvedValue(inspectResultStream([]));
    const commitSpy = vi.spyOn(api, "assetsCommit");
    const { result } = render(KICAD_NEEDS);

    await act(async () => {
      await result.current.submitPaths(["empty.zip"]);
    });

    expect(result.current.status).toBe("error");
    expect(result.current.message).toContain("No usable");
    expect(commitSpy).not.toHaveBeenCalled();
  });

  it("reset returns the hook to idle and tears down any armed capture handler", async () => {
    mockHost("tok");
    mockCadSourceUrl();
    const { result } = render(["kicad_symbol"]);

    await act(async () => {
      await result.current.start();
    });
    expect(typeof window.__STOCKROOM_CAD_DOWNLOAD__).toBe("function");

    act(() => {
      result.current.reset();
    });

    expect(result.current.status).toBe("idle");
    expect(window.__STOCKROOM_CAD_DOWNLOAD__).toBeUndefined();
  });
});
