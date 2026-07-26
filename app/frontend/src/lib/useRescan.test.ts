import { createElement, type ReactNode } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { api } from "../api/client";
import { useRescan } from "./useRescan";

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

afterEach(() => vi.restoreAllMocks());

describe("useRescan", () => {
  it("accumulates a running tally across per-part progress events, then folds the terminal summary", async () => {
    vi.spyOn(api, "rescanLibrary").mockResolvedValue({ job_id: "r1" });
    vi.spyOn(api, "openJobStream").mockResolvedValue(
      streamOf([
        'event: progress\ndata: {"pct":0,"done":0,"total":2,"message":"2 parts to refresh"}\n\n',
        'event: progress\ndata: {"pct":50,"done":1,"total":2,"part_id":"lm358","outcome":"updated"}\n\n',
        'event: progress\ndata: {"pct":100,"done":2,"total":2,"part_id":"tps1","outcome":"unchanged"}\n\n',
        'event: result\ndata: {"result":{"total":2,"updated":1,"unchanged":1,"no_data":0,"failed":0,"paused_providers":[],"message":"Refreshed 1 of 2 (1 unchanged, 0 no data, 0 failed)"}}\n\n',
        "event: done\ndata: {}\n\n",
      ]),
    );
    const qc = new QueryClient();
    const { result } = renderHook(() => useRescan(), { wrapper: wrapperWith(qc) });

    await act(async () => {
      await result.current.start(false);
    });
    await waitFor(() => expect(result.current.status).toBe("done"));

    expect(result.current.tally).toEqual({
      done: 2,
      total: 2,
      updated: 1,
      unchanged: 1,
      no_data: 0,
      failed: 0,
    });
    expect(result.current.currentPartId).toBe("tps1");
    expect(result.current.startMessage).toBe("2 parts to refresh");
    expect(result.current.summary?.message).toContain("Refreshed 1 of 2");
    expect(api.rescanLibrary).toHaveBeenCalledWith(false);
  });

  it("counts a failed part once even though the engine emits a warn event ahead of its outcome event", async () => {
    vi.spyOn(api, "rescanLibrary").mockResolvedValue({ job_id: "r2" });
    vi.spyOn(api, "openJobStream").mockResolvedValue(
      streamOf([
        'event: progress\ndata: {"pct":0,"done":0,"total":1,"message":"1 part to refresh"}\n\n',
        'event: progress\ndata: {"level":"warn","part_id":"bad1","message":"bad1: timeout"}\n\n',
        'event: progress\ndata: {"pct":100,"done":1,"total":1,"part_id":"bad1","outcome":"failed"}\n\n',
        'event: result\ndata: {"result":{"total":1,"updated":0,"unchanged":0,"no_data":0,"failed":1,"paused_providers":[],"message":"Refreshed 0 of 1 (0 unchanged, 0 no data, 1 failed)"}}\n\n',
        "event: done\ndata: {}\n\n",
      ]),
    );
    const qc = new QueryClient();
    const { result } = renderHook(() => useRescan(), { wrapper: wrapperWith(qc) });

    await act(async () => {
      await result.current.start(false);
    });
    await waitFor(() => expect(result.current.status).toBe("done"));

    expect(result.current.tally.failed).toBe(1);
    expect(result.current.currentPartId).toBe("bad1");
    // The warn line never overwrites the persistent "N parts to refresh" header line.
    expect(result.current.startMessage).toBe("1 part to refresh");
  });

  it("invalidates the last-known rescan state once the terminal result lands", async () => {
    vi.spyOn(api, "rescanLibrary").mockResolvedValue({ job_id: "r3" });
    vi.spyOn(api, "openJobStream").mockResolvedValue(
      streamOf([
        'event: result\ndata: {"result":{"total":0,"updated":0,"unchanged":0,"no_data":0,"failed":0,"paused_providers":[],"message":"Refreshed 0 of 0"}}\n\n',
        "event: done\ndata: {}\n\n",
      ]),
    );
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, "invalidateQueries");
    const { result } = renderHook(() => useRescan(), { wrapper: wrapperWith(qc) });

    await act(async () => {
      await result.current.start(false);
    });
    await waitFor(() => expect(result.current.status).toBe("done"));

    expect(spy).toHaveBeenCalledWith({ queryKey: ["rescan-state"] });
  });

  it("attaches to an already-running job instead of erroring, and reports already_running back", async () => {
    vi.spyOn(api, "rescanLibrary").mockResolvedValue({ job_id: "shared", already_running: true });
    vi.spyOn(api, "openJobStream").mockResolvedValue(
      streamOf([
        'event: progress\ndata: {"pct":80,"done":8,"total":10,"part_id":"midway","outcome":"updated"}\n\n',
        'event: result\ndata: {"result":{"total":10,"updated":8,"unchanged":2,"no_data":0,"failed":0,"paused_providers":[],"message":"Refreshed 8 of 10"}}\n\n',
        "event: done\ndata: {}\n\n",
      ]),
    );
    const qc = new QueryClient();
    const { result } = renderHook(() => useRescan(), { wrapper: wrapperWith(qc) });

    let started: { already_running: boolean } | undefined;
    await act(async () => {
      started = await result.current.start(false);
    });

    expect(started).toEqual({ already_running: true });
    await waitFor(() => expect(result.current.status).toBe("done"));
    expect(result.current.tally.total).toBe(10);
  });

  it("surfaces a job-stream error event as an error state", async () => {
    vi.spyOn(api, "rescanLibrary").mockResolvedValue({ job_id: "r4" });
    vi.spyOn(api, "openJobStream").mockResolvedValue(
      streamOf([
        'event: error\ndata: {"detail":"the engine crashed"}\n\n',
        "event: done\ndata: {}\n\n",
      ]),
    );
    const qc = new QueryClient();
    const { result } = renderHook(() => useRescan(), { wrapper: wrapperWith(qc) });

    await act(async () => {
      await result.current.start(false);
    });
    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.error).toBe("the engine crashed");
  });

  it("does not hang in running if the stream ends without a terminal event", async () => {
    vi.spyOn(api, "rescanLibrary").mockResolvedValue({ job_id: "r5" });
    vi.spyOn(api, "openJobStream").mockResolvedValue(
      streamOf(['event: progress\ndata: {"pct":30,"done":3,"total":10}\n\n']),
    );
    const qc = new QueryClient();
    const { result } = renderHook(() => useRescan(), { wrapper: wrapperWith(qc) });

    await act(async () => {
      await result.current.start(false);
    });
    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.error).toContain("without a result");
  });

  it("throws and surfaces an error state when the POST itself fails", async () => {
    vi.spyOn(api, "rescanLibrary").mockRejectedValue(new Error("connection refused"));
    const qc = new QueryClient();
    const { result } = renderHook(() => useRescan(), { wrapper: wrapperWith(qc) });

    await act(async () => {
      await expect(result.current.start(false)).rejects.toThrow("connection refused");
    });

    expect(result.current.status).toBe("error");
    expect(result.current.error).toBe("connection refused");
  });

  it("sends force=true through to the API when the caller asks for a full rescan", async () => {
    vi.spyOn(api, "rescanLibrary").mockResolvedValue({ job_id: "r6" });
    vi.spyOn(api, "openJobStream").mockResolvedValue(streamOf(["event: done\ndata: {}\n\n"]));
    const qc = new QueryClient();
    const { result } = renderHook(() => useRescan(), { wrapper: wrapperWith(qc) });

    await act(async () => {
      await result.current.start(true);
    });

    expect(api.rescanLibrary).toHaveBeenCalledWith(true);
  });
});
