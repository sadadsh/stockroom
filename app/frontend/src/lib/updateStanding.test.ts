import { describe, expect, it } from "vitest";
import {
  ADOPTION_STALL_MS,
  RESTART_GRACE_MS,
  aboutVersion,
  deriveUpdateStanding,
  runningVersion,
  shortRevision,
  staleFrontend,
  updateIdentity,
} from "./updateStanding";

describe("deriveUpdateStanding", () => {
  it("calls an install current only after a verified upstream comparison", () => {
    expect(
      deriveUpdateStanding({
        data: {
          update_available: false,
          state: "up_to_date",
          current_revision: "123456789abc",
          target_revision: "123456789abc",
        } as never,
        checking: false,
        failed: false,
      }),
    ).toMatchObject({
      standing: "current",
      currentRevision: "123456789abc",
      targetRevision: "123456789abc",
    });
  });

  it("does not translate a bare false into current", () => {
    expect(
      deriveUpdateStanding({
        data: { update_available: false },
        checking: false,
        failed: false,
      }).standing,
    ).toBe("unknown");
  });

  it("names an interrupted remote check as an automatic retry", () => {
    expect(
      deriveUpdateStanding({
        data: {
          update_available: false,
          state: "offline",
          current_revision: "123456789abc",
          detail: "network unavailable",
        },
        checking: false,
        failed: false,
      }),
    ).toMatchObject({
      standing: "retrying",
      currentRevision: "123456789abc",
      detail: "network unavailable",
    });
  });

  it("does not call a locally different revision current", () => {
    expect(
      deriveUpdateStanding({
        data: {
          update_available: false,
          state: "up_to_date",
          current_revision: "111111111111",
          target_revision: "222222222222",
        } as never,
        checking: false,
        failed: false,
      }).standing,
    ).toBe("unknown");
  });

  it("keeps the exact target when an update is available", () => {
    expect(
      deriveUpdateStanding({
        data: {
          update_available: true,
          state: "update_available",
          current_revision: "111111111111",
          target_revision: "222222222222",
        } as never,
        checking: false,
        failed: false,
      }),
    ).toMatchObject({
      standing: "available",
      currentRevision: "111111111111",
      targetRevision: "222222222222",
    });
  });

  it("names a verified staged release as ready", () => {
    expect(
      deriveUpdateStanding({
        data: {
          update_available: true,
          state: "ready",
          convergence_phase: "ready",
          current_release_id: "release-0.7.0.1",
          target_release_id: "release-0.7.0.2",
        },
        checking: false,
        failed: false,
      }),
    ).toMatchObject({
      standing: "ready",
      currentRevision: "release-0.7.0.1",
      targetRevision: "release-0.7.0.2",
    });
  });

  it("does not claim an available target it cannot identify", () => {
    expect(
      deriveUpdateStanding({
        data: {
          update_available: true,
          state: "update_available",
          current_revision: "111111111111",
        },
        checking: false,
        failed: false,
      }).standing,
    ).toBe("unknown");
  });

  it("reports checking before reusing a prior verified result", () => {
    expect(
      deriveUpdateStanding({
        data: {
          update_available: false,
          state: "up_to_date",
          current_revision: "111111111111",
          target_revision: "111111111111",
        } as never,
        checking: true,
        failed: false,
      }).standing,
    ).toBe("checking");
  });

  it("reports automatic adoption as updating instead of a waiting manual action", () => {
    expect(
      deriveUpdateStanding({
        data: {
          update_available: true,
          state: "updating",
          convergence_phase: "applying",
          current_revision: "111111111111",
          target_revision: "222222222222",
        } as never,
        checking: false,
        failed: false,
      }).standing,
    ).toBe("updating");
  });

  it("reads a lost backend during a restart as the restart it is, and only while it is young", () => {
    // C4: a real handoff KILLS the backend, so the check errors while the cached snapshot still
    // says the adoption is in flight. The failure branch used to be tested first and shadowed the
    // updating branch in exactly the case that branch exists for.
    const restarting = {
      update_available: true,
      state: "updating",
      convergence_phase: "handing_off",
      current_revision: "111111111111",
      target_revision: "222222222222",
    } as never;
    const at = (ms: number) =>
      deriveUpdateStanding({
        data: restarting,
        checking: false,
        failed: true,
        now: 1_000_000 + ms,
        failedSince: 1_000_000,
      });

    expect(at(0)).toMatchObject({
      standing: "updating",
      detail: "Stockroom is restarting to finish adopting a verified release.",
    });
    expect(at(RESTART_GRACE_MS - 1).standing).toBe("updating");
    // ...and once the backend has had every chance to come back, "Retrying" IS the honest word.
    expect(at(RESTART_GRACE_MS).standing).toBe("retrying");
    expect(at(RESTART_GRACE_MS * 10).standing).toBe("retrying");
  });

  it("does not extend the restart grace to a failure with nothing in flight", () => {
    expect(
      deriveUpdateStanding({
        data: {
          update_available: false,
          state: "up_to_date",
          current_revision: "111111111111",
          target_revision: "111111111111",
        } as never,
        checking: false,
        failed: true,
        now: 1_000_000,
        failedSince: 1_000_000,
      }).standing,
    ).toBe("retrying");
  });

  it("gives an adoption that never completes an exit instead of Updating forever", () => {
    // C6: nothing bounded the transitional phases, so a host that stalled held "Updating..." for
    // the life of the window with no manual escape anywhere in the UI.
    const applying = {
      update_available: true,
      state: "updating",
      convergence_phase: "applying",
      current_revision: "111111111111",
      target_revision: "222222222222",
      detail: "staging release",
    } as never;
    expect(
      deriveUpdateStanding({
        data: applying,
        checking: false,
        failed: false,
        now: 1_000_000 + ADOPTION_STALL_MS,
        phaseStartedAt: 1_000_000,
      }).standing,
    ).toBe("updating");

    const stalled = deriveUpdateStanding({
      data: applying,
      checking: false,
      failed: false,
      now: 1_000_000 + ADOPTION_STALL_MS + 1,
      phaseStartedAt: 1_000_000,
    });
    expect(stalled.standing).toBe("blocked");
    expect(stalled.detail).toContain("has not completed");
  });

  it("reports a bundle that never reloaded onto the backend's revision", () => {
    // C8: both readouts preferred the backend's revision, so a WebView2 bundle that missed its
    // reload showed the new revision confidently while running the old JavaScript.
    expect(
      deriveUpdateStanding({
        data: {
          update_available: false,
          state: "up_to_date",
          current_revision: "2222222222222",
          target_revision: "2222222222222",
          frontend_revision: "2222222222222",
        } as never,
        checking: false,
        failed: false,
        buildVersion: "0.1.0+1111111",
      }),
    ).toMatchObject({
      standing: "restart_required",
      detail:
        "This window is still running the 1111111 interface while the backend reports 2222222. " +
        "Restart Stockroom to finish adopting it.",
    });
  });

  it("does not confuse a committed bundle build with a stale window", () => {
    expect(
      deriveUpdateStanding({
        data: {
          update_available: false,
          state: "up_to_date",
          current_revision: "3333333333333",
          target_revision: "3333333333333",
          frontend_revision: "2222222222222",
        },
        checking: false,
        failed: false,
        buildVersion: "0.1.0+2222222",
      }).standing,
    ).toBe("current");
  });

  it("claims a mismatch only between identities that are comparable", () => {
    // The same short revision at two lengths is one revision, and a production release ID is not a
    // Git revision at all - "disagreeing" with either would be an invented fact, not a reported one.
    expect(staleFrontend({ update_available: false, frontend_revision: "1111111abc" }, "0.1.0+1111111")).toBeNull();
    expect(
      staleFrontend(
        { update_available: false, channel: "production", frontend_revision: "release-1.2.3.4" },
        "0.1.0+1111111",
      ),
    ).toBeNull();
    // No revision in the bundle (a plain package version) is no evidence either way.
    expect(staleFrontend({ update_available: false, frontend_revision: "222222222222" }, "0.1.0")).toBeNull();
    expect(staleFrontend({ update_available: false, current_revision: "222222222222" }, "0.1.0+1111111")).toBeNull();
    expect(staleFrontend({ update_available: false, frontend_revision: "222222222222" }, "0.1.0+1111111")).toEqual({
      bundle: "1111111",
      backend: "222222222222",
    });
  });

  it("does not call a stale frontend blocked or updating while an adoption is still running", () => {
    // The mismatch is EXPECTED mid-adoption: the backend has moved and the reload has not happened
    // yet. Only a settled backend makes the disagreement a standing of its own.
    expect(
      deriveUpdateStanding({
        data: {
          update_available: true,
          state: "updating",
          convergence_phase: "reloading_frontend",
          current_revision: "222222222222",
          target_revision: "222222222222",
        } as never,
        checking: false,
        failed: false,
        buildVersion: "0.1.0+1111111",
      }).standing,
    ).toBe("updating");
  });

  it("never presents failed or rolled-back adoption as update available", () => {
    for (const state of ["failed", "rolled_back"]) {
      expect(
        deriveUpdateStanding({
          data: {
            update_available: false,
            state,
            convergence_phase: state,
            current_revision: "111111111111",
            target_revision: "222222222222",
            detail: "automatic adoption did not complete",
          } as never,
          checking: false,
          failed: false,
        }),
      ).toMatchObject({
        standing: "blocked",
        targetRevision: "222222222222",
        detail: "automatic adoption did not complete",
      });
    }
  });
});

describe("revision labels", () => {
  it("uses compact Git revisions and falls back to the existing build version", () => {
    expect(shortRevision("123456789abc")).toBe("1234567");
    expect(shortRevision("release-1.2.3.4")).toBe("release-1.2.3.4");
    // CORRECTED (C8). This case used to expect "1234567" - the BACKEND's revision - from a bundle
    // built at aaaaaaa, which is the defect written down as an expectation: the running version is
    // whatever JavaScript is executing, and that is the bundle. The backend's revision is still
    // reported, next to it, under the `restart_required` standing that names the disagreement.
    expect(runningVersion("123456789abc", "0.1.0+aaaaaaa", true)).toEqual({
      value: "aaaaaaa",
      kind: "revision",
    });
    // A settled window reports the backend's Git/release identity; the content digest is a
    // different identity kind and wins only when the derived standing proves a stale window.
    expect(runningVersion("123456789abc", "0.1.0+aaaaaaa")).toEqual({
      value: "1234567",
      kind: "revision",
    });
    expect(runningVersion("", "0.1.0+abcdef123")).toEqual({
      value: "abcdef1",
      kind: "revision",
    });
    expect(runningVersion("", "0.1.0")).toEqual({
      value: "0.1.0",
      kind: "version",
    });
  });

  it("renders production release IDs as versions instead of truncated Git revisions", () => {
    expect(updateIdentity("release-1.2.3.4")).toEqual({
      value: "1.2.3.4",
      kind: "version",
    });
    expect(runningVersion("release-1.2.3.4", "0.1.0")).toEqual({
      value: "1.2.3.4",
      kind: "version",
    });
    expect(updateIdentity("release-candidate-blue")).toEqual({
      value: "release-candidate-blue",
      kind: "release",
    });
  });

  it("uses the authoritative production release in About and the build value in source mode", () => {
    expect(
      aboutVersion(
        {
          update_available: false,
          channel: "production",
          current_revision: "release-1.2.3.4",
        },
        "0.1.0+abcdef1",
      ),
    ).toBe("1.2.3.4");
    expect(
      aboutVersion(
        {
          update_available: false,
          channel: "main",
          current_revision: "abcdef123456",
        },
        "0.1.0+abcdef1",
      ),
    ).toBe("0.1.0+abcdef1");
  });
});
