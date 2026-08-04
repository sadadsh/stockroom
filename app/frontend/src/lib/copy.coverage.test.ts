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
 * Two things are checked, both chosen because they are UNAMBIGUOUS in source text. A heuristic that
 * has to guess is a heuristic people learn to ignore.
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
 *  2. A LITERAL `aria-label="..."` or `placeholder="..."`. A double-quoted JSX attribute value is a
 *     string literal, full stop - there is no expression form to confuse it with. These are the two
 *     attributes that carry text a person reads or hears and that a wrapper element cannot reach,
 *     which is exactly what `useText` exists for. `title=` is deliberately NOT checked: half the
 *     `title` props in this tree belong to components that take a `title` STRING plus a separate
 *     `copyId`, and convicting those would be the noise this gate is built to avoid.
 *
 * --- THE BOUNDARY ------------------------------------------------------------------------------
 *
 * `COVERED_SURFACES` is the enforced list, and it is the honest one: these are the files carrying
 * the surfaces this pass covers (the opened component and its sheets, the provider trip, intake and
 * import, the modals, the shared primitives, the rail and the two pickers). Adding a file here is
 * how coverage grows, and a new file inside an already-listed directory is covered the moment it
 * lands. Everything outside is NOT claimed to be covered, because claiming it without routing it is
 * how a coverage gate becomes decoration.
 *
 * Dev Mode's own surfaces (`DevPanel` / `DevInspector`) are deliberately outside: they are the
 * editor, and routing the editor's labels through the surface it edits means one bad override can
 * make the editor unusable and unfixable.
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

/** The files this gate enforces. A trailing slash covers a whole directory. */
const COVERED_SURFACES: readonly string[] = [
  "/src/components/component-workspace/",
  "/src/components/projects/",
  "/src/components/productState.tsx",
  "/src/components/modalParts.tsx",
  "/src/components/primitives.tsx",
  "/src/components/formFields.tsx",
  "/src/components/AddPartModal.tsx",
  "/src/components/AltiumDbLibModal.tsx",
  "/src/components/AltiumSetupModal.tsx",
  "/src/components/AppShell.tsx",
  "/src/components/BulkImportSection.tsx",
  "/src/components/CandidateCard.tsx",
  "/src/components/CompletePartModal.tsx",
  "/src/components/CompletionWorklist.tsx",
  "/src/components/ConfirmDialog.tsx",
  "/src/components/DiffModal.tsx",
  "/src/components/EnrichStages.tsx",
  "/src/components/Finder.tsx",
  "/src/components/HandoffBand.tsx",
  "/src/components/PartsList.tsx",
  "/src/components/PassiveAddSection.tsx",
  "/src/components/PreviewModal.tsx",
  "/src/components/ProductPhoto.tsx",
  "/src/components/Rail.tsx",
  "/src/components/SettingsDisclosure.tsx",
  "/src/pages/ComponentsPage.tsx",
  "/src/pages/IngestPage.tsx",
  "/src/pages/ProjectsPage.tsx",
];

function covered(path: string): boolean {
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

function unroutedText(path: string, raw: string): Offence[] {
  const src = blankComments(raw);
  const out: Offence[] = [];
  JSX_TEXT.lastIndex = 0;
  for (let m = JSX_TEXT.exec(src); m; m = JSX_TEXT.exec(src)) {
    const gt = m.index;
    const before = src[gt - 1];
    // `=>`, `->`, `<<`, `>>`: the `>` is an operator, not a tag close.
    if (before === "=" || before === "-" || before === "<" || before === ">") continue;
    const run = m[1];
    if (CODE_CHARS.test(run)) continue;
    const text = run.trim();
    if (text.length < 2 || !/[A-Za-z]{2}/.test(text)) continue;
    if (/^[,:;]/.test(text)) continue;
    const openAt = src.lastIndexOf("<", gt);
    if (openAt < 0) continue;
    const tag = src.slice(openAt, gt + 1);
    const name = /^<\/?([A-Za-z][\w.]*)/.exec(tag)?.[1];
    if (!name) continue;
    if (COPY_TAGS.has(name)) continue;
    if (tag.includes("copyId=")) continue;
    out.push({ where: `${path}:${lineOf(src, gt)}`, text });
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

  it("routes every literal aria-label and placeholder through the copy layer", () => {
    const offences = SOURCE.flatMap(([path, raw]) => unroutedAttributes(path, raw)).map(
      (o) => `${o.where} ${o.text}`,
    );
    expect(offences).toEqual([]);
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
