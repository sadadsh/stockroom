/**
 * The interface-letter gate: Unicode U+0079 - the lower-case letter after x - must not appear in
 * text this application authors for a person to read.
 *
 * See `lib/interfaceTerms.ts` for the rule itself, its reasoning, and the approved replacement for
 * each blocked term. This file is the enforcement. `copy.coverage.test.ts` already proves that a
 * user-visible string GOES THROUGH the copy layer; this proves that what goes through it obeys the
 * letter rule. The two are deliberately adjacent: coverage decides what counts as interface text,
 * and this reads the same sources so the two can never disagree about the boundary.
 *
 * --- WHAT IS READ, and why it is read this way -------------------------------------------------
 *
 * The copy DEFAULTS in the source, plus the committed copy overrides. Nothing is hand-listed: a
 * string is in scope because of the SHAPE it is written in, so a label added tomorrow is checked
 * the moment it lands rather than when somebody remembers to come back here. Four shapes carry a
 * copy default in this tree, and all four are read:
 *
 *  1. `<Text id="...">Some text</Text>` and the four other copy-carrying primitives, whose `id`
 *     prop their types REQUIRE, so their string children ARE the default. Both the plain JSX-text
 *     form and the `{"..."}` brace-string form.
 *  2. `useText(id, "default")` and `useCopyFormatter(id, "default")` - the string forms, for copy
 *     that lives in an attribute (`aria-label`, `placeholder`, `title`) where a wrapper cannot go.
 *     This is what stops a glyph from becoming a loophole: an icon-only control still needs an
 *     accessible name and a tooltip carrying the complete action, that text is interface text, and
 *     it is read here exactly like a visible label.
 *  3. A string prop paired with its own copy id in the same element or object literal - the
 *     `label`/`labelId`, `title`/`titleId`, `hint`/`hintId`, `label`/`copyId` and prefixed forms of
 *     those (`metLabel`/`metLabelId`) families, which
 *     resolve through `<Text id={thatId}>{thatString}</Text>` at the render site.
 *  4. `lib/copy.overrides.ts` - the committed rewordings, which ship and are read on every render
 *     for everyone. An override that reintroduced the letter would defeat every fix in the source.
 *     ONE EXEMPTION, and it is the owner's own (plan 1.5, the 2026-08-06 amendment): an id listed in
 *     that module's `OWNER_AUTHORED_COPY_IDS` was typed by the OWNER through the Design Mode editor,
 *     and the rule exists to stop this application authoring blocked words FOR them, not to overrule
 *     them inside their own product. The exemption is keyed on the id and on nothing else, so a
 *     rewording hand-edited into the map - or written by an agent through any other route - stays
 *     bound. `POST /api/dev/save` is what writes the record, and it drops any id that does not carry
 *     an override, so the record cannot become a standing exemption for a string that is not there.
 *
 * --- WHAT IS NOT READ, and why ----------------------------------------------------------------
 *
 * PART DATA. Manufacturer part numbers, manufacturer names, distributor descriptions, provider
 * names, class names off a provider, spec labels and spec values off the wire, and file names all
 * originate outside this codebase. Rewording a manufacturer's description would corrupt the record
 * and an MPN is an identifier that must never be altered, so none of it is scanned. Two mechanical
 * consequences:
 *
 *  - `{name}` placeholders are BLANKED before the check. A named placeholder resolves to data at
 *    render, so in `"Overrides {value} from {source}"` the words are checked and `{value}` /
 *    `{source}` are not. The names themselves are code identifiers wired to a values object, not
 *    text anybody reads.
 *  - Copy IDs are never read, only the defaults. An id is the stable persistence key for a
 *    rewording; renaming one would silently drop a committed override.
 *
 * Test files and fixtures are not scanned: a fixture stands in for a provider payload, which is
 * data. `lib/captureRequirements.ts`'s label table is not copy either - it names EDA tools and asset
 * kinds ("KiCad Symbol", "Altium Footprint") as registry vocabulary, and `copy.coverage.test.ts`
 * already records why routing that through the copy layer would let a rewording change what a file
 * IS.
 */
import { describe, it, expect } from "vitest";
import {
  APPROVED_PRODUCT_TERMS,
  BLOCKED_TERMS,
  INDUSTRY_TERMS,
  suggestReplacement,
} from "./interfaceTerms";
// The allowlist and the judgement moved to `lib/letterRule.ts` so Design Mode's copy editor can run
// the SAME rule live on text the owner types (plan 1.5). They are imported rather than restated:
// the allowlist is the one place this rule can be defeated wholesale, and a second copy of it in the
// editor would be a second place to defeat it that this gate could not see.
import { judgedText, PROPER_NAMES } from "./letterRule";
// The owner-authored provenance record, written into `copy.overrides.ts` by POST /api/dev/save. It
// is imported rather than parsed out of the raw text so that renaming the export breaks this gate
// loudly instead of turning the exemption into a silently-empty set.
import { COPY_OVERRIDES, OWNER_AUTHORED_COPY_IDS } from "./copy.overrides";

const RAW = import.meta.glob("/src/**/*.{ts,tsx}", {
  query: "?raw",
  eager: true,
  import: "default",
}) as Record<string, string>;

/**
 * ALLOWLIST, CATEGORY 1 - a proper name that is not ours to reword. Declared in `lib/letterRule.ts`
 * and imported above; the reasoning for the single entry lives beside it there.
 *
 * Named here so this file still reads as the statement of the two categories, and asserted below so
 * the move cannot have quietly emptied it.
 */
void PROPER_NAMES;

/**
 * ALLOWLIST, CATEGORY 2 - a standardised technical term with no synonym.
 *
 * Deliberately a SEPARATE category from the proper names above, because the argument is different: a
 * trade name is exempt because it belongs to someone else, whereas these are exempt because the
 * industry has already fixed the word and every candidate replacement either names a different
 * entity or is a coinage. The terms and the one-line reason for each live in `interfaceTerms.ts`
 * beside the term map, so the document and the gate cannot drift apart.
 *
 * Two guards keep this from becoming the rule's escape hatch. `holds the industry allowlist to a
 * short, argued list` below caps its length, so a fifth entry has to be argued for rather than
 * appended. And the allowlist only makes a word PERMITTED, never required: where a glyph or the
 * asset itself can carry the meaning, that is still the better answer.
 */
const INDUSTRY_WORDS: readonly string[] = INDUSTRY_TERMS.map((t) => t.term);

const BLOCKED = "y";

/** Blank comments in place, preserving offsets so reported line numbers stay true. */
function blankComments(src: string): string {
  const withoutBlocks = src.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, " "));
  return withoutBlocks
    .split("\n")
    .map((line) => {
      const at = line.indexOf("//");
      if (at < 0) return line;
      // A `//` inside a URL or a string is not a comment. The characters before it decide.
      if (at > 0 && (line[at - 1] === ":" || line[at - 1] === '"' || line[at - 1] === "'")) {
        return line;
      }
      return line.slice(0, at) + " ".repeat(line.length - at);
    })
    .join("\n");
}

const SOURCE: ReadonlyArray<readonly [string, string]> = Object.entries(RAW).filter(
  ([path]) => !/\.(test|spec)\.tsx?$/.test(path),
);

// The primitives whose types REQUIRE a copy id, so their string children are the copy default.
const COPY_TAG = "Text|EmptyState|LoadingState|WarningState|UnavailableState|ErrorState|InlineNotice";
// A prop name that carries a copy id, so its sibling string prop is a copy default.
const ID_PROP = "[A-Za-z]*(?:copyId|titleId|hintId|labelId|CopyId|TitleId|HintId|LabelId)";

/** Every shape a copy default is written in. Group 1 is the default text. */
const DEFAULT_SHAPES: ReadonlyArray<{ readonly what: string; readonly re: RegExp }> = [
  // <Text id="...">Some text</Text> - the JSX text child of a copy primitive.
  { what: "<Text> child", re: new RegExp(`<(?:${COPY_TAG})\\b[^>]*>([^<>{}]+)<`, "g") },
  // <Text id="..." values={...}>{"Some {count} text"}</Text> - the brace-string child.
  {
    what: "<Text> string child",
    re: new RegExp(`<(?:${COPY_TAG})\\b[^>]*>\\s*\\{"((?:[^"\\\\]|\\\\.)*)"\\}`, "g"),
  },
  // useText("id", "default") / useCopyFormatter("id", "default") - the attribute / callback forms.
  {
    what: "useText / useCopyFormatter default",
    re: /use(?:Text|CopyFormatter)\(\s*(?:"(?:[^"\\]|\\.)*"|[A-Za-z_$][\w.$]*)\s*,\s*"((?:[^"\\]|\\.)*)"/g,
  },
];

/**
 * An object literal, destructured parameter list, or opening tag that carries a copy id, so its
 * `label` / `title` / `hint` string is that id's default. Scanned in two passes because the pairing
 * is what makes the string copy: a bare `label="..."` on some other component may be a value.
 *
 * The prefixed forms matter - `metLabel` beside `metLabelId` is the same contract as `label` beside
 * `labelId`, and a gate that only knew the unprefixed names let one through. `=` is accepted as
 * well as `:` so that a DEFAULTED PARAMETER counts: `RetryAction({ id = "state.retry",
 * label = "Rerun" })` declares its default in the signature, which is a copy default like any
 * other, and it is exactly the shape that hid the app's one shared retry label from an earlier pass.
 */
// A dotted string is what a copy id looks like, which is how a bare `id` earns its place here
// without dragging in every DOM `id` attribute in the tree.
const COPY_ID_VALUE = `"[A-Za-z0-9_-]+(?:\\.[A-Za-z0-9_-]+)+"`;
const ID_PAIRED_HOLDER = new RegExp(
  `\\{[^{}]*(?:(?:${ID_PROP})\\s*[=:]|\\bid\\s*[=:]\\s*${COPY_ID_VALUE})[^{}]*\\}` +
    `|<[A-Z][\\w.]*\\s[^>]*(?:${ID_PROP})=[^>]*>`,
  "g",
);
const ID_PAIRED_STRING = /\b[A-Za-z]*(?:label|title|hint|Label|Title|Hint)\s*[:=]\s*"((?:[^"\\]|\\.)*)"/g;

// The committed rewordings: `"copy.id": "the reworded text"`. Group 1 is the ID, group 2 the text -
// the id is captured for ONE purpose, the owner-authored exemption below, and is never judged.
const OVERRIDE_ENTRY = /"((?:[^"\\]|\\.)*)"\s*:\s*"((?:[^"\\]|\\.)*)"/g;

const OVERRIDES_PATH = "/src/lib/copy.overrides.ts";
const OWNER_AUTHORED: ReadonlySet<string> = new Set(OWNER_AUTHORED_COPY_IDS);

interface Offence {
  readonly where: string;
  readonly what: string;
  readonly text: string;
}

function lineOf(src: string, index: number): number {
  return src.slice(0, index).split("\n").length;
}

/**
 * What the rule actually judges: the default with its data holes and its allowed terms removed.
 * A string is an offender when THIS still carries the letter.
 *
 * `lib/letterRule.ts` is the implementation, shared with the live editor - see the import above.
 */
const judged = judgedText;

/**
 * The committed rewordings, with the owner's own text exempted BY ID.
 *
 * `ownerAuthored` is a parameter rather than a module read so the two halves of the exemption can be
 * proven separately below: the same entry is an offence when its id is absent from the record and is
 * not one when it is present. The gate itself always passes the real record.
 */
function overrideOffences(
  path: string,
  src: string,
  ownerAuthored: ReadonlySet<string>,
): Offence[] {
  const out: Offence[] = [];
  OVERRIDE_ENTRY.lastIndex = 0;
  for (let m = OVERRIDE_ENTRY.exec(src); m; m = OVERRIDE_ENTRY.exec(src)) {
    const [, id, text] = m;
    // The owner typed this one themselves through Design Mode (plan 1.5). Everything the app
    // authors - including a rewording hand-edited into this map - has no id in the record and is
    // judged exactly as before.
    if (ownerAuthored.has(id)) continue;
    if (judged(text).includes(BLOCKED)) {
      out.push({
        where: `${path}:${lineOf(src, m.index)}`,
        what: "committed override",
        text: text.trim(),
      });
    }
  }
  return out;
}

function offences(
  path: string,
  raw: string,
  ownerAuthored: ReadonlySet<string> = OWNER_AUTHORED,
): Offence[] {
  const src = path.endsWith(".tsx") ? blankComments(raw) : raw;
  if (path === OVERRIDES_PATH) return overrideOffences(path, src, ownerAuthored);

  const out: Offence[] = [];
  for (const { what, re } of DEFAULT_SHAPES) {
    re.lastIndex = 0;
    for (let m = re.exec(src); m; m = re.exec(src)) {
      if (judged(m[1]).includes(BLOCKED)) {
        out.push({ where: `${path}:${lineOf(src, m.index)}`, what, text: m[1].trim() });
      }
    }
  }

  if (path.endsWith(".tsx")) {
    ID_PAIRED_HOLDER.lastIndex = 0;
    for (let holder = ID_PAIRED_HOLDER.exec(src); holder; holder = ID_PAIRED_HOLDER.exec(src)) {
      ID_PAIRED_STRING.lastIndex = 0;
      for (let m = ID_PAIRED_STRING.exec(holder[0]); m; m = ID_PAIRED_STRING.exec(holder[0])) {
        if (judged(m[1]).includes(BLOCKED)) {
          out.push({
            where: `${path}:${lineOf(src, holder.index)}`,
            what: "copy-id-paired label / title / hint",
            text: m[1].trim(),
          });
        }
      }
    }
  }
  return out;
}

/** The words that carry the letter, so a failure names the fix rather than the symptom. */
function advice(text: string): string {
  const words = judged(text).match(/[A-Za-z][A-Za-z-]*/g) ?? [];
  const notes: string[] = [];
  for (const w of words) {
    if (!w.includes(BLOCKED)) continue;
    const entry = suggestReplacement(w);
    notes.push(entry ? `${w} -> ${entry.replacement}` : `${w} -> no recorded replacement`);
  }
  return notes.length > 0 ? ` [${[...new Set(notes)].join("; ")}]` : "";
}

describe("the interface-letter rule on the copy layer", () => {
  it("reads a non-trivial number of copy sources (the glob is wired)", () => {
    // A silently-empty glob would turn the assertion below into a false pass.
    const withCopy = SOURCE.filter(([, raw]) => /<Text\b|useText\(|useCopyFormatter\(/.test(raw));
    expect(withCopy.length).toBeGreaterThan(60);
  });

  it("finds every shape a copy default is written in", () => {
    // Guards the shape regexes themselves: if a rename broke one, it would match nothing and this
    // gate would pass by finding no strings to check rather than by the strings being clean.
    const found = new Map<string, number>();
    for (const [, raw] of SOURCE) {
      const src = blankComments(raw);
      for (const { what, re } of DEFAULT_SHAPES) {
        re.lastIndex = 0;
        for (let m = re.exec(src); m; m = re.exec(src)) {
          found.set(what, (found.get(what) ?? 0) + 1);
        }
      }
      ID_PAIRED_HOLDER.lastIndex = 0;
      for (let h = ID_PAIRED_HOLDER.exec(src); h; h = ID_PAIRED_HOLDER.exec(src)) {
        ID_PAIRED_STRING.lastIndex = 0;
        for (let m = ID_PAIRED_STRING.exec(h[0]); m; m = ID_PAIRED_STRING.exec(h[0])) {
          found.set("copy-id-paired", (found.get("copy-id-paired") ?? 0) + 1);
        }
      }
    }
    for (const what of [...DEFAULT_SHAPES.map((s) => s.what), "copy-id-paired"]) {
      expect(found.get(what) ?? 0, `no copy default matched the ${what} shape`).toBeGreaterThan(0);
    }
  });

  it("keeps U+0079 out of every copy default and committed override", () => {
    const found = SOURCE.flatMap(([path, raw]) => offences(path, raw)).map(
      (o) => `${o.where} (${o.what}) ${JSON.stringify(o.text)}${advice(o.text)}`,
    );
    expect(found).toEqual([]);
  });

  /**
   * THE OWNER-AUTHORED EXEMPTION, both halves (plan 1.5).
   *
   * The same committed entry is judged twice: once with its id absent from the provenance record and
   * once with it present. If only the first case existed the exemption could be a no-op and this
   * would still pass; if only the second existed the rule could have been switched off wholesale for
   * `copy.overrides.ts` and this would still pass. Together they pin exactly one behaviour.
   *
   * FAILS IF: the exemption stops being keyed on the id (an unlisted rewording would go unjudged), or
   * the record stops being consulted (owner-typed text would be reported as an application offence).
   */
  it("exempts an owner-authored override by id, and only by id", () => {
    const module = 'export const COPY_OVERRIDES = {\n  "detail.summary": "Summary"\n};\n';

    const agentAuthored = offences(OVERRIDES_PATH, module, new Set());
    expect(agentAuthored.map((o) => o.text)).toEqual(["Summary"]);
    expect(agentAuthored[0]?.what).toBe("committed override");

    const ownerAuthored = offences(OVERRIDES_PATH, module, new Set(["detail.summary"]));
    expect(ownerAuthored).toEqual([]);

    // Keyed on THIS id: a record naming some other rewording exempts nothing here.
    expect(offences(OVERRIDES_PATH, module, new Set(["detail.other"]))).toEqual(agentAuthored);
  });

  it("cannot exempt a copy id that carries no committed override", () => {
    // The record's only cap. An id with no rewording above it has nothing to exempt, so a listing for
    // one is either stale or an attempt to pre-authorise text nobody has written. `POST /api/dev/save`
    // drops those on the way in; this is the same claim held against the file as committed.
    const dangling = OWNER_AUTHORED_COPY_IDS.filter((id) => COPY_OVERRIDES[id] === undefined);
    expect(dangling).toEqual([]);
  });

  it("every recorded replacement is itself clear of the letter", () => {
    // A term map that suggested an offending replacement would launder the rule it exists to serve.
    // `replacement` is the machine-usable text - what actually gets written - so it is held to the
    // same standard as a shipped label. `note` is reasoning for a reader of the source and is not.
    const bad = BLOCKED_TERMS.filter((t) => t.replacement.includes(BLOCKED)).map(
      (t) => `${t.term} -> ${t.replacement}`,
    );
    expect(bad).toEqual([]);
  });

  it("records a replacement for each term the owner named", () => {
    // The vocabulary the rule was handed down with. If one of these fell out of the map, the lint
    // would still catch the letter but would stop telling anyone what to write instead.
    const missing = [
      "Verify",
      "Display",
      "Copy",
      "Summary",
      "Apply",
      "Quantity",
      "Category",
      "Library",
    ].filter((word) => suggestReplacement(word) === undefined);
    expect(missing).toEqual([]);
  });

  it("accounts for every term the owner named, in exactly one of the two lists", () => {
    // `Symbol` and `Compatibility` moved from the term map to the industry allowlist, because both
    // proposed replacements named something else: `Schematic` is the sheet rather than the part on
    // it, and `Interchange` upgrades a compatibility claim into an equivalence this product is
    // explicit about NOT having validated. A term must sit in one list or the other, never both -
    // an entry in both would let the map advise a replacement for a word that is already permitted.
    const allowed = new Set(INDUSTRY_WORDS.map((w) => w.toLowerCase()));
    const unaccounted = ["Symbol", "Compatibility", "Courtyard", "Layer"].filter(
      (word) => !allowed.has(word.toLowerCase()),
    );
    expect(unaccounted).toEqual([]);
    const inBoth = INDUSTRY_WORDS.filter((word) => suggestReplacement(word) !== undefined);
    expect(inBoth).toEqual([]);
  });

  it("holds the industry allowlist to a short, argued list", () => {
    // The allowlist is the one place the rule can be defeated wholesale, so its SIZE is part of the
    // contract: four standardised terms is the argued set, and a fifth needs this number raised
    // deliberately rather than a line appended quietly. Every entry also has to carry its reason,
    // since an exemption with no stated ground is indistinguishable from a word somebody disliked.
    expect(INDUSTRY_TERMS.length).toBeLessThanOrEqual(6);
    const unreasoned = INDUSTRY_TERMS.filter((t) => t.why.trim().length < 40).map((t) => t.term);
    expect(unreasoned).toEqual([]);
  });

  it("holds approved product vocabulary to a short, argued list", () => {
    expect(APPROVED_PRODUCT_TERMS.length).toBeLessThanOrEqual(6);
    const unreasoned = APPROVED_PRODUCT_TERMS
      .filter((term) => term.why.trim().length < 40)
      .map((term) => term.term);
    expect(unreasoned).toEqual([]);
  });

  it("shares one allowlist with the live editor, and that allowlist is not empty", () => {
    // The judgement moved to `lib/letterRule.ts` so Design Mode can run it on text the owner types.
    // Killing mutation: return the text unchanged from `judgedText`, or empty either allowlist
    // category. Both would make the gate above pass by exempting everything, which is precisely the
    // failure a shared allowlist risks - so the exemptions are asserted to still exempt, and the
    // words around them are asserted to still be judged.
    expect(PROPER_NAMES).toContain("DigiKey");
    expect(judged("DigiKey")).not.toContain(BLOCKED);
    expect(judged("Symbol")).not.toContain(BLOCKED);
    expect(judged("{quantity} parts")).not.toContain(BLOCKED);
    expect(judged("Apply")).not.toContain(BLOCKED);
    expect(judged("Only")).toContain(BLOCKED);
    expect(judged("Layered")).toContain(BLOCKED);
  });
});
