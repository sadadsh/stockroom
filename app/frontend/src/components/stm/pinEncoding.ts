/**
 * The pinout map's visual encoding, shared by PinoutMap, PinoutLegend, and PinInspector so all
 * three read the same four channels (CONTEXT decision 5). Exactly ONE channel runs saturated color
 * (fill = electrical-class category); the others are neutral, so the map stays disciplined.
 *
 * - Fill  = PinDTO.category (electrical_class): the one saturated hue, a --stm-cat-* token.
 * - Border = PinDTO.roles[].role_class: a restrained NEUTRAL stroke that strengthens for a
 *            special-purpose pin (debug, oscillator, boot, reset, power), never a second hue.
 * - Mark  = PinDTO.five_v.tolerant: a small neutral dot, present only on 5V-tolerant IO pins.
 * - Ring  = selection: the neutral accent ring, not a fifth hue.
 */
import type { PinDTO } from "../../api/types";

// The API's PinDTO.category vocabulary (_pin_category in api/routers/stm.py): the io
// electrical class splits into four visual buckets (gpio/analog/debug/oscillator); every other
// class passes through as itself. The two vocabularies MUST stay in lockstep — an unknown
// category renders neutral and labels itself verbatim, never masquerading as another category.
export type PinCategory =
  | "gpio"
  | "analog"
  | "debug"
  | "oscillator"
  | "power"
  | "ground"
  | "reset"
  | "boot"
  | "vcap"
  | "nc";

export interface CategorySpec {
  key: PinCategory;
  label: string;
  token: string;
}

// Ordered gpio-first (the bucket most pins carry) through the quietest (nc), the order the
// legend teaches them in.
export const PIN_CATEGORIES: readonly CategorySpec[] = [
  { key: "gpio", label: "GPIO", token: "--stm-cat-gpio" },
  { key: "analog", label: "Analog", token: "--stm-cat-analog" },
  { key: "debug", label: "Debug", token: "--stm-cat-debug" },
  { key: "oscillator", label: "Oscillator", token: "--stm-cat-oscillator" },
  { key: "power", label: "Power", token: "--stm-cat-power" },
  { key: "ground", label: "Ground", token: "--stm-cat-ground" },
  { key: "reset", label: "Reset", token: "--stm-cat-reset" },
  { key: "boot", label: "Boot", token: "--stm-cat-boot" },
  { key: "vcap", label: "Vcap", token: "--stm-cat-vcap" },
  { key: "nc", label: "Not Connected", token: "--stm-cat-nc" },
];

const CATEGORY_BY_KEY: Record<string, CategorySpec> = Object.fromEntries(
  PIN_CATEGORIES.map((c) => [c.key, c]),
);
// A raw electrical_class "io" (a category the API only emits pre-split) reads as plain gpio.
CATEGORY_BY_KEY.io = CATEGORY_BY_KEY.gpio;

// The category fill as a token reference (never a raw hex). An UNKNOWN category renders as a
// neutral line tint — visibly un-categorized, never silently painted as Not Connected (that
// exact fallback masked a real vocabulary mismatch as a "Not Connected" I/O pin).
export function categoryFill(category: string): string {
  const spec = CATEGORY_BY_KEY[category];
  return spec ? `var(${spec.token})` : "var(--c-line2)";
}

export function categoryLabel(category: string): string {
  const spec = CATEGORY_BY_KEY[category];
  if (spec) return spec.label;
  return category ? category.charAt(0).toUpperCase() + category.slice(1) : "Unknown";
}

// The border channel: three neutral tiers keyed off the pin's role classes (never a hue). A pin
// with a special-purpose role reads with a brighter, heavier stroke; a plain I/O keeps the quiet
// hairline. The legend teaches this as "border weight = pin role".
const NOTABLE_ROLE = /swd|jtag|osc|boot|reset|nrst|debug|trace|tamper|wkup|mco/i;

export interface RoleStroke {
  color: string;
  width: number;
  tier: 0 | 1 | 2;
}

export function roleStroke(pin: Pick<PinDTO, "roles">): RoleStroke {
  const roles = pin.roles ?? [];
  if (roles.length === 0) return { color: "var(--c-line2)", width: 1, tier: 0 };
  const notable = roles.some((r) => NOTABLE_ROLE.test(r.role_class) || NOTABLE_ROLE.test(r.role_name));
  return notable
    ? { color: "var(--c-t1)", width: 1.75, tier: 2 }
    : { color: "var(--c-t2)", width: 1.25, tier: 1 };
}

// The 5V mark shows only on a 5V-tolerant pin (five_v.tolerant true). five_v null (non-GPIO) means
// no mark at all, itself informative (decision 5).
export function isFiveVoltTolerant(pin: Pick<PinDTO, "five_v">): boolean {
  return pin.five_v?.tolerant === true;
}
