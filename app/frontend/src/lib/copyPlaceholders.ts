/**
 * Named placeholders for the copy layer, and the fail-safe rules around them.
 *
 * A copy entry that has to say a number or a name writes it as a NAMED placeholder rather than by
 * concatenation:
 *
 *     <Text id="provider.downloaded" values={{ count, total }}>
 *       Downloaded {count} of {total} files
 *     </Text>
 *
 * The syntax is exactly `{name}`: an ASCII letter followed by letters, digits or underscores. There
 * is no index form, no format spec, and no escape - one shape, so a reworded override cannot invent
 * a second one.
 *
 * The DEFAULT string is the declaration. The placeholder set written into the JSX default is the
 * REQUIRED set for that id, and the call site passes exactly those names in `values` (a compile-time
 * obligation, since `values` is typed and the default is a literal). An override is a rewording of
 * that same sentence, so it must carry the same set - no more, no less.
 *
 * Three things can be wrong with a committed override, and all three resolve the same way (render
 * the DEFAULT, record a diagnostic, never show template syntax to a person):
 *
 *   malformed            - a brace that is not part of a well-formed `{name}` (`Downloaded {coun`,
 *                          `{}`, `{2}`, `{{count}}`). There is no way to know what was meant.
 *   missing-placeholder  - a required name was dropped ("Downloaded some files"), so the number the
 *                          sentence exists to carry would silently vanish.
 *   unknown-placeholder  - a name the call site does not supply ("Downloaded {count} of {pages}"),
 *                          which has no value and would render as nothing.
 *
 * Failing safe at RENDER is not a substitute for validating at SAVE, it is the other half: the
 * overrides file is committed source and can be hand-edited or arrive from an older revision, so the
 * app has to survive one that no longer matches the sentence it was written against.
 *
 * No React here on purpose - `lib/devMode.tsx` needs the same grammar to check an edit before it is
 * saved, and importing the copy component from the provider would be a cycle.
 */

/** What a call site substitutes. Numbers are formatted by the caller when grouping matters. */
export type CopyValues = Record<string, string | number>;

// The one placeholder shape. Global, so `lastIndex` is reset before every scan that uses it.
const PLACEHOLDER_RE = /\{([A-Za-z][A-Za-z0-9_]*)\}/g;

/**
 * The placeholder names in a template, sorted and de-duplicated, or `null` when the template is
 * MALFORMED (it carries a brace that is not part of a well-formed `{name}`).
 *
 * Malformedness is decided by removing every well-formed token and checking whether any brace
 * survives, so `{{count}}` and `{}` are caught as surely as an unclosed `{coun`.
 */
export function copyPlaceholders(template: string): string[] | null {
  const names = new Set<string>();
  let remainder = "";
  let cursor = 0;
  PLACEHOLDER_RE.lastIndex = 0;
  for (let m = PLACEHOLDER_RE.exec(template); m; m = PLACEHOLDER_RE.exec(template)) {
    names.add(m[1]);
    remainder += template.slice(cursor, m.index);
    cursor = m.index + m[0].length;
  }
  remainder += template.slice(cursor);
  if (remainder.includes("{") || remainder.includes("}")) return null;
  return [...names].sort();
}

/** True when a string carries no brace at all - the shape almost every copy entry has. */
export function hasNoPlaceholders(template: string): boolean {
  return !template.includes("{") && !template.includes("}");
}

/** Why an override cannot be used. Ordered by how it is discovered, not by severity. */
export type CopyProblem = "malformed" | "missing-placeholder" | "unknown-placeholder";

/**
 * Check one override against the default it reworded. `null` means it is safe to render.
 *
 * A default that is itself malformed is treated as declaring NO placeholders, so the override is
 * held to the stricter reading rather than inheriting the mistake. (A malformed default is a source
 * bug; `copy.coverage.test.ts` fails on one.)
 */
export function copyOverrideProblem(defaultText: string, override: string): CopyProblem | null {
  const actual = copyPlaceholders(override);
  if (actual === null) return "malformed";
  const required = copyPlaceholders(defaultText) ?? [];
  for (const name of required) if (!actual.includes(name)) return "missing-placeholder";
  for (const name of actual) if (!required.includes(name)) return "unknown-placeholder";
  return null;
}

/**
 * Substitute `values` into a template.
 *
 * A name with no supplied value collapses to the empty string rather than rendering `{name}`: the
 * contract is that template syntax never reaches a person, and a sentence missing a number is a
 * smaller failure than a sentence showing its own source.
 */
export function formatCopy(template: string, values?: CopyValues): string {
  if (values === undefined && hasNoPlaceholders(template)) return template;
  return template.replace(PLACEHOLDER_RE, (_match, name: string) => {
    const value = values?.[name];
    return value === undefined || value === null ? "" : String(value);
  });
}

// --- diagnostics ------------------------------------------------------------------------------
// A rejected override is not an exception and not a console flood: it is one recorded fact per id,
// readable by the Design panel so the person who wrote it can see WHY their rewording is not live.

export interface CopyDiagnostic {
  /** The copy id whose override was rejected. */
  id: string;
  /** Which rule it broke. */
  problem: CopyProblem;
  /** The placeholder names the default declares, so the panel can say what is required. */
  required: string[];
}

// Bounded: a diagnostic per id, and a cap so a pathological overrides file cannot grow this without
// limit. The map is keyed by id, so re-rendering the same bad entry records it once.
const MAX_DIAGNOSTICS = 200;
const diagnostics = new Map<string, CopyDiagnostic>();

export function recordCopyDiagnostic(id: string, problem: CopyProblem, required: string[]): void {
  if (!diagnostics.has(id) && diagnostics.size >= MAX_DIAGNOSTICS) return;
  diagnostics.set(id, { id, problem, required });
}

export function clearCopyDiagnostic(id: string): void {
  diagnostics.delete(id);
}

export function copyDiagnosticFor(id: string): CopyDiagnostic | undefined {
  return diagnostics.get(id);
}

export function copyDiagnostics(): CopyDiagnostic[] {
  return [...diagnostics.values()];
}

/** Test seam: drop every recorded diagnostic. */
export function resetCopyDiagnostics(): void {
  diagnostics.clear();
}

// --- declared placeholder sets ----------------------------------------------------------------
// Which names each id requires, learned from the DEFAULT text at the call site as it renders. This
// is not a second copy registry: there is no list of ids to keep in sync, only what the one copy
// layer has actually seen, and it exists so Save can tell the backend what each override must match.

const declared = new Map<string, string[]>();

export function declareCopyPlaceholders(id: string, defaultText: string): void {
  if (hasNoPlaceholders(defaultText)) {
    // Record the empty set too: it is what lets Save prove an override may not INVENT a placeholder
    // for a sentence that never had one.
    if (!declared.has(id)) declared.set(id, []);
    return;
  }
  declared.set(id, copyPlaceholders(defaultText) ?? []);
}

/** The declared sets for every id seen this session, for the /api/dev/save payload. */
export function copyPlaceholderDeclarations(): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const [id, names] of declared) out[id] = names;
  return out;
}

/** Test seam: forget every declaration. */
export function resetCopyDeclarations(): void {
  declared.clear();
}
