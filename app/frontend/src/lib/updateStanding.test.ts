import { describe, expect, it } from "vitest";
import {
  aboutVersion,
  deriveUpdateStanding,
  runningVersion,
  shortRevision,
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

  it("does not translate a bare false or an offline result into current", () => {
    for (const data of [
      { update_available: false },
      {
        update_available: false,
        state: "offline",
        current_revision: "123456789abc",
        detail: "network unavailable",
      },
    ]) {
      expect(
        deriveUpdateStanding({
          data,
          checking: false,
          failed: false,
        }).standing,
      ).toBe("unknown");
    }
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
        standing: "unknown",
        targetRevision: "",
        detail: "automatic adoption did not complete",
      });
    }
  });
});

describe("revision labels", () => {
  it("uses compact Git revisions and falls back to the existing build version", () => {
    expect(shortRevision("123456789abc")).toBe("1234567");
    expect(shortRevision("release-1.2.3.4")).toBe("release-1.2.3.4");
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
