/**
 * The pinned-spec preference, read and written in one place.
 *
 * Pins are per CATEGORY and bind to a canonical spec id, so a pin set on `Voltage - Breakdown`
 * still applies to a part whose vendor spells it `Breakdown Voltage`. They persist through the
 * machine config like the theme and the rail: localStorage alone resets on every launch, because
 * the host binds an ephemeral port and the origin moves with it (see uiPrefs.ts).
 *
 * Unlike the scalar preferences this one is JSON, so a malformed mirror must degrade to "nothing
 * pinned" rather than throwing during the first render of the surface that reads it.
 */
import { normalizePinnedSpecs, type PinnedSpecs } from "./keySpecs";
import { readPref, writePref } from "./uiPrefs";

export const PINNED_SPECS_KEY = "stockroom.pinned-specs";

export function readPinnedSpecs(): PinnedSpecs {
  return normalizePinnedSpecs(
    readPref<PinnedSpecs>(
      "pinned_specs",
      PINNED_SPECS_KEY,
      (raw) => {
        try {
          const parsed = JSON.parse(raw);
          return parsed && typeof parsed === "object" && !Array.isArray(parsed)
            ? (parsed as PinnedSpecs)
            : undefined;
        } catch {
          return undefined;
        }
      },
      {},
    ),
  );
}

export function writePinnedSpecs(pinned: PinnedSpecs): void {
  writePref("pinned_specs", pinned, PINNED_SPECS_KEY);
}
