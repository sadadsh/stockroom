/**
 * The pinout map's visual encoding, shared by PinoutMap, PinoutLegend, and PinInspector so all
 * three read the same four channels (CONTEXT decision 5). Exactly ONE channel runs saturated color
 * (fill = electrical-class category); the others are neutral, so the map stays disciplined.
 *
 * - Fill  = PinDTO.category (electrical_class): the one saturated hue, a --stm-* token. The hue
 *           table itself lives in lib/stmPinHue.ts (the single color-is-data source); this module
 *           only adapts it to the map's neutral fallback and adds the map-specific role/5V channels.
 * - Border = PinDTO.roles[].role_class: a restrained NEUTRAL stroke that strengthens for a
 *            special-purpose pin (debug, oscillator, boot, reset, power), never a second hue.
 * - Mark  = PinDTO.five_v.tolerant: a small neutral dot, present only on 5V-tolerant IO pins.
 * - Ring  = selection: the neutral accent ring, not a fifth hue.
 */
import type { PinDTO } from "../../api/types";
import { PIN_CATEGORY_HUES, pinElectricalHue, type PinCategory } from "../../lib/stmPinHue";

export type { PinCategory };

// The legend teaches the ten category buckets in stmPinHue's order (gpio-first through nc). Each
// entry is a full hue descriptor (key / label / token / stroke / tileClass) from the single source.
export const PIN_CATEGORIES = PIN_CATEGORY_HUES;

// The category fill as a token reference (never a raw hex). An UNKNOWN category renders as a neutral
// line tint on the map (--c-line2) - visibly un-categorized, never silently painted as another
// category (that exact fallback once masked a real vocabulary mismatch as a "Not Connected" pin).
export function categoryFill(category: string): string {
  const hue = pinElectricalHue(category);
  return hue.key === "neutral" ? "var(--c-line2)" : hue.stroke;
}

export function categoryLabel(category: string): string {
  const hue = pinElectricalHue(category);
  if (hue.key !== "neutral") return hue.label;
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
