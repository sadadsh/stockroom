/**
 * Copy coverage gate: a user-visible string on a covered surface must go through the copy layer.
 *
 * Dev Mode can only reword what the copy layer resolves. A label written straight into the JSX is
 * invisible to it, and the failure is silent - the panel simply has nothing to offer for that
 * element, and nobody finds out until they try to change the word. This is the gate that makes that
 * loud, at the one moment it is cheap to fix.
 *
 * --- THE RULE, and why it is not noise ---------------------------------------------------------
 *
 * Every shape below is checked, and each was chosen because it is UNAMBIGUOUS in source text. A
 * heuristic that has to guess is a heuristic people learn to ignore.
 *
 *  1. A JSX TEXT RUN: the text between a tag-closing `>` and the next `<` that opens a tag. It is
 *     an offender when it contains two consecutive letters and none of the characters that only
 *     appear in code (`(){};=$"'` and friends). That exclusion is what removes the false positives
 *     a naive `>...<` scan drowns in: a `=>` arrow, a `useState<Foo>(bar)` type argument, and the
 *     `) : cond ? (` spine of a JSX ternary all carry at least one of them. Comments are blanked
 *     first, so prose in a `//` or `/* *\/` note is never convicted. A run that STARTS with a list
 *     separator is object-literal punctuation (`<Icon />,\n  projects:`), not a sentence.
 *
 *     A run is fine when its element is one of the copy-carrying primitives (`<Text>` and the five
 *     product states, whose `id` prop is REQUIRED by their types, so their children ARE the copy
 *     default) or when the element's opening tag carries a `copyId=` - the copy layer's one prop
 *     name in this codebase, so matching it textually cannot mean anything else.
 *
 *  1b. THE SAME RUN, STARTING AFTER AN EXPRESSION. `<>All {total} components have every file they
 *     need.</>` renders a sentence and routes none of it, because the run begins after the `}` that
 *     closed `{total}` rather than after a `>`. Anchoring only on `>` made the gate depend on where
 *     a value happens to sit in the sentence, which is not a distinction a reader of the interface
 *     can perceive - so the `}` form is read exactly like the `>` form, with one extra question.
 *
 *     THE EXTRA QUESTION is whether that `}` closed a JSX expression at all, because most closing
 *     braces in a `.tsx` file close a function body or an object literal, and the text after those
 *     is the next declaration (`}\n\nexport function SegmentedControl<T extends string>`). It is
 *     answered by walking back from the brace's partner: step over any adjacent `{...}` container,
 *     pass over JSX text, and the run counts only if that walk lands on a tag-closing `>`. A body
 *     brace fails it at the `)` or `=` that introduced the body, and a type argument list fails it
 *     because `Record<` glues its `<` to an identifier where a tag never does. That walk also
 *     yields the enclosing tag, so the `<Text>` and `copyId=` exemptions above apply unchanged.
 *
 *  2. A LITERAL `aria-label="..."` or `placeholder="..."`. A double-quoted JSX attribute value is a
 *     string literal, full stop - there is no expression form to confuse it with. These are the two
 *     attributes that carry text a person reads or hears and that a wrapper element cannot reach,
 *     which is exactly what `useText` exists for. Their EXPRESSION forms are shape 5.
 *
 *  3. A TOAST MESSAGE. `toast(message, tone?)` takes a resolved STRING, so no wrapper element can
 *     reach it and a literal there is invisible to Dev Mode exactly like a literal in the JSX. The
 *     whole first argument is read, not just its simplest form, because the message is as often
 *     `cond ? "one thing" : "another"` as it is a bare literal. The component resolves each side
 *     through `useText` / `useCopyFormatter` and passes the result.
 *
 *  4. A CONDITIONAL JSX CHILD. `{usable ? "Prepared" : "Incomplete"}` renders two labels and routes
 *     neither: the brace makes it an expression, so shape 1's `>text<` scan never sees it. Read only
 *     for a literal in BRANCH position - the value the conditional evaluates to, sitting directly
 *     after its `?` or its `:`. That is the one place a bare string inside an expression is
 *     unambiguously the text being rendered, which is what keeps an enum operand (`x === "dark"`) and
 *     a call argument (`fmt("n")`) out of it. Parentheses do not hide a branch: a formatter adds them
 *     the moment a branch wraps onto its own line, so `busy ? ("A") : ("B")` reads as the same code it
 *     is.
 *
 *  5. A `title=`, `aria-label=` or `placeholder=` VALUE, in either form. `title` was checked first,
 *     having been skipped before on the ground that half the `title` props in this tree belong to
 *     components taking a `title` STRING plus a separate `copyId`. That was the right worry and the
 *     wrong conclusion: those are exempted by the PAIRING instead, the same way a `copyId=` on an
 *     element exempts its text run in shape 1. What is left after that exemption is a real browser
 *     tooltip, which is prose a person reads and often the only place an icon-only control states
 *     its complete action.
 *
 *     `aria-label` and `placeholder` joined it because shape 2 only ever bound their LITERAL form,
 *     which left `aria-label={busy ? "Stop" : "Start"}` and `` aria-label={`Open ${label}`} ``
 *     outside the gate - and an accessible name is exactly the text a screen-reader user hears, so
 *     it is interface prose as much as a visible label is, and more, since it is the only text those
 *     users get. A template whose only literal content is punctuation or a separator authors no
 *     words and is not convicted: the `${...}` holes are blanked before the judgement, the same way
 *     the letter rule blanks its named placeholders.
 *
 * Shapes 3, 4 and 5 also close a hole in the LETTER rule next door, which reads whatever the copy
 * layer holds: a string that never entered the copy layer was never checked for the letter either.
 *
 * --- THE BOUNDARY ------------------------------------------------------------------------------
 *
 * `COVERED_SURFACES` is the enforced list and `EXCLUDED_SURFACES` is what is carved back out of it.
 * Together they are the honest boundary: every rendering surface the product has - the routes, the
 * opened component and its sheets, settings and its sections, the STM workbenches, the provider
 * trip, intake and import, the modals, the shared primitives, the rail and the pickers - is now
 * inside, so coverage grows by a new file LANDING rather than by someone remembering to list it.
 * Anything carved out is carved out with a reason written next to it, because a boundary that is
 * only a list is a boundary that drifts.
 *
 * Dev Mode's own surfaces (`DevPanel` / `DevInspector`) are excluded: they are the editor, and
 * routing the editor's labels through the surface it edits means one bad override can make the
 * editor unusable and unfixable. `lib/devMode.tsx` and `lib/copy.tsx` are the same chrome and are
 * simply not listed, since `lib/` is covered file by file rather than whole.
 *
 * `lib/captureRequirements.ts` is also not listed - and could not be, since the glob reads only
 * `.tsx`. Its one label table names EDA tools and asset kinds ("KiCad Symbol", "Altium Footprint"),
 * which are registry vocabulary rendered as data, in the same class as a provider label or a spec
 * key. Routing data through the copy layer would let a rewording change what a file IS. The
 * surfaces that show a requirement to a person pass those labels as the copy DEFAULT for their own
 * id, so the wording stays reachable without the table itself becoming copy.
 *
 * Third-party provider pages, OS dialogs and other applications' windows are outside because they
 * are not ours to edit. Nothing here claims otherwise.
 */
import { describe, it, expect } from "vitest";
import { copyPlaceholders } from "./copyPlaceholders";

const RAW = import.meta.glob("/src/**/*.tsx", {
  query: "?raw",
  eager: true,
  import: "default",
}) as Record<string, string>;

/**
 * The files this gate enforces. A trailing slash covers a whole directory.
 *
 * Every rendering surface the product has now lives under `components/` or `pages/`, so those are
 * listed WHOLE rather than file by file. A flat list of ninety-odd paths is a list nobody updates:
 * the point of the directory form is that a new component is enforced the moment it lands, instead
 * of being coverable only by someone remembering to come back here.
 */
const COVERED_SURFACES: readonly string[] = [
  "/src/components/",
  "/src/pages/",
  "/src/App.tsx",
  "/src/main.tsx",
  "/src/lib/addPart.tsx",
  "/src/lib/router.tsx",
  "/src/lib/theme.tsx",
  "/src/lib/toast.tsx",
];

/**
 * Carved back OUT of the directories above, and each one for a stated reason. This list is the
 * honest part of the boundary: without it the directory form would silently claim files that this
 * pass did not route, which is the failure mode a coverage gate exists to prevent.
 */
const EXCLUDED_SURFACES: readonly string[] = [
  // Dev Mode's own editor chrome. Routing the editor's labels through the surface it edits means one
  // bad override can make the editor unusable AND unfixable, since fixing it needs the editor.
  "/src/components/DevPanel.tsx",
  "/src/components/DevInspector.tsx",
];

function covered(path: string): boolean {
  if (EXCLUDED_SURFACES.includes(path)) return false;
  return COVERED_SURFACES.some((s) => (s.endsWith("/") ? path.startsWith(s) : path === s));
}

const SOURCE: ReadonlyArray<readonly [string, string]> = Object.entries(RAW)
  .filter(([path]) => !/\.(test|spec)\.tsx$/.test(path))
  .filter(([path]) => covered(path));

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

// The primitives whose types REQUIRE a copy id, so their string children are the copy default.
const COPY_TAGS = new Set([
  "Text",
  "EmptyState",
  "LoadingState",
  "WarningState",
  "UnavailableState",
  "ErrorState",
  "InlineNotice",
]);

const JSX_TEXT = />([^<>{}]+)<(?=[A-Za-z/])/g;
/** The same run one character earlier in the sentence: `{total} components have every file.` */
const EXPRESSION_TEXT = /\}([^<>{}]+)<(?=[A-Za-z/])/g;
// Characters that appear in code and never in a UI sentence in this tree.
const CODE_CHARS = /[(){};=$"'`&|!?[\]\\]/;
const LITERAL_ATTR = /\s(aria-label|placeholder)="([^"]*)"/g;

interface Offence {
  where: string;
  text: string;
}

function lineOf(src: string, index: number): number {
  return src.slice(0, index).split("\n").length;
}

/** A run's text if it reads as a sentence rather than as code, else null. */
function sentence(run: string): string | null {
  if (CODE_CHARS.test(run)) return null;
  const text = run.trim();
  if (text.length < 2 || !/[A-Za-z]{2}/.test(text)) return null;
  if (/^[,:;]/.test(text)) return null;
  return text;
}

/** Whether the element whose opening tag is `tag` already carries this run through the copy layer. */
function tagCarriesCopy(tag: string): boolean {
  const name = /^<\/?([A-Za-z][\w.]*)/.exec(tag)?.[1];
  if (name !== undefined && COPY_TAGS.has(name)) return true;
  return tag.includes("copyId=");
}

function unroutedText(path: string, raw: string): Offence[] {
  const src = blankComments(raw);
  const out: Offence[] = [];
  JSX_TEXT.lastIndex = 0;
  for (let m = JSX_TEXT.exec(src); m; m = JSX_TEXT.exec(src)) {
    const gt = m.index;
    const before = src[gt - 1];
    // `=>`, `->`, `<<`, `>>`: the `>` is an operator, not a tag close.
    if (before === "=" || before === "-" || before === "<" || before === ">") continue;
    const text = sentence(m[1]);
    if (text === null) continue;
    const openAt = src.lastIndexOf("<", gt);
    if (openAt < 0) continue;
    const tag = src.slice(openAt, gt + 1);
    // A tag with no name is a fragment, whose runs shape 1b reads instead.
    if (!/^<\/?[A-Za-z][\w.]*/.test(tag)) continue;
    if (tagCarriesCopy(tag)) continue;
    out.push({ where: `${path}:${lineOf(src, gt)}`, text });
  }
  return out;
}

/** The index of the `{` that the `}` at `close` closes, or -1 if the walk falls off the front. */
function openBrace(src: string, close: number): number {
  let depth = 0;
  for (let i = close; i >= 0; i -= 1) {
    if (src[i] === "}") depth += 1;
    else if (src[i] === "{") {
      depth -= 1;
      if (depth === 0) return i;
    }
  }
  return -1;
}

/**
 * The tag-closing `>` that opens the child sequence the expression closed at `close` sits in, or -1
 * when that `}` closed something which is not a JSX child - a function body, an object literal, a
 * type. This is the whole basis of shape 1b, and it is a WALK rather than a pattern because the
 * question is what ENCLOSES the brace, which no amount of local context answers.
 *
 * From the brace's partner, step LEFT: over whitespace, over the JSX text of the same child sequence,
 * and over any adjacent `{...}` container, since `{a}{b} text<` is one sequence and not two. Landing
 * on a tag-closing `>` proves child position. Anything else is code, and ends the walk:
 *
 *  - a body or an object literal is introduced by `)`, `=`, `,`, `(` or `;`, every one of them a
 *    `CODE_CHAR`, so `function f() { ... }\n\nconst NEXT: Record<...>` is never read as a sentence;
 *  - `=>` and `->` are rejected exactly as shape 1 rejects them;
 *  - a type argument list closes with a `>` as well, and is told apart by where its `<` sits:
 *    `Record<` and `Attributes<HTMLButtonElement>` glue the `<` to an identifier, which a tag never
 *    does.
 */
function childRunStart(src: string, close: number): number {
  let i = openBrace(src, close);
  if (i < 0) return -1;
  while (i > 0) {
    i -= 1;
    const c = src[i];
    if (/\s/.test(c)) continue;
    if (c === "}") {
      i = openBrace(src, i);
      if (i < 0) return -1;
      continue;
    }
    if (c === ">") {
      if (src[i - 1] === "=" || src[i - 1] === "-") return -1;
      const openAt = src.lastIndexOf("<", i);
      if (openAt < 0) return -1;
      return /[A-Za-z0-9_$.]/.test(src[openAt - 1] ?? " ") ? -1 : i;
    }
    if (c === "<" || CODE_CHARS.test(c)) return -1;
  }
  return -1;
}

function unroutedExpressionText(path: string, raw: string): Offence[] {
  const src = blankComments(raw);
  const out: Offence[] = [];
  EXPRESSION_TEXT.lastIndex = 0;
  for (let m = EXPRESSION_TEXT.exec(src); m; m = EXPRESSION_TEXT.exec(src)) {
    const text = sentence(m[1]);
    if (text === null) continue;
    const gt = childRunStart(src, m.index);
    if (gt < 0) continue;
    const openAt = src.lastIndexOf("<", gt);
    if (openAt < 0) continue;
    if (tagCarriesCopy(src.slice(openAt, gt + 1))) continue;
    out.push({ where: `${path}:${lineOf(src, m.index)}`, text });
  }
  return out;
}

function unroutedAttributes(path: string, raw: string): Offence[] {
  const src = blankComments(raw);
  const out: Offence[] = [];
  LITERAL_ATTR.lastIndex = 0;
  for (let m = LITERAL_ATTR.exec(src); m; m = LITERAL_ATTR.exec(src)) {
    const value = m[2].trim();
    if (!/[A-Za-z]{2}/.test(value)) continue;
    out.push({ where: `${path}:${lineOf(src, m.index)}`, text: `${m[1]}="${value}"` });
  }
  return out;
}

// --- the shapes that used to bypass the copy layer entirely -------------------------------------
//
// A JSX text run and a literal attribute are found with one regex each because both are bounded by
// characters that cannot appear inside them. These three are not: a toast message runs to a
// top-level comma, a conditional child runs to a matching brace, and an attribute value can be
// either. So they share one small balanced scanner rather than three regexes that each guess at
// nesting. Shape 1b's walk sits with shape 1 above, because what it reads is still a text run.

/**
 * Text with two consecutive letters in it: what separates a sentence from a token or a class list.
 *
 * A template's `${...}` holes are blanked first, on the same ground the letter rule blanks its named
 * placeholders: what goes in the hole is a VALUE, and the identifier naming it is code. So
 * `` `${pin.name} · ${pad.position}` `` authors no words and is nothing for the copy layer to hold,
 * while `` `Supports ${n} of ${total}` `` authors two and is.
 */
function isProse(text: string): boolean {
  return /[A-Za-z]{2}/.test(text.replace(/\$\{[^}]*\}/g, " ").trim());
}

/**
 * Every string and template literal inside `src[from..to)` that sits at the TOP level of that slice,
 * paired with the character that introduced it. Nested literals - the `key="a"` of an element built
 * inside a `.map()`, a class list handed to a helper call - are skipped, because at depth they are
 * arguments to code rather than the text this expression evaluates to.
 *
 * The introducer is what lets a caller tell a rendered branch (`? "..."`, `: "..."`) from a
 * comparison operand (`=== "..."`), which is the whole basis of the conditional-child check.
 *
 * Depth counts `{}` and `[]` but NOT `()`, and the introducer skips back over any `(`. Parentheses
 * around a conditional branch are what a formatter adds the moment the branch wraps onto its own
 * line, so counting them would have made the gate depend on line length: `busy ? ("A") : ("B")` and
 * `busy ? "A" : "B"` are the same code and are now read the same way. An argument to a CALL is still
 * excluded, because the character before it is the last letter of the callee rather than a `?`.
 */
function topLevelLiterals(
  src: string,
  from: number,
  to: number,
): ReadonlyArray<{ readonly text: string; readonly at: number; readonly after: string }> {
  const out: { text: string; at: number; after: string }[] = [];
  let depth = 0;
  let prev = "";
  for (let i = from; i < to; i += 1) {
    const c = src[i];
    if (c === "[" || c === "{") depth += 1;
    else if (c === "]" || c === "}") depth -= 1;
    else if (c === '"' || c === "'" || c === "`") {
      const start = i;
      i += 1;
      // A template's `${...}` can itself hold a quoted string, so the walk has to step OVER each
      // hole to find the real closing backtick. Without that, the first quote inside the first hole
      // ends the literal early and the reported text is a torn fragment.
      while (i < to && src[i] !== c) {
        if (src[i] === "\\") i += 2;
        else if (c === "`" && src[i] === "$" && src[i + 1] === "{") i = matching(src, i + 1);
        else i += 1;
      }
      if (depth === 0) out.push({ text: src.slice(start + 1, i), at: start, after: prev });
      prev = c;
      continue;
    }
    if (!/[\s(]/.test(c)) prev = c;
  }
  return out;
}

/**
 * Whether a literal introduced by this character is TEXT BEING RENDERED rather than an operand.
 *
 * `mode === "dark" ? a : b` holds a string that nobody reads: it is an enum value being compared, and
 * convicting it would be the noise this gate exists to avoid. A literal that follows `?`, `:`, `&&`,
 * `||`, `??`, `+` or nothing at all is the value the expression evaluates TO, which is the text.
 */
const RENDERED_AFTER: ReadonlySet<string> = new Set(["", "?", ":", "&", "|", "(", ",", "+"]);

/** The index just past the bracket opened at `open`, or `src.length` if it never closes. */
function matching(src: string, open: number): number {
  const pairs: Record<string, string> = { "(": ")", "[": "]", "{": "}" };
  const close = pairs[src[open]];
  let depth = 0;
  for (let i = open; i < src.length; i += 1) {
    const c = src[i];
    if (c === '"' || c === "'" || c === "`") {
      i += 1;
      while (i < src.length && src[i] !== c) i += src[i] === "\\" ? 2 : 1;
      continue;
    }
    if (c === src[open]) depth += 1;
    else if (c === close) {
      depth -= 1;
      if (depth === 0) return i + 1;
    }
  }
  return src.length;
}

/**
 * The opening tag that encloses `at`, as a slice of source.
 *
 * Needed so that a `title=` can be exempted by a `copyId=` or `titleId=` on the SAME element, which
 * is what makes shape 5 quiet enough to enforce. Found by walking back through the `<`s and keeping
 * the first one whose tag actually reaches `at`: the nearest `<` is often an element nested in an
 * earlier attribute (`icon={<RefreshIcon />}`), and its tag closes long before the attribute wanted.
 */
function enclosingTag(src: string, at: number): string {
  for (let open = src.lastIndexOf("<", at); open >= 0; open = src.lastIndexOf("<", open - 1)) {
    if (!/[A-Za-z]/.test(src[open + 1] ?? "")) continue;
    let end = open;
    let depth = 0;
    for (let i = open; i < src.length; i += 1) {
      const c = src[i];
      if (c === '"' || c === "'" || c === "`") {
        i += 1;
        while (i < src.length && src[i] !== c) i += src[i] === "\\" ? 2 : 1;
        continue;
      }
      if (c === "{" || c === "(") depth += 1;
      else if (c === "}" || c === ")") depth -= 1;
      else if (c === ">" && depth <= 0) {
        end = i;
        break;
      }
    }
    if (end > at) return src.slice(open, end + 1);
  }
  return "";
}

/** `toast(...)` - the whole first argument, since the message is as often a ternary as a literal. */
const TOAST_CALL = /\btoast\s*\(/g;

function unroutedToasts(path: string, raw: string): Offence[] {
  const src = blankComments(raw);
  const out: Offence[] = [];
  TOAST_CALL.lastIndex = 0;
  for (let m = TOAST_CALL.exec(src); m; m = TOAST_CALL.exec(src)) {
    const open = src.indexOf("(", m.index);
    const close = matching(src, open) - 1;
    for (const lit of topLevelLiterals(src, open + 1, close)) {
      // Only the MESSAGE, which is the first argument: a tone (`"ok"`, `"err"`) is an enum, and an
      // action label past the second comma is a nested object and therefore not top-level here.
      if (src.slice(open + 1, lit.at).includes(",")) break;
      if (!RENDERED_AFTER.has(lit.after)) continue;
      if (!isProse(lit.text) || isData(path, lit.text)) continue;
      out.push({ where: `${path}:${lineOf(src, lit.at)}`, text: lit.text });
    }
  }
  return out;
}

/**
 * `>{ ... ? "a" : "b" }<` - a conditional standing where a text run would.
 *
 * Bounded on both sides by a tag, so it really is in child position, and read only for a literal in
 * BRANCH position at the top level of the expression. Those two conditions are what make this narrow
 * enough to trust: a JSX branch wraps its element in parentheses and so is never at the top level, an
 * attribute inside a chosen element arrives after an `=` rather than a `?`, and an argument to
 * anything called in the expression is a bracket deeper still.
 */
const CHILD_BRACE = /(?<=>)\s*\{/g;

function unroutedConditionalChildren(path: string, raw: string): Offence[] {
  const src = blankComments(raw);
  const out: Offence[] = [];
  CHILD_BRACE.lastIndex = 0;
  for (let m = CHILD_BRACE.exec(src); m; m = CHILD_BRACE.exec(src)) {
    const open = src.indexOf("{", m.index);
    const end = matching(src, open) - 1;
    if (!/^\s*</.test(src.slice(end + 1))) continue;
    if (!src.slice(open + 1, end).includes("?")) continue;
    for (const lit of topLevelLiterals(src, open + 1, end)) {
      if (lit.after !== "?" && lit.after !== ":") continue;
      if (!isProse(lit.text) || isData(path, lit.text)) continue;
      out.push({ where: `${path}:${lineOf(src, lit.at)}`, text: lit.text });
    }
  }
  return out;
}

/**
 * `title=`, `aria-label=` and `placeholder=` - the browser tooltip, the accessible name and the
 * in-field hint. Between them they are all the text an icon-only control has room to state fully in,
 * and the accessible name is the ONLY text a screen-reader user gets for such a control.
 *
 * Every value form counts, because every one of them reaches the same person: the plain
 * `title="..."`, the conditional `aria-label={busy ? "..." : "..."}` and the template
 * `` placeholder={`Search ${label}`} ``. Shape 2 above binds the literal form of the latter two and
 * always did; what is added here is their EXPRESSION forms, which it cannot see.
 *
 * A template whose literal halves are only punctuation or a separator authors no words, so the
 * `${...}` holes are blanked before judging - `` `${pin.name} · ${pad.position}` `` is a value with
 * a divider in it and nothing for the copy layer to hold.
 *
 * Exempt when the same opening tag carries a `copyId=` or a `titleId=`: that pairing IS the copy
 * layer for the components in this tree that take a `title` string plus its id, and the letter rule
 * next door already reads the pair as a copy default.
 */
const SPOKEN_ATTR = /\s(title|aria-label|placeholder)=/g;

function unroutedAttributeCopy(path: string, raw: string): Offence[] {
  const src = blankComments(raw);
  const out: Offence[] = [];
  SPOKEN_ATTR.lastIndex = 0;
  for (let m = SPOKEN_ATTR.exec(src); m; m = SPOKEN_ATTR.exec(src)) {
    const eq = m.index + m[0].length;
    const tag = enclosingTag(src, m.index);
    if (/\b(?:copyId|[A-Za-z]*[Tt]itleId)=/.test(tag)) continue;
    // The brace form: read INSIDE the braces, so the conditional's own branches are at top level.
    const brace = src[eq] === "{";
    const end = brace ? matching(src, eq) - 1 : src.indexOf('"', eq + 1) + 1;
    for (const lit of topLevelLiterals(src, brace ? eq + 1 : eq, end)) {
      if (!RENDERED_AFTER.has(lit.after)) continue;
      if (!isProse(lit.text) || isData(path, lit.text)) continue;
      out.push({ where: `${path}:${lineOf(src, lit.at)}`, text: `${m[1]}="${lit.text}"` });
    }
  }
  return out;
}

/**
 * The narrow, stated DATA exemptions for the three shapes above: a string that is not prose this
 * product authored but a code, an identifier or a value it renders. Keyed by file AND exact text, so
 * adding one is a decision about ONE string rather than a licence over a file, and so a reader can
 * check the reason against the site.
 *
 * The precedent is `lib/captureRequirements.ts`'s label table, which the header above records: routing
 * registry vocabulary through the copy layer would let a rewording change what a thing IS. A tooltip
 * built entirely from a value (`title={data.dblib}`, `title={row.mpn}`) never needs a line here,
 * because it holds no literal to convict in the first place - which is exactly why a file path must
 * never be routed: a rewording would corrupt the path.
 */
const DATA_STRINGS: readonly (readonly [string, string, string])[] = [
  [
    "/src/components/projects/ProjectDesignWorkbench.tsx",
    "SCH",
    "The Altium document kind, drawn as its file-extension code inside a glyph. Renaming it would say a .SchDoc is something other than what it is.",
  ],
  [
    "/src/components/projects/ProjectDesignWorkbench.tsx",
    "PRJ",
    "As above, for the .PrjPcb project document.",
  ],
  [
    "/src/components/stm/PinoutTable.tsx",
    "FT",
    "ST's own datasheet code for a five-volt-tolerant pin, printed in the tolerance column beside the pin it describes. It is read against ST's tables, not as a word.",
  ],
  [
    "/src/components/BulkImportSection.tsx",
    "595-TPD6E05U06RVZR\\n603-RC0402FR-07100RL\\nSN74LVC1G08DBVR",
    "Three real part numbers shown as the paste box's own example: two distributor stock numbers and one MPN, which is exactly the mix the box accepts. They are identifiers, and a reworded digit would demonstrate a part that does not exist.",
  ],
  [
    "/src/components/CompletePartModal.tsx",
    "https://...",
    "The shape of a URL, standing in the URL field to say what belongs there. It is syntax rather than prose, in the same class as the file paths this list already refuses to route: a rewording would describe an address form the field does not accept.",
  ],
];

const DATA_INDEX: ReadonlySet<string> = new Set(DATA_STRINGS.map(([path, text]) => `${path} ${text}`));

function isData(path: string, text: string): boolean {
  return DATA_INDEX.has(`${path} ${text}`);
}

describe("copy coverage on the covered surfaces", () => {
  it("scans a non-trivial number of covered files (the glob is wired)", () => {
    // A silently-empty glob would turn every assertion below into a false pass.
    expect(SOURCE.length).toBeGreaterThan(30);
  });

  it("routes every user-visible JSX text run through the copy layer", () => {
    const offences = SOURCE.flatMap(([path, raw]) => unroutedText(path, raw)).map(
      (o) => `${o.where} ${JSON.stringify(o.text)}`,
    );
    expect(offences).toEqual([]);
  });

  it("routes a text run that follows an expression, not only one that follows a tag", () => {
    const offences = SOURCE.flatMap(([path, raw]) => unroutedExpressionText(path, raw)).map(
      (o) => `${o.where} ${JSON.stringify(o.text)}`,
    );
    expect(offences).toEqual([]);
  });

  it("routes every literal aria-label and placeholder through the copy layer", () => {
    const offences = SOURCE.flatMap(([path, raw]) => unroutedAttributes(path, raw)).map(
      (o) => `${o.where} ${o.text}`,
    );
    expect(offences).toEqual([]);
  });

  it("routes every toast message through the copy layer", () => {
    const offences = SOURCE.flatMap(([path, raw]) => unroutedToasts(path, raw)).map(
      (o) => `${o.where} ${JSON.stringify(o.text)}`,
    );
    expect(offences).toEqual([]);
  });

  it("routes both sides of a conditional JSX child through the copy layer", () => {
    const offences = SOURCE.flatMap(([path, raw]) =>
      unroutedConditionalChildren(path, raw),
    ).map((o) => `${o.where} ${JSON.stringify(o.text)}`);
    expect(offences).toEqual([]);
  });

  it("routes every title, accessible name and placeholder through the copy layer", () => {
    const offences = SOURCE.flatMap(([path, raw]) => unroutedAttributeCopy(path, raw)).map(
      (o) => `${o.where} ${o.text}`,
    );
    expect(offences).toEqual([]);
  });

  it("keeps every data exemption checked rather than rubber-stamped", () => {
    // An exemption list that outlived its strings is how a coverage gate quietly stops covering. Each
    // line has to name a file this gate scans, a string that is still IN that file, and a reason.
    const stale: string[] = [];
    for (const [path, text, why] of DATA_STRINGS) {
      const raw = RAW[path];
      if (raw === undefined) stale.push(`${path}: not a scanned file`);
      else if (!raw.includes(`"${text}"`)) stale.push(`${path}: ${text} is no longer in the source`);
      if (why.trim().length < 40) stale.push(`${path}: ${text} has no stated reason`);
    }
    expect(stale).toEqual([]);
  });

  it("finds every shape it claims to find (the newer scanners are wired)", () => {
    // The failure mode of a scanner with a balanced walk in it is matching NOTHING after a rename, so
    // the gate would go green by finding no strings rather than by the strings being routed. These
    // are the shapes as they legitimately appear once routed: a resolved variable, not a literal.
    //
    // The after-an-expression run is counted through its WALK and not merely its regex, because the
    // walk is the part that could silently start answering -1 to everything. It counts every
    // child-position expression the walk resolves rather than only the convictable ones, since the
    // ROUTED shape of this hole is `{count} <Text id="...">label</Text>` - a run of one space, which
    // has to be found before it can be found innocent. Each attribute name is counted on its own, so
    // the pattern cannot be narrowed back to one of the three without this failing.
    const seen = { toast: 0, conditional: 0, expression: 0, title: 0, ariaLabel: 0, placeholder: 0 };
    for (const [, raw] of SOURCE) {
      const src = blankComments(raw);
      TOAST_CALL.lastIndex = 0;
      for (let m = TOAST_CALL.exec(src); m; m = TOAST_CALL.exec(src)) seen.toast += 1;
      CHILD_BRACE.lastIndex = 0;
      for (let m = CHILD_BRACE.exec(src); m; m = CHILD_BRACE.exec(src)) {
        const open = src.indexOf("{", m.index);
        const end = matching(src, open) - 1;
        if (src.slice(open + 1, end).includes("?")) seen.conditional += 1;
      }
      EXPRESSION_TEXT.lastIndex = 0;
      for (let m = EXPRESSION_TEXT.exec(src); m; m = EXPRESSION_TEXT.exec(src)) {
        if (childRunStart(src, m.index) >= 0) seen.expression += 1;
      }
      SPOKEN_ATTR.lastIndex = 0;
      for (let m = SPOKEN_ATTR.exec(src); m; m = SPOKEN_ATTR.exec(src)) {
        if (m[1] === "title") seen.title += 1;
        else if (m[1] === "aria-label") seen.ariaLabel += 1;
        else seen.placeholder += 1;
      }
    }
    expect(seen.toast, "no toast call found at all").toBeGreaterThan(10);
    expect(seen.conditional, "no conditional child found at all").toBeGreaterThan(20);
    expect(seen.expression, "no expression in child position found at all").toBeGreaterThan(50);
    expect(seen.title, "no title attribute found at all").toBeGreaterThan(20);
    expect(seen.ariaLabel, "no aria-label attribute found at all").toBeGreaterThan(20);
    expect(seen.placeholder, "no placeholder attribute found at all").toBeGreaterThan(5);
  });
});

// --- placeholder wellformedness ----------------------------------------------------------------
// The DEFAULT declares the required placeholder set, so a malformed default would declare nonsense
// and hold every override to it. Scanned across the WHOLE app, not just the covered surfaces: this
// is a correctness rule about the copy layer, not a coverage boundary.

const ALL_SOURCE: ReadonlyArray<readonly [string, string]> = Object.entries(RAW).filter(
  ([path]) => !/\.(test|spec)\.tsx$/.test(path),
);

// useText("id", "default") / useCopyFormatter("id", "default"), default on the same or next line.
const TEXT_DEFAULT = /use(?:Text|CopyFormatter)\(\s*"([^"]+)",\s*"((?:[^"\\]|\\.)*)"/g;
// <Text ...>{"..."}</Text>: the brace-carrying form, since a raw `{` cannot appear in JSX text.
const TEXT_STRING_CHILD = /<Text\b([^>]*)>\s*\{"((?:[^"\\]|\\.)*)"\}\s*<\/Text>/g;

describe("copy placeholder declarations", () => {
  it("every useText / useCopyFormatter default is a well-formed template", () => {
    const bad: string[] = [];
    for (const [path, raw] of ALL_SOURCE) {
      TEXT_DEFAULT.lastIndex = 0;
      for (let m = TEXT_DEFAULT.exec(raw); m; m = TEXT_DEFAULT.exec(raw)) {
        if (copyPlaceholders(m[2]) === null) bad.push(`${path} ${m[1]}: ${m[2]}`);
      }
    }
    expect(bad).toEqual([]);
  });

  it("a <Text> default carrying placeholders also passes the values for them", () => {
    const bad: string[] = [];
    for (const [path, raw] of ALL_SOURCE) {
      TEXT_STRING_CHILD.lastIndex = 0;
      for (let m = TEXT_STRING_CHILD.exec(raw); m; m = TEXT_STRING_CHILD.exec(raw)) {
        const names = copyPlaceholders(m[2]);
        if (names === null) {
          bad.push(`${path}: malformed template ${m[2]}`);
          continue;
        }
        if (names.length > 0 && !m[1].includes("values=")) {
          bad.push(`${path}: ${m[2]} declares ${names.join(", ")} but passes no values`);
        }
      }
    }
    expect(bad).toEqual([]);
  });
});
