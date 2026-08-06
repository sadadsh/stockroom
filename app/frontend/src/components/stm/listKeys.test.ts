import { describe, expect, it } from "vitest";
import { withStableKeys } from "./listKeys";

describe("withStableKeys", () => {
  it("keys each row on its own content, in input order", () => {
    const rows = withStableKeys(
      [
        { signal: "ADC1_IN0", io_modes: "Analog" },
        { signal: "WKUP1", io_modes: "" },
      ],
      (fn) => `${fn.signal}|${fn.io_modes}`,
    );
    expect(rows.map((r) => r.key)).toEqual(["ADC1_IN0|Analog", "WKUP1|"]);
    expect(rows.map((r) => r.item.signal)).toEqual(["ADC1_IN0", "WKUP1"]);
  });

  it("keeps a row's key across a reorder, which an array index would not", () => {
    const identity = (fn: { signal: string }) => fn.signal;
    const a = { signal: "SPI1_SCK" };
    const b = { signal: "I2C1_SCL" };
    const before = withStableKeys([a, b], identity);
    const after = withStableKeys([b, a], identity);
    expect(before[0].key).toBe(after[1].key);
    expect(before[1].key).toBe(after[0].key);
  });

  it("gives a byte-identical repeat an occurrence suffix so keys stay unique", () => {
    const rows = withStableKeys(
      [{ signal: "GPIO" }, { signal: "GPIO" }, { signal: "GPIO" }],
      (fn) => fn.signal,
    );
    expect(rows.map((r) => r.key)).toEqual(["GPIO", "GPIO#1", "GPIO#2"]);
    expect(new Set(rows.map((r) => r.key)).size).toBe(3);
  });
});
