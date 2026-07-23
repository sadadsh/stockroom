import { describe, expect, it, vi, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement, type ReactNode } from "react";
import {
  useStmStatus,
  useStmMcus,
  useStmFamilies,
  useStmPinout,
  useBuildStmIndex,
  useStmCompatUnion,
} from "./stmQueries";
import { api, ApiError } from "./client";
import type { McusResponse, PinoutDTO, StmStatusDTO, UnionDTO } from "./types";

const UNION: UnionDTO = {
  parts: ["STM32F407VETx"],
  resolved: [{ ref: "A", mpn: "STM32F407VETx" }],
  package: "LQFP100",
  family: "STM32F4",
  grain: "per-part",
  positions: [],
  verdict: { interchangeable: true, swaps_required: 0, blocking: [] },
};

const STATUS: StmStatusDTO = {
  built: true,
  building: false,
  source_path: "/cubemx/mcu",
  source_present: true,
  all_families: true,
  device_xml_count: 2204,
  family_count: 14,
  families: ["STM32F4"],
  mcu_count: 2204,
  classifier_rev: 1,
  af_schema_rev: 1,
  geometry_rev: 1,
  source_sha256: "abc",
  built_at: "2026-07-23T00:00:00Z",
};

const MCUS: McusResponse = {
  mcus: [],
  count: 0,
  facets: { family: {}, core: {}, package: {}, series: {} },
};

const PINOUT: PinoutDTO = {
  part: "STM32F407V(E-G)Tx",
  mpn_example: "STM32F407VETx",
  package: "LQFP100",
  geometry: {
    body_shape: "qfp",
    pin_count: 100,
    rows: null,
    cols: null,
    pitch_mm: 0.5,
    has_center_pad: false,
  },
  pins: [],
};

function wrapperWith(qc: QueryClient) {
  return ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children);
}

function freshClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

afterEach(() => vi.restoreAllMocks());

describe("STM query hooks", () => {
  it("useStmStatus reads api.getStmStatus", async () => {
    const spy = vi.spyOn(api, "getStmStatus").mockResolvedValue(STATUS);
    const { result } = renderHook(() => useStmStatus(), { wrapper: wrapperWith(freshClient()) });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(spy).toHaveBeenCalledTimes(1);
    expect(result.current.data?.mcu_count).toBe(2204);
  });

  it("useStmMcus calls api.getStmMcus with the scope and refetches when it changes", async () => {
    const spy = vi.spyOn(api, "getStmMcus").mockResolvedValue(MCUS);
    const qc = freshClient();
    const { result, rerender } = renderHook((scope: { family?: string }) => useStmMcus(scope), {
      wrapper: wrapperWith(qc),
      initialProps: { family: "STM32F4" },
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(spy).toHaveBeenLastCalledWith({ family: "STM32F4" });

    rerender({ family: "STM32H7" });
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
    expect(spy).toHaveBeenLastCalledWith({ family: "STM32H7" });
  });

  it("useStmFamilies reads api.getStmFamilies", async () => {
    const spy = vi.spyOn(api, "getStmFamilies").mockResolvedValue({ families: [] });
    const { result } = renderHook(() => useStmFamilies(), { wrapper: wrapperWith(freshClient()) });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("useStmPinout is disabled until a part is set, then loads it", async () => {
    const spy = vi.spyOn(api, "getStmPinout").mockResolvedValue(PINOUT);
    const qc = freshClient();
    const { result, rerender } = renderHook((part: string | null) => useStmPinout(part), {
      wrapper: wrapperWith(qc),
      initialProps: null as string | null,
    });
    // no part -> disabled -> no fetch
    expect(spy).not.toHaveBeenCalled();
    expect(result.current.fetchStatus).toBe("idle");

    rerender("STM32F407V(E-G)Tx");
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(spy).toHaveBeenCalledWith("STM32F407V(E-G)Tx");
  });

  it("a 409 surfaces on the query as an ApiError the page can branch on", async () => {
    vi.spyOn(api, "getStmMcus").mockRejectedValue(new ApiError(409, "STM index not built"));
    const { result } = renderHook(() => useStmMcus(), { wrapper: wrapperWith(freshClient()) });
    await waitFor(() => expect(result.current.isError).toBe(true));
    const err = result.current.error;
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(409);
  });

  it("useBuildStmIndex starts a job over api.buildStmIndex", async () => {
    const buildSpy = vi.spyOn(api, "buildStmIndex").mockResolvedValue({ job_id: "job-7" });
    // the job then opens an SSE stream; stub it to end immediately so the hook settles
    vi.spyOn(api, "openJobStream").mockRejectedValue(new Error("stream closed in test"));
    const { result } = renderHook(() => useBuildStmIndex(), { wrapper: wrapperWith(freshClient()) });
    result.current.start();
    await waitFor(() => expect(buildSpy).toHaveBeenCalledTimes(1));
  });

  it("useStmCompatUnion posts a (family, package) group body and resolves the UnionDTO", async () => {
    const spy = vi.spyOn(api, "postStmCompatUnion").mockResolvedValue(UNION);
    const { result } = renderHook(() => useStmCompatUnion(), { wrapper: wrapperWith(freshClient()) });
    result.current.mutate({ family: "STM32F4", package: "LQFP100" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(spy).toHaveBeenCalledWith({ family: "STM32F4", package: "LQFP100" });
    expect(result.current.data?.verdict.interchangeable).toBe(true);
  });

  it("useStmCompatUnion also accepts an explicit ref-list body (both input shapes)", async () => {
    const spy = vi.spyOn(api, "postStmCompatUnion").mockResolvedValue(UNION);
    const { result } = renderHook(() => useStmCompatUnion(), { wrapper: wrapperWith(freshClient()) });
    result.current.mutate({ parts: ["STM32F407VETx", "STM32F407VGTx"] });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(spy).toHaveBeenCalledWith({ parts: ["STM32F407VETx", "STM32F407VGTx"] });
  });

  it("useStmCompatUnion surfaces a 409 as an ApiError the workbench can branch on", async () => {
    vi.spyOn(api, "postStmCompatUnion").mockRejectedValue(new ApiError(409, "STM index not built"));
    const { result } = renderHook(() => useStmCompatUnion(), { wrapper: wrapperWith(freshClient()) });
    result.current.mutate({ family: "STM32F4", package: "LQFP100" });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect((result.current.error as ApiError).status).toBe(409);
  });
});
