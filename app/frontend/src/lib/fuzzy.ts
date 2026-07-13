/**
 * A tiny, dependency-free fuzzy matcher for the Ctrl+K palette. It scores a query
 * against a candidate string by walking both in order: the query must appear as a
 * case-insensitive subsequence (every query char, in order) or there is no match.
 * When it matches, the score rewards the traits a human reads as "closer": a run
 * of adjacent hits, a hit at a word boundary (string start or after a separator),
 * and a tighter (shorter) candidate. Higher is better. This is deliberately not a
 * full Smith-Waterman: it stays cheap enough to run over every command and part
 * on each keystroke, and the ranking it produces matches how a palette should feel.
 */

const BOUNDARY = /[\s\-_/.]/;

/**
 * Score `query` against `text`. Returns `null` when `query` is not a subsequence
 * of `text`; otherwise a non-negative-ish score where higher means a better match.
 * An empty query returns 0 (it matches everything, with no preference).
 */
export function fuzzyScore(query: string, text: string): number | null {
  const q = query.toLowerCase();
  const t = text.toLowerCase();
  if (q.length === 0) return 0;

  let qi = 0;
  let score = 0;
  let prevMatch = -2; // so the first match is never counted as "consecutive"
  for (let ti = 0; ti < t.length && qi < q.length; ti++) {
    if (t[ti] !== q[qi]) continue;
    let bonus = 1;
    if (ti === prevMatch + 1) bonus += 2; // adjacent to the previous hit: a run
    if (ti === 0 || BOUNDARY.test(t[ti - 1])) bonus += 3; // at a word boundary
    score += bonus;
    prevMatch = ti;
    qi++;
  }

  if (qi < q.length) return null; // ran out of text before consuming the query
  // Prefer a tighter candidate: a small penalty per character length so an exact
  // short title outranks the same subsequence buried in a long one.
  return score - t.length * 0.01;
}

/**
 * Score `query` against several fields (e.g. a part's name, MPN, manufacturer,
 * category) and return the strongest match, or `null` when no field matches.
 */
export function fuzzyScoreFields(
  query: string,
  fields: Array<string | null | undefined>,
): number | null {
  let best: number | null = null;
  for (const field of fields) {
    if (!field) continue;
    const s = fuzzyScore(query, field);
    if (s !== null && (best === null || s > best)) best = s;
  }
  return best;
}
