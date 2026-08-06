/**
 * NAMED LOCAL DRAFTS of a layout document, in this browser's storage.
 *
 * The owner's decision 4, stated in two halves: "a committed redesign becomes the app", and "named
 * local drafts exist while experimenting". This module is the second half and only the second half. A
 * draft here is a WORKSTATION artefact - it never travels, it is never a gate, and nothing renders
 * from it by itself; the owner loads one into the Design Mode working draft
 * (`lib/devModeDraft.ts`'s layout slice) and the arrangement in force follows from
 * `layout/resolveWorkspaceLayout.ts` as usual. Committing is the plan's Phase 4 pipeline and writes
 * `lib/layout.overrides.ts` instead.
 *
 * SAME DISCIPLINE AS `lib/workspaceColumns.ts`'s storage helpers, for the same reason: every function
 * that touches `window.localStorage` SWALLOWS EVERY FAILURE. A browser with storage disabled, a quota
 * that is full, a value some other tool overwrote with a string - none of those may take the editor
 * down. A read that cannot be trusted returns nothing; a write that cannot land returns `false` and
 * the caller can say so.
 *
 * WHAT IS NOT VALIDATED, deliberately. A stored document is checked for SHAPE (it is a document, with
 * a region for a root) and nothing more. A draft naming a piece this build has not shipped, or
 * carrying an arrangement `validateLayout` would report, is still a draft the owner saved: warn, never
 * block (decision 3) means it loads and the issues list says what is wrong with it.
 *
 * NO UI HERE. The Design Mode surfaces that save, list, load and delete are 3B/3C.
 */
import type { LayoutDocument } from "../layout/document";

export const LAYOUT_DRAFTS_STORAGE_KEY = "stockroom.design-mode.layout-drafts.v1";

/**
 * The longest name a draft may carry.
 *
 * Not a style rule - a bound on what one workstation's storage can be made to hold by a caller that
 * pastes something enormous into a name field. A draft nobody can name is a draft nobody can find.
 */
export const LAYOUT_DRAFT_NAME_MAX = 120;

/** What the list shows: enough to choose between drafts, without loading any of them. */
export interface LayoutDraftSummary {
  name: string;
  /** Epoch milliseconds. A number rather than a `Date`, because this is serialised. */
  savedAt: number;
  /** The document's own surface id, so a draft of another surface is recognisable as one. */
  documentId: string;
}

export interface LayoutDraft extends LayoutDraftSummary {
  document: LayoutDocument;
}

/** The stored file: one version marker and one entry per name. */
interface DraftFile {
  version: number;
  drafts: Record<string, LayoutDraft>;
}

const DRAFT_FILE_VERSION = 1;

/**
 * A name that can be stored and found again, or `null`.
 *
 * Trimmed, because " sourcing left" and "sourcing left" are the same draft to the person who typed
 * them and two drafts to a record keyed on the string.
 */
function normalizeName(raw: unknown): string | null {
  if (typeof raw !== "string") return null;
  const name = raw.trim();
  if (name.length === 0 || name.length > LAYOUT_DRAFT_NAME_MAX) return null;
  return name;
}

/** Is this the SHAPE of a layout document. Not "is it a good one" - see the file header. */
function isLayoutDocument(value: unknown): value is LayoutDocument {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<LayoutDocument>;
  if (typeof candidate.schemaVersion !== "number") return false;
  if (typeof candidate.id !== "string") return false;
  const root = candidate.root as { kind?: unknown; slots?: unknown } | undefined;
  if (!root || typeof root !== "object") return false;
  return root.kind === "region" && Array.isArray(root.slots);
}

function isDraft(value: unknown, name: string): value is LayoutDraft {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<LayoutDraft>;
  if (candidate.name !== name) return false;
  if (typeof candidate.savedAt !== "number" || !Number.isFinite(candidate.savedAt)) return false;
  return isLayoutDocument(candidate.document);
}

/**
 * Every readable draft, keyed by name. An unreadable file, or an entry that is not a draft, is
 * DROPPED rather than repaired: half a document is not an arrangement, and guessing at one would put
 * an edit the owner never made on the screen.
 */
function readFile(): Record<string, LayoutDraft> {
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(LAYOUT_DRAFTS_STORAGE_KEY);
  } catch {
    return {};
  }
  if (!raw) return {};
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw) as unknown;
  } catch {
    return {};
  }
  if (!parsed || typeof parsed !== "object") return {};
  const file = parsed as Partial<DraftFile>;
  if (file.version !== DRAFT_FILE_VERSION) return {};
  if (!file.drafts || typeof file.drafts !== "object") return {};
  const drafts: Record<string, LayoutDraft> = {};
  for (const [key, value] of Object.entries(file.drafts)) {
    const name = normalizeName(key);
    if (!name || !isDraft(value, name)) continue;
    drafts[name] = value;
  }
  return drafts;
}

/** Write the whole file. `false` when storage refused it, and nothing else happens either way. */
function writeFile(drafts: Record<string, LayoutDraft>): boolean {
  try {
    window.localStorage.setItem(
      LAYOUT_DRAFTS_STORAGE_KEY,
      JSON.stringify({ version: DRAFT_FILE_VERSION, drafts } satisfies DraftFile),
    );
    return true;
  } catch {
    /* A browser that refuses storage still gets a working editor - the draft just is not kept. */
    return false;
  }
}

/**
 * Save this arrangement under this name, replacing a draft of the same name.
 *
 * REPLACING RATHER THAN VERSIONING is the whole of the naming decision: a name is how the owner says
 * which experiment this is, and a save that silently made "sourcing left (2)" would leave them
 * choosing between drafts they did not distinguish.
 *
 * `false` when the name is unusable, the document is not a document, or storage refused the write.
 */
export function saveLayoutDraft(
  name: string,
  document: LayoutDocument,
  savedAt: number = Date.now(),
): boolean {
  const key = normalizeName(name);
  if (!key || !isLayoutDocument(document)) return false;
  const drafts = readFile();
  // NO COPY IS TAKEN, and that is deliberate rather than an omission: `writeFile` serialises the whole
  // file immediately, so what is kept is TEXT and the map below is discarded on the next line. A draft
  // therefore cannot hold a reference into the live working document. It also means a document that
  // will not serialise - a cycle, something a bad merge produced - fails inside `writeFile` and comes
  // back as `false`, which is exactly the answer a draft that was not stored deserves.
  drafts[key] = {
    name: key,
    savedAt: Number.isFinite(savedAt) ? savedAt : Date.now(),
    documentId: document.id,
    document,
  };
  return writeFile(drafts);
}

/** The document saved under this name, or `null`. Fresh objects - storage holds text. */
export function loadLayoutDraft(name: string): LayoutDocument | null {
  const key = normalizeName(name);
  if (!key) return null;
  return readFile()[key]?.document ?? null;
}

/** Every saved draft, newest first, ties broken by name so the order is total and stable. */
export function listLayoutDrafts(): LayoutDraftSummary[] {
  return Object.values(readFile())
    .map(({ name, savedAt, documentId }) => ({ name, savedAt, documentId }))
    .sort((left, right) => right.savedAt - left.savedAt || left.name.localeCompare(right.name));
}

/** Forget this draft. `false` when there was nothing to forget, or storage refused the write. */
export function deleteLayoutDraft(name: string): boolean {
  const key = normalizeName(name);
  if (!key) return false;
  const drafts = readFile();
  if (!(key in drafts)) return false;
  delete drafts[key];
  return writeFile(drafts);
}
