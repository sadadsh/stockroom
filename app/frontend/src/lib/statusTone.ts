/**
 * Map a status KIND to a semantic tone so a git/update status value reads at a glance by hue
 * instead of as plain body text (FIX-08). The tone is built entirely from the app's design
 * tokens (--c-ok / --c-warn / --c-err / --c-acc / --c-t3), mixed against transparent for the
 * fill so it adapts to both themes and clears >=3:1 contrast (the same tint idiom the Badge and
 * the Lifecycle chip use). Pure + total: every kind maps, and an unknown kind is neutral.
 */

export type StatusToneRole = "info" | "warn" | "ok" | "accent" | "neutral";

export interface StatusTone {
  /** the semantic role this value carries (for reasoning + tests) */
  role: StatusToneRole;
  /** the design token the tone is built from (never a raw hex) */
  token: "--c-ok" | "--c-warn" | "--c-err" | "--c-acc" | "--c-t3";
  /** the token-colored text class */
  text: string;
  /** a low-alpha color-mix tint of the same token, for a pill background */
  tint: string;
  /** text + tint composed: a full status pill */
  className: string;
}

function tone(role: StatusToneRole, token: StatusTone["token"], text: string, tintPct: number): StatusTone {
  // A theme-adaptive tint: the token mixed against transparent, so light and dark both get a
  // faint wash of the SAME semantic hue (no hardcoded rgba, no per-theme literal).
  const tint =
    role === "neutral"
      ? "bg-raise2"
      : `bg-[color-mix(in_srgb,var(${token})_${tintPct}%,transparent)]`;
  return { role, token, text, tint, className: `${text} ${tint}` };
}

const TONES: Record<string, StatusTone> = {
  // local commits waiting to push: informational, the neutral accent emphasis
  ahead: tone("info", "--c-acc", "text-acc", 14),
  // remote is ahead of you: pull soon
  behind: tone("warn", "--c-warn", "text-warn", 15),
  // a dirty working tree: this build will not match a commit
  uncommitted: tone("warn", "--c-warn", "text-warn", 15),
  dirty: tone("warn", "--c-warn", "text-warn", 15),
  // a new release exists: attention
  "update-available": tone("accent", "--c-acc", "text-acc", 14),
  // clean / current: success
  "up-to-date": tone("ok", "--c-ok", "text-ok", 15),
};

const NEUTRAL: StatusTone = tone("neutral", "--c-t3", "text-t3", 0);

/** The semantic tone for a status `kind`. Total: an unknown/empty kind is the neutral tone. */
export function statusTone(kind: string): StatusTone {
  return TONES[kind] ?? NEUTRAL;
}
