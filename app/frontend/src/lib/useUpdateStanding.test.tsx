import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { UpdateCheck } from "../api/types";
import { ADOPTION_STALL_MS, RESTART_GRACE_MS } from "./updateStanding";
import { resetUpdateClocksForTests, useUpdateStanding } from "./useUpdateStanding";

// The query itself is not under test here - the CLOCKS are, and React Query's own timestamps
// cannot keep them (it rewrites `dataUpdatedAt` on every successful poll and `errorUpdatedAt` on
// every failed one, so neither measures a streak).
const query: { data: UpdateCheck | undefined; isPending: boolean; isFetching: boolean; isError: boolean } =
  { data: undefined, isPending: false, isFetching: false, isError: false };
vi.mock("../api/queries", () => ({
  useUpdateCheck: () => query,
}));

// A build version with no embedded revision: a bundle that carries none cannot disagree with the
// backend, so the stale-frontend rule stays out of the way of the timing being asserted here.
const BUILD = "0.1.0";
const RESTARTING = {
  update_available: true,
  state: "updating",
  convergence_phase: "handing_off",
  current_revision: "111111111111",
  target_revision: "222222222222",
} as UpdateCheck;

function at(ms: number) {
  vi.spyOn(Date, "now").mockReturnValue(ms);
}

describe("useUpdateStanding", () => {
  beforeEach(() => {
    resetUpdateClocksForTests();
    query.data = undefined;
    query.isPending = false;
    query.isFetching = false;
    query.isError = false;
  });

  it("holds a healthy restart as updating, then tells the truth about a backend that never returns", () => {
    // C4. The backend dies during a handoff, so the check errors while the cached snapshot still
    // says the adoption is in flight. That window is bounded rather than trusted forever.
    query.data = RESTARTING;
    query.isError = true;
    at(1_000_000);
    const { result, rerender } = renderHook(() => useUpdateStanding(BUILD));
    expect(result.current.view.standing).toBe("updating");

    at(1_000_000 + RESTART_GRACE_MS - 1);
    rerender();
    expect(result.current.view.standing).toBe("updating");

    at(1_000_000 + RESTART_GRACE_MS);
    rerender();
    expect(result.current.view.standing).toBe("retrying");
  });

  it("restarts the failure clock once the backend answers again", () => {
    query.data = RESTARTING;
    query.isError = true;
    at(1_000_000);
    const { result, rerender } = renderHook(() => useUpdateStanding(BUILD));
    at(1_000_000 + RESTART_GRACE_MS);
    rerender();
    expect(result.current.view.standing).toBe("retrying");

    // The backend came back mid-adoption. A later handoff is a NEW failure, not a continuation of
    // the old streak, so it gets its own grace window rather than inheriting an expired one.
    query.isError = false;
    rerender();
    query.isError = true;
    at(1_000_000 + RESTART_GRACE_MS + 1);
    rerender();
    expect(result.current.view.standing).toBe("updating");
  });

  it("times ONE adoption, not one phase, and stops saying Updating when it never lands", () => {
    // C6. The clock is keyed by what is being adopted: applying -> handing_off is progress on the
    // same adoption, so an advancing phase must not buy the host another full window.
    query.data = { ...RESTARTING, convergence_phase: "applying" };
    at(1_000_000);
    const { result, rerender } = renderHook(() => useUpdateStanding(BUILD));
    expect(result.current.view.standing).toBe("updating");

    query.data = { ...RESTARTING, convergence_phase: "handing_off" };
    at(1_000_000 + ADOPTION_STALL_MS + 1);
    rerender();
    expect(result.current.view.standing).toBe("blocked");
    expect(result.current.view.detail).toContain("has not completed");
  });

  it("does not report a settled standing as unknown-yet on every background refetch", () => {
    // C5. `isFetching` is true on each 5s poll and on every window focus, so passing it as
    // `checking` flickered a settled pill to "Checking..." constantly. Only "no answer has ever
    // landed" is genuinely unknown.
    query.data = {
      update_available: false,
      state: "up_to_date",
      current_revision: "111111111111",
      target_revision: "111111111111",
    } as UpdateCheck;
    query.isFetching = true;
    at(1_000_000);
    const { result, rerender } = renderHook(() => useUpdateStanding(BUILD));
    expect(result.current.view.standing).toBe("current");

    query.data = undefined;
    query.isPending = true;
    rerender();
    expect(result.current.view.standing).toBe("checking");
  });
});
