import { statusTone, type StatusTone } from "./statusTone";

const KNOWN_TOKENS = ["--c-ok", "--c-warn", "--c-err", "--c-acc", "--c-t3"];

function assertTokenBacked(t: StatusTone) {
  // every tone references a design token, never a raw hex literal that bypasses theming
  expect(KNOWN_TOKENS).toContain(t.token);
  expect(t.text.startsWith("text-")).toBe(true);
  expect(t.className).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
}

describe("statusTone", () => {
  it("maps ahead and behind to their status roles", () => {
    expect(statusTone("ahead").role).toBe("info");
    expect(statusTone("behind").role).toBe("warn");
  });

  it("maps a dirty/uncommitted tree to a warn tone", () => {
    expect(statusTone("uncommitted").role).toBe("warn");
    expect(statusTone("dirty").role).toBe("warn");
  });

  it("maps update-available to an accent/attention tone", () => {
    expect(statusTone("update-available").role).toBe("accent");
  });

  it("maps up-to-date to an ok tone", () => {
    expect(statusTone("up-to-date").role).toBe("ok");
  });

  it("returns a neutral tone for an unknown or empty kind", () => {
    expect(statusTone("something-else").role).toBe("neutral");
    expect(statusTone("").role).toBe("neutral");
  });

  it("is total and every tone is token-backed (no raw hex)", () => {
    for (const kind of [
      "ahead",
      "behind",
      "uncommitted",
      "dirty",
      "update-available",
      "up-to-date",
      "mystery",
      "",
    ]) {
      assertTokenBacked(statusTone(kind));
    }
  });
});
