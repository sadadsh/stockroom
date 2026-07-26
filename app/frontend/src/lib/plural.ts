/** Counted nouns that agree with their number.
 *
 * The status bar read "1 Components" on 10 of the 12 captured screens, which is the kind of thing
 * that reads as carelessness everywhere it appears. It is a one-line fix per site and there are
 * several sites, so it is a helper rather than a scattering of ternaries.
 *
 * Deliberately NOT a general English pluraliser: this app counts a small, known set of nouns, and
 * a clever inflector would be a pile of rules serving five words. An irregular plural is passed
 * explicitly.
 */
export function plural(count: number, one: string, many?: string): string {
  return count === 1 ? one : (many ?? `${one}s`);
}

/** "1 Component" / "2 Components", with the number formatted for the locale.
 *
 * The count is grouped ("1,204 Components"), because a four-digit library is reachable and an
 * ungrouped 1204 reads as a part number in a bar full of part numbers.
 */
export function counted(count: number, one: string, many?: string): string {
  return `${count.toLocaleString()} ${plural(count, one, many)}`;
}
