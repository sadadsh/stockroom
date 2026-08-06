/**
 * Map a status KIND to a semantic tone so a git/update status value reads as a state rather than as
 * plain body text (FIX-08). The tone is built entirely from the app's design tokens
 * (--c-ok / --c-warn / --c-err / --c-t3), mixed against transparent for the fill so it adapts to
 * both themes and clears >=3:1 contrast (the same tint idiom the Badge and the product-status chip
 * use). `token` names the token the TINT is mixed from, which is the mark strength; the `text` class
 * is the WORD and therefore the text strength, since a pill's label is normal text at 4.5:1.
 * Pure + total: every kind maps, and an unknown kind is neutral.
 *
 * `--c-acc` IS NO LONGER ONE OF THEM. Two kinds resolved onto it - `ahead` and `update-available` -
 * and the accent was an amber, so "Update Available" sat in the same colour as the selected row, the
 * active tab and every `Missing`. The accent is a loud NEUTRAL now, which would make an update
 * notice the brightest text on the screen, so these two moved onto the tiers that describe what they
 * actually are: `ahead` is supplementary information (the label tier) and `update-available` is a
 * warning (the warning tier, which draws its own triangle wherever it goes through StatusText or
 * Badge). The ROLE names are unchanged, because the role is the semantic and only the paint moved.
 */

export type StatusToneRole = "info" | "warn" | "ok" | "accent" | "neutral";

export interface StatusTone {
  /** the semantic role this value carries (for reasoning + tests) */
  role: StatusToneRole;
  /** the design token the tone is built from (never a raw hex) */
  token: "--c-ok" | "--c-warn" | "--c-err" | "--c-t3";
  /** the token-colored text class */
  text: string;
  /** a low-alpha color-mix tint of the same token, for a pill background */
  tint: string;
  /** text + tint composed: a full status pill */
  className: string;
}

// Keep arbitrary-value utilities as complete literals so Tailwind never emits a
// `${token}` placeholder into production CSS.
const TINT_CLASSES: Readonly<Record<string, string>> = {
  "--c-warn:15": "bg-[color-mix(in_srgb,var(--c-warn)_15%,transparent)]",
  "--c-ok:15": "bg-[color-mix(in_srgb,var(--c-ok)_15%,transparent)]",
  "--c-err:15": "bg-[color-mix(in_srgb,var(--c-err)_15%,transparent)]",
};

function tone(role: StatusToneRole, token: StatusTone["token"], text: string, tintPct: number): StatusTone {
  // A theme-adaptive tint: the token mixed against transparent, so light and dark both get a
  // faint wash of the SAME semantic hue (no hardcoded rgba, no per-theme literal).
  const tint =
    role === "neutral"
      ? "bg-raise2"
      : (TINT_CLASSES[`${token}:${tintPct}`] ?? "bg-raise2");
  return { role, token, text, tint, className: `${text} ${tint}` };
}

const TONES: Record<string, StatusTone> = {
  // local commits waiting to push: informational, at the label tier
  ahead: tone("info", "--c-t3", "text-t3", 0),
  // remote is ahead of you: pull soon
  behind: tone("warn", "--c-warn", "text-warn", 15),
  // a dirty working tree: this build will not match a commit
  uncommitted: tone("warn", "--c-warn", "text-warn", 15),
  dirty: tone("warn", "--c-warn", "text-warn", 15),
  // a new release exists: attention, which is the warning tier
  "update-available": tone("accent", "--c-warn", "text-warn", 15),
  // clean / current: success
  "up-to-date": tone("ok", "--c-ok", "text-ok-text", 15),
};

const NEUTRAL: StatusTone = tone("neutral", "--c-t3", "text-t3", 0);

/** The semantic tone for a status `kind`. Total: an unknown/empty kind is the neutral tone. */
export function statusTone(kind: string): StatusTone {
  return TONES[kind] ?? NEUTRAL;
}
