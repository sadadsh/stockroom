/**
 * THE INTERFACE-LETTER RULE, as a function the running editor can call.
 *
 * `lib/interfaceTerms.ts` states the rule and the replacement for each blocked term.
 * `copy.letterRule.test.ts` enforces it against everything an AGENT authors, by reading the four
 * shapes a copy default is written in out of source. Neither of those can help while the OWNER is
 * typing: Design Mode's copy editor rewords a shipped label in the browser, and a gate that runs in
 * CI over source text has nothing to say about a string that exists only in a draft.
 *
 * So the JUDGEMENT moves here and the two callers share it:
 *
 *   THE GATE (`copy.letterRule.test.ts`) imports `judgedText` and `PROPER_NAMES`, so the allowlist
 *   and the blanking rules are stated once. Before this module the editor would have had to carry a
 *   second copy of both, and a term added to one list would have quietly stopped matching in the
 *   other - the allowlist is the one place the rule can be defeated wholesale, and two allowlists
 *   is one more than that argument survives.
 *
 *   THE EDITOR (`components/DevPanel.tsx`) calls `letterRuleOffences` on the working text and shows
 *   what it finds. It WARNS AND NEVER BLOCKS (plan decision 3): Save stays enabled, because the rule
 *   exists to catch text written FOR the owner and this is the owner writing in their own product.
 *
 * WHAT IS NOT HERE, and where it goes instead. Plan 1.5 settles the rest of this question: at commit
 * an owner-authored override carries PROVENANCE marking it as such, and the lint exempts an
 * owner-authored override while still binding everything an agent writes. Provenance is a field on
 * the committed override and belongs to the commit pipeline, which is PHASE 4 - so nothing in this
 * module records who typed anything. It reports what the text says, and that is all it claims.
 */
import { INDUSTRY_TERMS } from "./interfaceTerms";

/**
 * Unicode U+0079, the letter this interface leaves out.
 *
 * The lower-case codepoint and only it, which is what the gate has always tested for and therefore
 * what the editor must agree with. A warning that fired on the capital where the gate does not would
 * be telling the owner their text is an offence that nothing downstream reports.
 */
export const BLOCKED_LETTER = "y";

/**
 * ALLOWLIST, CATEGORY 1 - a proper name that is not ours to reword.
 *
 * Kept deliberately tiny and whole-word. `DigiKey` is a distributor's registered trade name; it
 * appears inside sentences this product authors ("no DigiKey API credential is set"), and spelling
 * a company's name differently would be a factual error, not a style choice.
 *
 * CATEGORY 2 - the standardised technical terms with no synonym - lives in `interfaceTerms.ts` as
 * `INDUSTRY_TERMS`, beside the one-line reason each entry carries and the test that caps its length.
 */
export const PROPER_NAMES: readonly string[] = ["DigiKey"];

/** Every permitted term, both categories, as plain words. */
export const ALLOWED_TERMS: readonly string[] = [
  ...PROPER_NAMES,
  ...INDUSTRY_TERMS.map((entry) => entry.term),
];

/**
 * Every allowed term as a whole-word, case-insensitive matcher with an optional plural `s`.
 *
 * Whole-word matters in both directions: it stops `Layer` from laundering `Layered Analysis`, and it
 * stops a bare substring match from silently blessing a longer offending word that happens to
 * contain an allowed one. Case-insensitive because an upper-case letter is the same letter - the
 * rule says so explicitly - so `symbol` in prose is exempt on the same grounds as `Symbol` on a
 * label.
 *
 * Built once. Each carries the `g` flag and is only ever handed to `String.prototype.replace`, which
 * resets `lastIndex` itself, so a shared instance cannot carry state between two calls.
 */
const ALLOWED = ALLOWED_TERMS.map(
  // Escaped, though every term today is plain letters: an allowlist entry is a WORD, and a term
  // that ever carried a regex metacharacter would otherwise be compiled as a pattern and exempt far
  // more than the word it names - which is the one direction this list must never fail in.
  (term) => new RegExp(`\\b${term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}s?\\b`, "gi"),
);

/**
 * What the rule actually judges: the text with its data holes and its allowed terms removed.
 *
 * A `{name}` placeholder resolves to data at render, so the words around it are judged and the hole
 * is not - the name inside is a code identifier wired to a values object, not text anybody reads.
 * A string offends when THIS still carries the letter.
 */
export function judgedText(text: string): string {
  let out = text.replace(/\{[^{}]*\}/g, " ");
  for (const allowed of ALLOWED) out = out.replace(allowed, " ");
  return out;
}

/**
 * The words in this text that carry the letter, in first-appearance order, each named once.
 *
 * The WORDS rather than a boolean, because a warning that says only "there is a problem" leaves the
 * owner to hunt a single character through a sentence. An empty array is the clean answer.
 */
export function letterRuleOffences(text: string): string[] {
  const words = judgedText(text).match(/[A-Za-z][A-Za-z-]*/g) ?? [];
  const found: string[] = [];
  // The order is the sentence's, so the answer is an ARRAY; the set is only the seen-check, which
  // would otherwise be a scan of the answer per word.
  const seen = new Set<string>();
  for (const word of words) {
    if (!word.includes(BLOCKED_LETTER)) continue;
    if (seen.has(word)) continue;
    seen.add(word);
    found.push(word);
  }
  return found;
}
