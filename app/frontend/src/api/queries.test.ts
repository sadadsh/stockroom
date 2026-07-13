import { describe, expect, it, vi, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement, type ReactNode } from "react";
import {
  useActivateProfile,
  useDeletePart,
  useEditField,
  useDoSync,
} from "./queries";
import { api } from "./client";
import type { PartDetail } from "./types";

const PART_DETAIL: PartDetail = {
  id: "lm358",
  display_name: "LM358",
  category: "ICs",
  description: "",
  tags: [],
  mpn: "LM358DR",
  manufacturer: "TI",
  datasheet: null,
  purchase: [],
  symbol: null,
  footprint: null,
  model: null,
  provenance: null,
  hashes: null,
  enrichment: {},
};

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

describe("duplicates invalidation (M6e)", () => {
  // The Duplicates page deletes a member and expects that surface to refresh
  // itself, else the resolved duplicate lingers on screen. Lock the invalidation
  // so a delete can never silently leave a stale group behind.
  it("deleting a part refreshes the duplicates surface", async () => {
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, "invalidateQueries");
    vi.spyOn(api, "deletePart").mockResolvedValue(undefined);

    const { result } = renderHook(() => useDeletePart(), {
      wrapper: wrapperWith(qc),
    });
    result.current.mutate("lm358");
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(invalidatedKeys(spy)).toContain("duplicates");
  });

  // Editing an MPN can change which parts share it, so an edit must refresh the
  // surface too (locks the shared useInvalidateAfterWrite path).
  it("editing a field refreshes the duplicates surface", async () => {
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, "invalidateQueries");
    vi.spyOn(api, "editField").mockResolvedValue(PART_DETAIL);

    const { result } = renderHook(() => useEditField(), {
      wrapper: wrapperWith(qc),
    });
    result.current.mutate({ id: "lm358", field: "mpn", value: "NEW-MPN" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(invalidatedKeys(spy)).toContain("duplicates");
  });
});
