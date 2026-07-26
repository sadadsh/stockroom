import { describe, expect, it } from "vitest";

import { counted, plural } from "./plural";

describe("counted nouns agree with their number", () => {
  // The status bar read "1 Components" on 10 of the 12 captured screens.
  it("is singular at exactly one", () => {
    expect(plural(1, "Component")).toBe("Component");
    expect(counted(1, "Component")).toBe("1 Component");
  });

  it("is plural at zero and at many", () => {
    // Zero takes the plural in English ("0 Components"), which is the case a naive
    // `count > 1 ? plural : singular` gets wrong.
    expect(counted(0, "Component")).toBe("0 Components");
    expect(counted(2, "Component")).toBe("2 Components");
  });

  it("takes an explicit irregular plural rather than guessing", () => {
    expect(counted(2, "Property", "Properties")).toBe("2 Properties");
    expect(counted(1, "Property", "Properties")).toBe("1 Property");
  });

  it("groups a large count, so it does not read as a part number", () => {
    expect(counted(1204, "Component")).toBe("1,204 Components");
  });
});
