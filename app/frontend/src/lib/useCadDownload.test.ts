import { createElement, type ReactNode } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { api } from "../api/client";
import type { StagingCandidate } from "../api/types";
import { useCadDownload } from "./useCadDownload";

function wrapperWith(qc: QueryClient) {
  return ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children);
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
  vendor: "digikey",
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

afterEach(() => {
  vi.restoreAllMocks();
  delete (window as { pywebview?: unknown }).pywebview;
  delete window.__STOCKROOM_CAD_DOWNLOAD__;
});

describe("useCadDownload", () => {
  it("resolves the DigiKey page, opens it through the host bridge, then waits for the capture", async () => {
    const openCadDownload = vi.fn();
    (window as unknown as { pywebview: { api: { open_cad_download: typeof openCadDownload } } }).pywebview =
      { api: { open_cad_download: openCadDownload } };
    vi.spyOn(api, "partCadSource").mockResolvedValue({
      url: "https://www.digikey.com/en/products/detail/x/BQ24074/123",
      mpn: "BQ24074",
      vendor: "DigiKey",
    });
    const qc = new QueryClient();
    const { result } = renderHook(() => useCadDownload("part1"), { wrapper: wrapperWith(qc) });

    await act(async () => {
      await result.current.start();
    });

    expect(api.partCadSource).toHaveBeenCalledWith("part1");
    expect(openCadDownload).toHaveBeenCalledWith(
      "https://www.digikey.com/en/products/detail/x/BQ24074/123",
    );
    expect(result.current.status).toBe("waiting");
    expect(typeof window.__STOCKROOM_CAD_DOWNLOAD__).toBe("function");
  });

  it("runs inspect then commit once the captured-download global fires, and reports done", async () => {
    const openCadDownload = vi.fn();
    (window as unknown as { pywebview: { api: { open_cad_download: typeof openCadDownload } } }).pywebview =
      { api: { open_cad_download: openCadDownload } };
    vi.spyOn(api, "partCadSource").mockResolvedValue({
      url: "https://www.digikey.com/en/products/detail/x/BQ24074/123",
      mpn: "BQ24074",
      vendor: "DigiKey",
    });
    vi.spyOn(api, "assetsInspect").mockResolvedValue({ job_id: "j1" });
    vi.spyOn(api, "openJobStream").mockResolvedValue(inspectResultStream([CANDIDATE]));
    vi.spyOn(api, "assetsCommit").mockResolvedValue({} as never);
    const qc = new QueryClient();
    const invalidateSpy = vi.spyOn(qc, "invalidateQueries");
    const { result } = renderHook(() => useCadDownload("part1"), { wrapper: wrapperWith(qc) });

    await act(async () => {
      await result.current.start();
    });

    await act(async () => {
      window.__STOCKROOM_CAD_DOWNLOAD__!("C:\\Users\\me\\Downloads\\BQ24074.zip");
      // let the async submitPaths() chain (inspect -> stream -> commit) settle
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    await waitFor(() => expect(result.current.status).toBe("done"));
    expect(api.assetsInspect).toHaveBeenCalledWith("part1", [
      "C:\\Users\\me\\Downloads\\BQ24074.zip",
    ]);
    expect(api.assetsCommit).toHaveBeenCalledWith("part1", CANDIDATE);
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["part", "part1"] });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["cad-source", "part1"] });
    // the one-shot handler cleans itself up once it has fired
    expect(window.__STOCKROOM_CAD_DOWNLOAD__).toBeUndefined();
  });

  it("only honors the first capture of a fresh start(), ignoring a redundant second one", async () => {
    const openCadDownload = vi.fn();
    (window as unknown as { pywebview: { api: { open_cad_download: typeof openCadDownload } } }).pywebview =
      { api: { open_cad_download: openCadDownload } };
    vi.spyOn(api, "partCadSource").mockResolvedValue({
      url: "https://www.digikey.com/en/products/detail/x/BQ24074/123",
      mpn: "BQ24074",
      vendor: "DigiKey",
    });
    vi.spyOn(api, "assetsInspect").mockResolvedValue({ job_id: "j1" });
    vi.spyOn(api, "openJobStream").mockResolvedValue(inspectResultStream([CANDIDATE]));
    vi.spyOn(api, "assetsCommit").mockResolvedValue({} as never);
    const qc = new QueryClient();
    const { result } = renderHook(() => useCadDownload("part1"), { wrapper: wrapperWith(qc) });

    await act(async () => {
      await result.current.start();
    });
    await act(async () => {
      window.__STOCKROOM_CAD_DOWNLOAD__!("first.zip");
      window.__STOCKROOM_CAD_DOWNLOAD__?.("second.zip");
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    await waitFor(() => expect(result.current.status).toBe("done"));
    expect(api.assetsInspect).toHaveBeenCalledTimes(1);
    expect(api.assetsInspect).toHaveBeenCalledWith("part1", ["first.zip"]);
  });

  it("reports unavailable and never opens the host bridge when no DigiKey source resolves", async () => {
    const openCadDownload = vi.fn();
    (window as unknown as { pywebview: { api: { open_cad_download: typeof openCadDownload } } }).pywebview =
      { api: { open_cad_download: openCadDownload } };
    vi.spyOn(api, "partCadSource").mockResolvedValue({ url: null, mpn: "", vendor: "DigiKey" });
    const qc = new QueryClient();
    const { result } = renderHook(() => useCadDownload("part1"), { wrapper: wrapperWith(qc) });

    await act(async () => {
      await result.current.start();
    });

    expect(result.current.status).toBe("unavailable");
    expect(result.current.message).toBe("No DigiKey CAD source for this part.");
    expect(openCadDownload).not.toHaveBeenCalled();
  });

  it("degrades gracefully with no window.pywebview, never throwing", async () => {
    vi.spyOn(api, "partCadSource").mockResolvedValue({
      url: "https://www.digikey.com/en/products/detail/x/BQ24074/123",
      mpn: "BQ24074",
      vendor: "DigiKey",
    });
    const qc = new QueryClient();
    const { result } = renderHook(() => useCadDownload("part1"), { wrapper: wrapperWith(qc) });

    await act(async () => {
      await expect(result.current.start()).resolves.not.toThrow();
    });

    expect(result.current.status).toBe("waiting");
    expect(result.current.url).toBe("https://www.digikey.com/en/products/detail/x/BQ24074/123");
    // no host bridge means no capture hook was ever armed
    expect(window.__STOCKROOM_CAD_DOWNLOAD__).toBeUndefined();
  });

  it("submitPaths serves the manual-pick fallback the same way, without a prior start()", async () => {
    vi.spyOn(api, "assetsInspect").mockResolvedValue({ job_id: "j2" });
    vi.spyOn(api, "openJobStream").mockResolvedValue(inspectResultStream([CANDIDATE]));
    vi.spyOn(api, "assetsCommit").mockResolvedValue({} as never);
    const qc = new QueryClient();
    const { result } = renderHook(() => useCadDownload("part1"), { wrapper: wrapperWith(qc) });

    await act(async () => {
      await result.current.submitPaths(["C:\\manual\\pick.zip"]);
    });

    expect(api.assetsInspect).toHaveBeenCalledWith("part1", ["C:\\manual\\pick.zip"]);
    expect(result.current.status).toBe("done");
  });

  it("surfaces an empty inspect result as an honest error instead of committing nothing", async () => {
    vi.spyOn(api, "assetsInspect").mockResolvedValue({ job_id: "j3" });
    vi.spyOn(api, "openJobStream").mockResolvedValue(inspectResultStream([]));
    const commitSpy = vi.spyOn(api, "assetsCommit");
    const qc = new QueryClient();
    const { result } = renderHook(() => useCadDownload("part1"), { wrapper: wrapperWith(qc) });

    await act(async () => {
      await result.current.submitPaths(["empty.zip"]);
    });

    expect(result.current.status).toBe("error");
    expect(result.current.message).toContain("No usable");
    expect(commitSpy).not.toHaveBeenCalled();
  });

  it("surfaces an assets/commit failure as an error state", async () => {
    vi.spyOn(api, "assetsInspect").mockResolvedValue({ job_id: "j4" });
    vi.spyOn(api, "openJobStream").mockResolvedValue(inspectResultStream([CANDIDATE]));
    vi.spyOn(api, "assetsCommit").mockRejectedValue(new Error("commit failed"));
    const qc = new QueryClient();
    const { result } = renderHook(() => useCadDownload("part1"), { wrapper: wrapperWith(qc) });

    await act(async () => {
      await result.current.submitPaths(["a.zip"]);
    });

    expect(result.current.status).toBe("error");
    expect(result.current.message).toBe("commit failed");
  });

  it("reset returns the hook to idle and tears down any armed capture handler", async () => {
    const openCadDownload = vi.fn();
    (window as unknown as { pywebview: { api: { open_cad_download: typeof openCadDownload } } }).pywebview =
      { api: { open_cad_download: openCadDownload } };
    vi.spyOn(api, "partCadSource").mockResolvedValue({
      url: "https://www.digikey.com/en/products/detail/x/BQ24074/123",
      mpn: "BQ24074",
      vendor: "DigiKey",
    });
    const qc = new QueryClient();
    const { result } = renderHook(() => useCadDownload("part1"), { wrapper: wrapperWith(qc) });

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
