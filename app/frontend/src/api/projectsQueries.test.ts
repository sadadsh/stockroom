import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { useActiveAssembly, useRecordAssemblyEvent } from "./queries";
import type { AssemblyEvent, AssemblyRun } from "./types";

function wrapperWith(client: QueryClient) {
  return ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client }, children);
}

function runWith(state: "pending" | "done"): AssemblyRun {
  const event: AssemblyEvent | null =
    state === "done"
      ? {
          id: "event-1",
          sequence: 1,
          run_id: "run-1",
          placement_id: "placement-1",
          state: "done",
          scanned_mpn: "RC0402FR-0710KL",
          note: "",
          recorded_at: "2026-07-29T22:00:00Z",
        }
      : null;
  return {
    schema_version: 1,
    id: "run-1",
    project_id: "power-board",
    project_name: "Power Board",
    eda: "kicad",
    operator: "Sadad",
    boards: 1,
    source_commit: "0123456789abcdef",
    project_digest: "digest",
    started_at: "2026-07-29T21:59:00Z",
    completed_at: "",
    status: "active",
    placements: [
      {
        placement_id: "placement-1",
        board_index: 1,
        native_id: "native-r1",
        reference: "R1",
        sheet: "Power.kicad_sch",
        value: "10k",
        footprint: "R_0402",
        part_id: "resistor-10k",
        mpn: "RC0402FR-0710KL",
        manufacturer: "Yageo",
        state,
        last_event: event,
      },
    ],
    events: event ? [event] : [],
    progress: {
      total: 1,
      complete: state === "done" ? 1 : 0,
      resolved: state === "done" ? 1 : 0,
      percent: state === "done" ? 100 : 0,
      counts: {
        pending: state === "pending" ? 1 : 0,
        done: state === "done" ? 1 : 0,
        skipped: 0,
        reworked: 0,
        issue: 0,
      },
    },
  };
}

afterEach(() => vi.restoreAllMocks());

describe("shared assembly state", () => {
  it("updates the operator immediately and reaches a second client on its next poll", async () => {
    let serverRun = runWith("pending");
    vi.spyOn(api, "activeAssembly").mockImplementation(async () => serverRun);
    vi.spyOn(api, "recordAssemblyEvent").mockImplementation(async () => {
      serverRun = runWith("done");
      return serverRun;
    });
    const operatorClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const observerClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const operator = renderHook(() => useActiveAssembly("power-board"), {
      wrapper: wrapperWith(operatorClient),
    });
    const observer = renderHook(() => useActiveAssembly("power-board"), {
      wrapper: wrapperWith(observerClient),
    });
    const record = renderHook(() => useRecordAssemblyEvent("power-board"), {
      wrapper: wrapperWith(operatorClient),
    });

    await waitFor(() => {
      expect(operator.result.current.data?.placements[0].state).toBe("pending");
      expect(observer.result.current.data?.placements[0].state).toBe("pending");
    });

    act(() => {
      record.result.current.mutate({
        runId: "run-1",
        placementId: "placement-1",
        state: "done",
        scannedMpn: "RC0402FR-0710KL",
      });
    });
    await waitFor(() =>
      expect(operator.result.current.data?.placements[0].state).toBe("done"),
    );
    expect(observer.result.current.data?.placements[0].state).toBe("pending");

    await act(async () => {
      await observer.result.current.refetch();
    });
    await waitFor(() =>
      expect(observer.result.current.data?.placements[0].state).toBe("done"),
    );

    operator.unmount();
    observer.unmount();
    record.unmount();
    operatorClient.clear();
    observerClient.clear();
  });
});
