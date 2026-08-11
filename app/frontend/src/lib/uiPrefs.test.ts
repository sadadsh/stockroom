/**
 * The preference store, and the one invariant that keeps it honest: EVERY PREFERENCE IS A SCALAR.
 *
 * The mirror is `localStorage`, which stores strings, and `writePref` writes it with a bare
 * `String(value)`. An object-valued preference would mirror as the literal "[object Object]", parse
 * back as undefined on the next launch, and silently lose whatever it held. `pinned_specs` was such
 * a member - declared on `UiPrefs`, read by nothing, written by nothing, and carrying with it a
 * JSON-encoding branch in `writePref` that existed only because the member did. Both were removed
 * together, and this gate is what stops half of that pair coming back without the other:
 *
 *   - a non-scalar member added to `UiPrefs` fails the first test, which reads the declaration; and
 *   - the encoder that would be needed to support one is asserted absent, so re-adding the member
 *     alone cannot quietly reuse a branch nothing else can reach.
 *
 * The declaration is read as raw source rather than reflected off the type, because a TypeScript
 * interface leaves nothing behind at runtime to reflect. Same technique, and same reason, as
 * `statusVocabulary.test.ts` and `devIds.parity.test.ts`: `node:fs` breaks `tsc -b`, which
 * type-checks this file too.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { injectedPrefs, readPref, writePref } from "./uiPrefs";

const RAW = import.meta.glob("/src/lib/*.ts", {
  query: "?raw",
  eager: true,
  import: "default",
}) as Record<string, string>;

const SOURCE = RAW["/src/lib/uiPrefs.ts"];

/** One `name?: type;` line of the interface body. */
interface Member {
  readonly name: string;
  readonly type: string;
}

function declaredMembers(): readonly Member[] {
  const body = /export interface UiPrefs \{([\s\S]*?)\n\}/.exec(SOURCE ?? "")?.[1] ?? "";
  return [...body.matchAll(/^\s*([A-Za-z_][\w]*)\??:\s*([^;]+);/gm)].map((m) => ({
    name: m[1],
    type: m[2].trim(),
  }));
}

/** A type `String(value)` round-trips: a primitive, or a union of primitives and string literals. */
function isScalarType(type: string): boolean {
  return type
    .split("|")
    .map((part) => part.trim())
    .every((part) => /^(?:string|number|boolean|true|false|"[^"]*"|'[^']*'|-?\d+(?:\.\d+)?)$/.test(part));
}

describe("the shape of UiPrefs", () => {
  it("reads the declaration (the glob and the pattern are wired)", () => {
    // A silently-empty glob or a renamed interface would turn the assertion below into a false pass.
    expect(SOURCE).toBeTruthy();
    expect(declaredMembers().map((m) => m.name)).toEqual([
      "theme",
      "rail_collapsed",
      "design_studio_left_collapsed",
      "design_studio_right_collapsed",
      "design_studio_left_width",
      "design_studio_right_width",
    ]);
  });

  it("declares only scalar preferences, because the mirror can hold nothing else", () => {
    const structured = declaredMembers()
      .filter((m) => !isScalarType(m.type))
      .map((m) => `${m.name}: ${m.type}`);
    expect(structured).toEqual([]);
  });

  it("keeps no encoder for a preference the type cannot hold", () => {
    // The other half of the pair. `pinned_specs` was removed and its JSON branch with it; a branch
    // left behind, commented with the name of a member that no longer exists, is dead code that
    // reads as a live contract. A preference that genuinely needs structure brings its own
    // encode/decode pair AND its own round-trip test - it does not inherit this one.
    expect(SOURCE).not.toMatch(/JSON\.(?:stringify|parse)/);
  });
});

describe("reading and writing one preference", () => {
  beforeEach(() => {
    localStorage.clear();
    // The host injects the machine config into the page at boot, so the injected copy is part of
    // the slate a test has to reset. See lib/uiPrefs.ts.
    window.__STOCKROOM_UI__ = {};
  });

  const parseTheme = (raw: string) => (raw === "light" || raw === "dark" ? raw : undefined);

  it("prefers the host injection over the mirror", () => {
    localStorage.setItem("sr-theme", "dark");
    window.__STOCKROOM_UI__ = { theme: "light" };
    expect(readPref("theme", "sr-theme", parseTheme, "dark")).toBe("light");
  });

  it("falls back to the mirror, then to the given default", () => {
    localStorage.setItem("sr-theme", "light");
    expect(readPref("theme", "sr-theme", parseTheme, "dark")).toBe("light");
    localStorage.clear();
    expect(readPref("theme", "sr-theme", parseTheme, "dark")).toBe("dark");
  });

  it("mirrors each scalar in its bare string form, and keeps the injected copy current", () => {
    writePref("theme", "light", "sr-theme");
    expect(localStorage.getItem("sr-theme")).toBe("light");
    expect(injectedPrefs().theme).toBe("light");

    writePref("rail_collapsed", true, "sr-rail");
    expect(localStorage.getItem("sr-rail")).toBe("true");
    expect(injectedPrefs().rail_collapsed).toBe(true);
  });

  it("does nothing at all when the value already matches", () => {
    window.__STOCKROOM_UI__ = { theme: "light" };
    writePref("theme", "light", "sr-theme");
    expect(localStorage.getItem("sr-theme")).toBeNull();
  });
});
