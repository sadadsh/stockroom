/**
 * What a person is allowed to write into one specification, and what they are told when they are
 * not.
 *
 * Every rule here comes from the category schema the dossier already sent. The point of checking
 * before the write is not to save a round trip: it is that the category knows what the correction
 * IS. A server that answers "422" tells somebody their number was wrong; a ceiling of 5.5 V tells
 * them what to type instead.
 */
import { describe, expect, it } from "vitest";
import type { SpecificationRecord } from "../../api/dossierTypes";
import { EN_DASH, NBSP } from "../../lib/formatValue";
import { makeSpecification } from "../../test/dossierFixture";
import {
  composeSpecificationValue,
  editableValueType,
  scaleTo,
  validateSpecificationEdit,
} from "./specificationEditing";

function withConstraint(over: Partial<SpecificationRecord> = {}): SpecificationRecord {
  return makeSpecification({
    key: "supply_voltage",
    label: "Supply Voltage",
    valueType: "quantity",
    unit: "V",
    constraint: { minimum: 1.65, maximum: 5.5, unit: "V", allowed: [], note: "" },
    ...over,
  });
}

const quantity = { unit: "V", valueType: "quantity" } as const;

describe("an entry that cannot be written", () => {
  it("refuses an empty value rather than storing a blank as an answer", () => {
    expect(validateSpecificationEdit(withConstraint(), { ...quantity, value: "  " })).toEqual({
      problem: "required",
      values: {},
    });
  });

  it("refuses a field the category says this kind of component does not have", () => {
    const refusal = validateSpecificationEdit(
      withConstraint({ applicability: "not_applicable" }),
      { ...quantity, value: "3.3" },
    );
    expect(refusal?.problem).toBe("not-applicable");
  });

  it("refuses text where the field is measured, and says what a number looks like", () => {
    expect(
      validateSpecificationEdit(withConstraint(), { ...quantity, value: "about three" })?.problem,
    ).toBe("not-a-number");
  });

  it("refuses a fraction on a field counted in whole units", () => {
    const pins = makeSpecification({ key: "pin_count", valueType: "integer", unit: "" });
    expect(
      validateSpecificationEdit(pins, { value: "5.5", unit: "", valueType: "integer" })?.problem,
    ).toBe("not-an-integer");
  });

  it("refuses one number where the field is a range", () => {
    expect(
      validateSpecificationEdit(withConstraint(), { ...quantity, value: "3.3", valueType: "range" })
        ?.problem,
    ).toBe("not-a-range");
  });

  it("refuses a value outside the floor and the ceiling the category declares", () => {
    expect(validateSpecificationEdit(withConstraint(), { ...quantity, value: "9" })).toEqual({
      problem: "above-maximum",
      values: { maximum: 5.5, unit: "V" },
    });
    expect(validateSpecificationEdit(withConstraint(), { ...quantity, value: "0.9" })).toEqual({
      problem: "below-minimum",
      values: { minimum: 1.65, unit: "V" },
    });
  });

  it("checks BOTH ends of a range, because a range is only inside if all of it is", () => {
    expect(
      validateSpecificationEdit(withConstraint(), {
        ...quantity,
        value: `1.65${EN_DASH}9`,
        valueType: "range",
      })?.problem,
    ).toBe("above-maximum");
  });

  it("refuses a unit this field is not measured in, and names the one it is", () => {
    expect(validateSpecificationEdit(withConstraint(), { ...quantity, unit: "A", value: "3" })).toEqual(
      { problem: "wrong-unit", values: { unit: "V" } },
    );
  });

  it("refuses a value that is not one of the ones the field accepts", () => {
    const enumerated = withConstraint({
      valueType: "enum",
      constraint: { minimum: null, maximum: null, unit: "", allowed: ["SMD", "Through Hole"], note: "" },
    });
    expect(
      validateSpecificationEdit(enumerated, { value: "Panel", unit: "", valueType: "enum" }),
    ).toEqual({ problem: "not-allowed", values: { allowed: "SMD, Through Hole" } });
  });

  it("refuses anything but yes or no on a two-state field", () => {
    const flag = makeSpecification({ key: "schmitt_trigger", valueType: "boolean", unit: "" });
    expect(
      validateSpecificationEdit(flag, { value: "maybe", unit: "", valueType: "boolean" })?.problem,
    ).toBe("not-a-boolean");
  });
});

describe("an entry that can be written", () => {
  it("accepts a value inside the range, in the field's own unit", () => {
    expect(validateSpecificationEdit(withConstraint(), { ...quantity, value: "3.3" })).toBeNull();
  });

  it("accepts a prefixed unit, because 4.7 kΩ is not outside a floor stated in Ω", () => {
    const resistance = withConstraint({
      key: "resistance",
      unit: "Ω",
      constraint: { minimum: 0, maximum: 1e6, unit: "Ω", allowed: [], note: "" },
    });
    expect(
      validateSpecificationEdit(resistance, { value: "4.7", unit: "kΩ", valueType: "quantity" }),
    ).toBeNull();
    // And the scaling is the reason: 4.7 kΩ read as 4.7 Ω would pass a check it should not.
    expect(
      validateSpecificationEdit(resistance, { value: "4.7", unit: "MΩ", valueType: "quantity" })
        ?.problem,
    ).toBe("above-maximum");
  });

  it("accepts free text on a field with no shape to break", () => {
    const text = makeSpecification({ key: "packaging", valueType: "text", unit: "" });
    expect(
      validateSpecificationEdit(text, { value: "Tape & Reel", unit: "", valueType: "text" }),
    ).toBeNull();
  });

  it("accepts the real minus sign a person pastes back out of the sheet", () => {
    const temperature = withConstraint({
      key: "operating_temperature",
      unit: "°C",
      constraint: { minimum: -65, maximum: 150, unit: "°C", allowed: [], note: "" },
    });
    expect(
      validateSpecificationEdit(temperature, { value: "−40", unit: "°C", valueType: "quantity" }),
    ).toBeNull();
  });
});

describe("what the write actually carries", () => {
  it("puts the unit inside the value, bound to it, because the record has no second slot", () => {
    expect(
      composeSpecificationValue({ value: "3.3", unit: "V", valueType: "quantity" }),
    ).toBe(`3.3${NBSP}V`);
  });

  it("states a range's unit once, at the end, exactly as the sheet reads it", () => {
    expect(
      composeSpecificationValue({ value: "1.65-5.5", unit: "V", valueType: "range" }),
    ).toBe(`1.65${EN_DASH}5.5${NBSP}V`);
  });

  it("leaves a leading minus alone, because a sign is not a range", () => {
    expect(
      composeSpecificationValue({ value: "-40", unit: "°C", valueType: "quantity" }),
    ).toBe(`-40${NBSP}°C`);
  });

  it("never doubles a unit the person already typed", () => {
    expect(composeSpecificationValue({ value: "3.3 V", unit: "V", valueType: "quantity" })).toBe(
      "3.3 V",
    );
  });

  it("leaves text and enumerated answers exactly as they were chosen", () => {
    expect(composeSpecificationValue({ value: "SMD", unit: "V", valueType: "enum" })).toBe("SMD");
    expect(composeSpecificationValue({ value: "Yes", unit: "V", valueType: "boolean" })).toBe("Yes");
  });
});

describe("which control the editor opens with", () => {
  it("offers the list whenever the category declares one, whatever the stored type says", () => {
    expect(
      editableValueType(
        makeSpecification({
          valueType: "text",
          constraint: { minimum: null, maximum: null, unit: "", allowed: ["SMD"], note: "" },
        }),
      ),
    ).toBe("enum");
  });

  it("falls back to text for a shape nobody can type into a box", () => {
    expect(editableValueType(makeSpecification({ valueType: "list" }))).toBe("text");
  });
});

describe("reading one unit against another", () => {
  it("takes an empty entry to already be in the field's own unit", () => {
    expect(scaleTo("", "V")).toBe(1);
  });

  it("knows the spellings of the ohm that mean the same unit", () => {
    expect(scaleTo("Ohms", "Ω")).toBe(1);
    expect(scaleTo("kOhm", "Ω")).toBe(1e3);
  });

  it("refuses a unit that is simply a different measurement", () => {
    expect(scaleTo("A", "V")).toBeNull();
  });
});
