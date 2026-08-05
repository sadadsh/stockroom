/**
 * The typesetting rules for values, each pinned to the reason it exists. Every case here is a
 * string a reader would otherwise have to decode: a unit that wrapped away from its number, a
 * hyphen pretending to be a range, a hyphen-minus that made a column of negatives look ragged, a
 * float artefact, or a relative time with no absolute time behind it.
 */
import { describe, expect, it } from "vitest";
import {
  EN_DASH,
  MINUS,
  NBSP,
  alignmentFor,
  formatCount,
  formatDate,
  formatDateTime,
  formatEngineeringValue,
  formatNumber,
  formatPrice,
  formatQuantity,
  formatRange,
  formatRelativeTime,
  formatTimestamp,
  isTabular,
} from "./formatValue";

describe("the separators are the real characters", () => {
  it("uses U+00A0, U+2013 and U+2212, not the ASCII lookalikes", () => {
    expect(NBSP.codePointAt(0)).toBe(0x00a0);
    expect(EN_DASH.codePointAt(0)).toBe(0x2013);
    expect(MINUS.codePointAt(0)).toBe(0x2212);
  });
});

describe("formatNumber", () => {
  it("keeps a string's authored precision, because a datasheet meant it", () => {
    // "3.30" says three significant figures. Trimming it states a different measurement.
    expect(formatNumber("3.30")).toBe("3.30");
    expect(formatNumber("0.100")).toBe("0.100");
  });

  it("trims the trailing zeros a float leaves behind", () => {
    expect(formatNumber(3.3)).toBe("3.3");
    expect(formatNumber(5)).toBe("5");
    expect(formatNumber(2.5000000001)).toBe("2.5");
  });

  it("uses the real minus, which lines up with the digits beside it", () => {
    expect(formatNumber(-40)).toBe(`${MINUS}40`);
    expect(formatNumber("-40.5")).toBe(`${MINUS}40.5`);
    // An already-typeset value passes through unchanged rather than being double-converted.
    expect(formatNumber(`${MINUS}40`)).toBe(`${MINUS}40`);
  });

  it("never renders a negative zero", () => {
    expect(formatNumber(-0.4, { maxDecimals: 0 })).toBe("0");
  });

  it("normalises the two spellings that read as typos, and nothing else", () => {
    expect(formatNumber("+5")).toBe("5");
    expect(formatNumber(".5")).toBe("0.5");
    expect(formatNumber("-.5")).toBe(`${MINUS}0.5`);
  });

  it("groups thousands only when asked", () => {
    expect(formatNumber(12400)).toBe("12400");
    expect(formatNumber(12400, { grouping: true })).toBe("12,400");
    expect(formatNumber(-1234567.5, { grouping: true })).toBe(`${MINUS}1,234,567.5`);
  });

  it("returns nothing for a value that is not a number, rather than throwing", () => {
    // A bad field in one row must not blank a screen.
    expect(formatNumber(Number.NaN)).toBe("");
    expect(formatNumber(Number.POSITIVE_INFINITY)).toBe("");
    expect(formatNumber("n/a")).toBe("");
    expect(formatNumber("")).toBe("");
  });
});

describe("formatQuantity", () => {
  it("binds the unit to the number with a non-breaking space", () => {
    expect(formatQuantity(3.3, "V")).toBe(`3.3${NBSP}V`);
    expect(formatQuantity("100", "nF")).toBe(`100${NBSP}nF`);
    // The gap is genuinely unbreakable, so "3.3" and "V" can never land on separate lines.
    expect(formatQuantity(3.3, "V")).not.toContain(" ");
  });

  it("attaches the units that convention writes tight", () => {
    expect(formatQuantity(40, "%")).toBe("40%");
  });

  it("returns the bare number when there is no unit, so callers need no branch", () => {
    expect(formatQuantity(12)).toBe("12");
    expect(formatQuantity(12, "")).toBe("12");
    expect(formatQuantity(12, null)).toBe("12");
  });
});

describe("formatRange", () => {
  it("states the unit once, after the range", () => {
    expect(formatRange(1.65, 5.5, "V")).toBe(`1.65${EN_DASH}5.5${NBSP}V`);
  });

  it("joins the endpoints with an en dash and no spaces, so it reads as one value", () => {
    expect(formatRange(1.65, 5.5, "V")).toContain(EN_DASH);
    expect(formatRange(1.65, 5.5, "V")).not.toContain("-");
    expect(formatRange(1.65, 5.5, "V")).not.toContain(` ${EN_DASH} `);
  });

  it("uses the real minus on a negative endpoint", () => {
    expect(formatRange(-40, 125, "°C")).toBe(
      `${MINUS}40${EN_DASH}125${NBSP}°C`,
    );
  });

  it("collapses a degenerate range to the single quantity it actually is", () => {
    expect(formatRange(5, 5, "V")).toBe(`5${NBSP}V`);
  });

  it("falls back to the endpoint it has when the other is missing", () => {
    expect(formatRange("", 5.5, "V")).toBe(`5.5${NBSP}V`);
    expect(formatRange(1.65, Number.NaN, "V")).toBe(`1.65${NBSP}V`);
    expect(formatRange("", "", "V")).toBe("");
  });

  it("preserves authored precision on both endpoints", () => {
    expect(formatRange("2.70", "3.60", "V")).toBe(`2.70${EN_DASH}3.60${NBSP}V`);
  });
});

describe("formatPrice", () => {
  it("holds two decimals, because $1.2 is a typo and $1.20 is a price", () => {
    expect(formatPrice(1.2)).toBe("$1.20");
    expect(formatPrice(5)).toBe("$5.00");
  });

  it("keeps the extra places a volume break is genuinely quoted at", () => {
    expect(formatPrice(0.00412)).toBe("$0.00412");
  });

  it("groups thousands and uses the real minus on a credit", () => {
    expect(formatPrice(12400.5)).toBe("$12,400.50");
    expect(formatPrice(-3.5)).toBe(`${MINUS}$3.50`);
  });

  it("returns nothing for a non-price", () => {
    expect(formatPrice(Number.NaN)).toBe("");
  });
});

describe("formatCount", () => {
  it("groups a stock figure and never renders a fraction of a part", () => {
    expect(formatCount(1240)).toBe("1,240");
    expect(formatCount(12)).toBe("12");
    expect(formatCount(1240.7)).toBe("1,240");
  });
});

describe("dates have one format", () => {
  // Built from local components so the expectation is timezone-independent.
  const when = new Date(2026, 7, 5, 10, 42);

  it("renders the one absolute form: Aug 5, 2026, 10:42 AM", () => {
    expect(formatDateTime(when)).toBe("Aug 5, 2026, 10:42 AM");
  });

  it("uses a plain ASCII space before the meridiem, not the narrow no-break space ICU emits", () => {
    // Intl's output for these options changed shape across ICU versions (U+202F), which is
    // invisible in a diff and breaks every comparison. That is why this is hand-built.
    expect(formatDateTime(when)).not.toMatch(/ /);
  });

  it("renders noon and midnight the way a clock does", () => {
    expect(formatDateTime(new Date(2026, 7, 5, 12, 0))).toBe("Aug 5, 2026, 12:00 PM");
    expect(formatDateTime(new Date(2026, 7, 5, 0, 5))).toBe("Aug 5, 2026, 12:05 AM");
  });

  it("pads the minute and never the day", () => {
    expect(formatDateTime(new Date(2026, 7, 5, 9, 7))).toBe("Aug 5, 2026, 9:07 AM");
  });

  it("offers the date alone in the same vocabulary", () => {
    expect(formatDate(when)).toBe("Aug 5, 2026");
  });

  it("returns nothing for an unparseable date", () => {
    expect(formatDateTime("not a date")).toBe("");
    expect(formatDate(Number.NaN)).toBe("");
  });
});

describe("relative time is only ever half of a timestamp", () => {
  const now = new Date(2026, 7, 5, 12, 0);

  it("counts up through the units a person tracks", () => {
    expect(formatRelativeTime(new Date(2026, 7, 5, 11, 59, 30), now)).toBe("just now");
    expect(formatRelativeTime(new Date(2026, 7, 5, 11, 56), now)).toBe(`4${NBSP}min ago`);
    expect(formatRelativeTime(new Date(2026, 7, 5, 9, 0), now)).toBe(`3${NBSP}h ago`);
    expect(formatRelativeTime(new Date(2026, 7, 3, 12, 0), now)).toBe(`2${NBSP}d ago`);
  });

  it("gives up past a week, because '37 d ago' is not a date anyone can recover", () => {
    expect(formatRelativeTime(new Date(2026, 6, 1, 10, 42), now)).toBe("Jul 1, 2026, 10:42 AM");
  });

  it("shows a future time absolutely rather than counting backwards", () => {
    expect(formatRelativeTime(new Date(2026, 7, 6, 9, 30), now)).toBe("Aug 6, 2026, 9:30 AM");
  });

  it("returns the relative text and the absolute tooltip TOGETHER, so neither can ship alone", () => {
    // The rule is a pair: "4 min ago" is honest only while the exact time is one hover away.
    const ts = formatTimestamp(new Date(2026, 7, 5, 11, 56), now);
    expect(ts.text).toBe(`4${NBSP}min ago`);
    expect(ts.title).toBe("Aug 5, 2026, 11:56 AM");
  });

  it("returns an empty pair for an unparseable date, so no tooltip promises a time", () => {
    expect(formatTimestamp("not a date", now)).toEqual({ text: "", title: "" });
  });
});

describe("alignment follows what the value is for", () => {
  it("right-aligns the figures that are compared down a column", () => {
    for (const kind of ["stock", "price", "priceBreak", "quantity"] as const) {
      expect(alignmentFor(kind), kind).toBe("right");
    }
  });

  it("left-aligns ordinary property values, including measurements and dates", () => {
    for (const kind of ["measurement", "date", "identifier", "text"] as const) {
      expect(alignmentFor(kind), kind).toBe("left");
    }
  });

  it("gives tabular figures to everything that contains digits, alignment aside", () => {
    for (const kind of ["stock", "price", "priceBreak", "quantity", "measurement", "date"] as const) {
      expect(isTabular(kind), kind).toBe(true);
    }
    expect(isTabular("text")).toBe(false);
  });
});

describe("a stored engineering value, typeset", () => {
  it("binds a number to its unit so the pair can never wrap apart", () => {
    expect(formatEngineeringValue("3.3V")).toBe(`3.3${NBSP}V`);
    expect(formatEngineeringValue("100 nF")).toBe(`100${NBSP}nF`);
  });

  it("takes the unit from the schema only when the value carried none", () => {
    expect(formatEngineeringValue("3.3", "V")).toBe(`3.3${NBSP}V`);
    // The source's own unit is the measured one and is never overwritten by the schema's.
    expect(formatEngineeringValue("16 MHz", "Hz")).toBe(`16${NBSP}MHz`);
  });

  it("writes a range with an en dash and states its unit once", () => {
    expect(formatEngineeringValue("1.65V to 5.5V")).toBe(`1.65${EN_DASH}5.5${NBSP}V`);
    expect(formatEngineeringValue("1.65-5.5 V")).toBe(`1.65${EN_DASH}5.5${NBSP}V`);
    expect(formatEngineeringValue("2.5 ~ 5.5", "V")).toBe(`2.5${EN_DASH}5.5${NBSP}V`);
  });

  it("uses the real minus, which is the width and height of the digits beside it", () => {
    expect(formatEngineeringValue("-40 to 125 °C")).toBe(`${MINUS}40${EN_DASH}125${NBSP}°C`);
    expect(formatEngineeringValue("-55", "°C")).toBe(`${MINUS}55${NBSP}°C`);
  });

  it("keeps the precision the source authored, and adds none of its own", () => {
    expect(formatEngineeringValue("3.30", "V")).toBe(`3.30${NBSP}V`);
    expect(formatEngineeringValue("0.000001", "F")).toBe(`0.000001${NBSP}F`);
  });

  it("attaches a percent sign directly, because a space there is a different symbol", () => {
    expect(formatEngineeringValue("1%")).toBe("1%");
  });

  it("refuses anything that is not a measurement, so the source's own words survive", () => {
    // A package code is not a subtraction, a tolerance sign is not a number, and a word is a word.
    for (const text of ["SOT-23-5", "±1%", "Yes", "X7R", "5 V (typ)", "1,000 h"]) {
      expect(formatEngineeringValue(text), text).toBe("");
    }
  });

  it("refuses a range whose two ends are measured in different units", () => {
    expect(formatEngineeringValue("3 V to 5 A")).toBe("");
  });

  it("collapses a range whose ends are the same value into the single quantity", () => {
    expect(formatEngineeringValue("5 to 5 V")).toBe(`5${NBSP}V`);
  });
});
