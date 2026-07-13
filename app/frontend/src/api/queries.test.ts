import { describe, expect, it, vi, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement, type ReactNode } from "react";
import { useActivateProfile, useDoSync } from "./queries";
import { api } from "./client";

function wrapperWith(qc: QueryClient) {
  return ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children);
}

function invalidatedKeys(spy: { mock: { calls: unknown[][] } }): string[] {
  return spy.mock.calls.map(
    (c) => (c[0] as { queryKey: string[] }).queryKey[0],
  );
}

afterEach(() => vi.restoreAllMocks());

describe("profile + sync invalidation", () => {
  it("activating a profile refreshes the parts, facets, profiles and system views", async () => {
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, "invalidateQueries");
    vi.spyOn(api, "activateProfile").mockResolvedValue({
      active: "Archive",
      part_count: 0,
    });

    const { result } = renderHook(() => useActivateProfile(), {
      wrapper: wrapperWith(qc),
    });
    result.current.mutate("Archive");
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(invalidatedKeys(spy)).toEqual(
      expect.arrayContaining(["parts", "facets", "profiles", "system"]),
    );
  });

  it("a sync that pulled refreshes the parts and facets", async () => {
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, "invalidateQueries");
    vi.spyOn(api, "doSync").mockResolvedValue({
      state: "synced",
      pulled: true,
      pushed: false,
      detail: "",
    });

    const { result } = renderHook(() => useDoSync(), { wrapper: wrapperWith(qc) });
    result.current.mutate();
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(invalidatedKeys(spy)).toEqual(
      expect.arrayContaining(["parts", "facets"]),
    );
  });

  it("a no-op sync does not churn the parts view", async () => {
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, "invalidateQueries");
    vi.spyOn(api, "doSync").mockResolvedValue({
      state: "up_to_date",
      pulled: false,
      pushed: false,
      detail: "",
    });

    const { result } = renderHook(() => useDoSync(), { wrapper: wrapperWith(qc) });
    result.current.mutate();
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(invalidatedKeys(spy)).not.toContain("parts");
  });
});
