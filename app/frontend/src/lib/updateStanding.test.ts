import { describe, expect, it } from "vitest";
import {
  deriveUpdateStanding,
  runningVersion,
  shortRevision,
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
});

describe("revision labels", () => {
  it("uses compact Git revisions and falls back to the existing build version", () => {
    expect(shortRevision("123456789abc")).toBe("1234567");
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
});
