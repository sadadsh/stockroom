/**
 * What a person is allowed to write into one specification, decided BEFORE anything is sent.
 *
 * The category already told us what this field is: its value type, its unit, its allowed values,
 * its floor and its ceiling, and whether it applies to this kind of component at all. All of that
 * arrives on the record as `constraint` and `applicability`, so a refusal costs no round trip and
 * - more importantly - can say what the correction IS. "That change was not saved" is a report; a
 * ceiling of 5.5 V is an instruction.
 *
 * Everything here is pure and returns a REASON CODE rather than a sentence. The sentence is the
 * row's to render, because every word a person reads goes through the copy layer, and a validator
 * that returned English would be a second place UI text lives.
 *
 * This is not a second data model. Nothing is classified, grouped or re-derived: the rules are the
 * ones the dossier sent, applied to the characters in the box.
 */
import type { SpecificationConstraint, SpecificationRecord, ValueType } from "../../api/dossierTypes";
import { EN_DASH, MINUS, NBSP } from "../../lib/formatValue";

/** The value types a person can enter by hand. `list` is not one: a list is not typed into a box. */
export const EDITABLE_VALUE_TYPES: readonly ValueType[] = [
  "quantity",
  "range",
  "integer",
  "boolean",
  "enum",
  "text",
];

export function editableValueType(record: SpecificationRecord): ValueType {
  if ((record.constraint?.allowed.length ?? 0) > 0) return "enum";
  return EDITABLE_VALUE_TYPES.includes(record.valueType) ? record.valueType : "text";
}

/** Every way one entry can be wrong. One code per correction a person can actually make. */
export type SpecEditProblem =
  | "required"
  | "not-applicable"
  | "not-a-number"
  | "not-an-integer"
  | "not-a-range"
  | "not-a-boolean"
  | "not-allowed"
  | "wrong-unit"
  | "below-minimum"
  | "above-maximum";

export interface SpecEditRefusal {
  problem: SpecEditProblem;
  /** Named values the sentence needs: the ceiling it broke, the units it may use. */
  values: Record<string, string | number>;
}

export interface SpecDraft {
  value: string;
  unit: string;
  valueType: ValueType;
}

// The SI prefixes an entry may carry, and what each multiplies its base unit by. Small on
// purpose: this exists to check `4.7 kΩ` against a floor stated in Ω, not to be a unit library.
const SI_SCALE: Record<string, number> = {
  p: 1e-12,
  n: 1e-9,
  u: 1e-6,
  "µ": 1e-6,
  "μ": 1e-6,
  m: 1e-3,
  k: 1e3,
  K: 1e3,
  M: 1e6,
  G: 1e9,
  T: 1e12,
};

/** Spellings that name the same unit. A page writes ohms three ways and means one thing. */
const UNIT_ALIASES: Record<string, string> = {
  ohm: "Ω",
  ohms: "Ω",
  // U+03C9: both spellings of the ohm symbol fold to it, and the lookup is case-folded.
  "ω": "Ω",
  degc: "°C",
  "°c": "°C",
  celsius: "°C",
  percent: "%",
};

function canonicalUnit(unit: string): string {
  const trimmed = unit.trim();
  if (trimmed === "") return "";
  return UNIT_ALIASES[trimmed.toLowerCase()] ?? trimmed;
}

/**
 * How much an entered unit multiplies the constraint's unit by, or null when it is a different
 * unit altogether. An empty entry is taken to already be in the constraint's own unit.
 */
export function scaleTo(entered: string, expected: string): number | null {
  const want = canonicalUnit(expected);
  const got = canonicalUnit(entered);
  if (got === "" || want === "") return 1;
  if (got.toLowerCase() === want.toLowerCase()) return 1;
  const scale = SI_SCALE[got[0]];
  if (scale === undefined) return null;
  const rest = canonicalUnit(got.slice(1));
  return rest.toLowerCase() === want.toLowerCase() ? scale : null;
}

/** A single number, in the plain forms a person types. The real minus is accepted as a minus. */
function toNumber(text: string): number | null {
  const trimmed = text.trim().replace(MINUS, "-").replace(/,/g, "");
  if (!/^[+-]?(\d+\.?\d*|\.\d+)$/.test(trimmed)) return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

/** The two endpoints of a typed range, in every separator a person reaches for. */
function toRange(text: string): [number, number] | null {
  const parts = text
    .trim()
    .split(/\s*(?:\bto\b|~|\.{2,3}|–|—)\s*|(?<=[^\s\-−])\s*-\s*(?=[.\d])/i)
    .filter((part) => part.trim() !== "");
  if (parts.length !== 2) return null;
  const low = toNumber(parts[0]);
  const high = toNumber(parts[1]);
  if (low === null || high === null) return null;
  return [low, high];
}

function outsideBounds(
  magnitudes: number[],
  constraint: SpecificationConstraint,
): SpecEditRefusal | null {
  for (const magnitude of magnitudes) {
    if (constraint.minimum !== null && magnitude < constraint.minimum) {
      return {
        problem: "below-minimum",
        values: { minimum: constraint.minimum, unit: constraint.unit },
      };
    }
    if (constraint.maximum !== null && magnitude > constraint.maximum) {
      return {
        problem: "above-maximum",
        values: { maximum: constraint.maximum, unit: constraint.unit },
      };
    }
  }
  return null;
}

/** The answers a boolean field accepts, and what each one is stored as. */
const TRUE_WORDS = new Set(["yes", "true", "y"]);
const FALSE_WORDS = new Set(["no", "false", "n"]);

/**
 * Why this entry cannot be written, or null when it can.
 *
 * Checked in the order a person would want to be told: is there anything here at all, does this
 * field apply, is it the right shape, is the unit one this field is measured in, and is it inside
 * the range the category declares.
 */
export function validateSpecificationEdit(
  record: SpecificationRecord,
  draft: SpecDraft,
): SpecEditRefusal | null {
  const value = draft.value.trim();
  if (value === "") return { problem: "required", values: {} };
  // A reviewed value on a field the category says does not exist would make the sheet claim a
  // property the part cannot have. The control is not offered on such a row; this is the backstop.
  if (record.applicability === "not_applicable") {
    return { problem: "not-applicable", values: { label: record.label } };
  }

  const constraint = record.constraint;

  if (draft.valueType === "enum") {
    const allowed = constraint?.allowed ?? [];
    if (allowed.length > 0) {
      const folded = allowed.map((item) => item.toLowerCase());
      if (!folded.includes(value.toLowerCase())) {
        return { problem: "not-allowed", values: { allowed: allowed.join(", ") } };
      }
    }
    return null;
  }

  if (draft.valueType === "boolean") {
    const folded = value.toLowerCase();
    if (!TRUE_WORDS.has(folded) && !FALSE_WORDS.has(folded)) {
      return { problem: "not-a-boolean", values: {} };
    }
    return null;
  }

  if (draft.valueType === "text") return null;

  // Numeric from here down, so the unit has to be one this field is measured in before any
  // magnitude means anything.
  let scale = 1;
  if (constraint?.unit) {
    const resolved = scaleTo(draft.unit, constraint.unit);
    if (resolved === null) return { problem: "wrong-unit", values: { unit: constraint.unit } };
    scale = resolved;
  }

  if (draft.valueType === "range") {
    const bounds = toRange(value);
    if (!bounds) return { problem: "not-a-range", values: { dash: EN_DASH } };
    return constraint ? outsideBounds(bounds.map((item) => item * scale), constraint) : null;
  }

  const magnitude = toNumber(value);
  if (magnitude === null) return { problem: "not-a-number", values: {} };
  if (draft.valueType === "integer" && !Number.isInteger(magnitude)) {
    return { problem: "not-an-integer", values: {} };
  }
  return constraint ? outsideBounds([magnitude * scale], constraint) : null;
}

/**
 * The one string the write carries: the value and its unit, joined the way the sheet reads them.
 *
 * The unit travels INSIDE the value because that is what a specification value is - the record
 * has no second slot for it, and splitting the pair across two fields would let a record hold a
 * number whose unit nothing remembers. A range states its unit once, at the end, for the same
 * reason it is displayed that way.
 */
export function composeSpecificationValue(draft: SpecDraft): string {
  // A hyphen BETWEEN two figures is a range and is written with an en dash. A leading hyphen is
  // a sign and is left alone, which is why the lookbehind is not optional.
  const value = draft.value.trim().replace(/(?<=[^\s\-−])\s*-\s*(?=[.\d])/, EN_DASH);
  const unit = draft.unit.trim();
  if (unit === "" || draft.valueType === "text" || draft.valueType === "enum") return value;
  if (draft.valueType === "boolean") return value;
  if (value.endsWith(unit)) return value;
  return `${value}${NBSP}${unit}`;
}
