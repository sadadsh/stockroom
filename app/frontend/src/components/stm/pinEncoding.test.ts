import { describe, expect, it } from "vitest";
import { PIN_CATEGORIES, categoryFill, categoryLabel } from "./pinEncoding";

describe("pinEncoding categories", () => {
  it("covers the API's full ten-bucket category vocabulary", () => {
    expect(PIN_CATEGORIES.map((c) => c.key)).toEqual([
      "gpio",
      "analog",
      "debug",
      "oscillator",
      "power",
      "ground",
      "reset",
      "boot",
      "vcap",
      "nc",
    ]);
  });

  it("maps each known category to its own token", () => {
    expect(categoryFill("analog")).toBe("var(--stm-cat-analog)");
    expect(categoryFill("gpio")).toBe("var(--stm-cat-gpio)");
    expect(categoryFill("nc")).toBe("var(--stm-cat-nc)");
    expect(categoryLabel("oscillator")).toBe("Oscillator");
    expect(categoryLabel("nc")).toBe("Not Connected");
  });

  it("reads a raw io electrical class as plain gpio", () => {
    expect(categoryFill("io")).toBe("var(--stm-cat-gpio)");
    expect(categoryLabel("io")).toBe("GPIO");
  });

  it("never masks an unknown category as Not Connected", () => {
    // the regression that painted analog-capable PA1 as a "Not Connected" pin
    expect(categoryFill("someday-new")).toBe("var(--c-line2)");
    expect(categoryLabel("someday-new")).toBe("Someday-new");
    expect(categoryLabel("")).toBe("Unknown");
  });
});
