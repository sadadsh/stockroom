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

export type PinCategory = "io" | "power" | "ground" | "reset" | "boot" | "vcap" | "nc";

export interface CategorySpec {
  key: PinCategory;
  label: string;
  token: string;
}

// Ordered io-first (the class most pins carry) through the quietest (nc), the order the legend
// teaches them in.
export const PIN_CATEGORIES: readonly CategorySpec[] = [
  { key: "io", label: "I/O", token: "--stm-cat-io" },
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

// The category fill as a token reference (never a raw hex), falling back to nc for an unknown
// category so a pad always renders.
export function categoryFill(category: string): string {
  const spec = CATEGORY_BY_KEY[category] ?? CATEGORY_BY_KEY.nc;
  return `var(${spec.token})`;
}

export function categoryLabel(category: string): string {
  return (CATEGORY_BY_KEY[category] ?? CATEGORY_BY_KEY.nc).label;
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
