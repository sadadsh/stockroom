/**
 * The interface-text term map.
 *
 * THE RULE: Unicode U+0079 - the lower-case letter after x - must not appear in text this
 * application authors for a person to read. Labels, menus, hints, placeholders, tooltips, dialog
 * copy, notices, error text, success text, status text, empty-state copy and in-app documentation
 * are all bound to it. An upper-case form is NOT an escape hatch: it is the same letter with a
 * different case, and it is accepted here just once, inside a proper name that cannot be reworded
 * (a provider's own trade name).
 *
 * WHAT IS NOT BOUND: part DATA. Manufacturer part numbers, manufacturer names, distributor
 * descriptions, provider names, class names that arrive from a provider, spec labels and spec
 * values off the wire, and file names all originate outside this codebase. Rewording a
 * manufacturer's description would corrupt the record, and an MPN is an identifier that must never
 * be altered. The copy layer is the boundary: a string authored in a `<Text id>` default, a
 * `useText(id, fallback)` or a `useCopyFormatter(id, fallback)` is ours and is bound. A value
 * interpolated INTO one of those through a named placeholder is data and is exempt - in
 * `"Overrides {value} from {source}"` the words are bound and `{value}` / `{source}` are not.
 *
 * HOW A BLOCKED TERM IS RESOLVED, in this order:
 *
 *  1. CAN A GLYPH CARRY THE VERB? Then the text carries the object alone, or the control is
 *     icon-only. A copy glyph beside `MPN` says what `Copy MPN` said, in less space, and reads
 *     like an instrument rather than a labelled web button. This is the preferred outcome.
 *     Two constraints hold: an icon-only control still needs an accessible name and a tooltip
 *     carrying the COMPLETE action, and that text is interface text, so it is bound to the rule
 *     as well - a glyph is not a place to hide a blocked word. And a control whose action is not
 *     self-evident keeps its word; a destructive action always keeps its word.
 *  2. IS THERE A GENUINELY ACCURATE REPLACEMENT WORD? Then use the one recorded below, so the
 *     same idea reads the same way on every surface.
 *  3. NEITHER? Leave the string and raise it, rather than shipping a label that means something
 *     the control does not do.
 *
 * Every replacement here is a word an engineer would actually write. None is a contraction, a
 * clipped form or a misspelling: `Repo` is rejected for `Repository` on exactly that ground, and
 * `Duplicate` is rejected for a clipboard write because duplicating an MPN would mean making a
 * second MPN, which is not what the control does.
 *
 * A note on adverbs: essentially every English adverb in `-ly` carries the letter, so an adverb
 * cannot be swapped word-for-word. The entries below turn each one into an adjective or a phrase
 * ("adopted automatically" becomes "adoption is automatic"), which is why some replacements are
 * a rewrite instruction rather than a single word.
 *
 * A FOURTH outcome exists and is recorded separately, in `INDUSTRY_TERMS` at the foot of this file:
 * a standardised technical term with no synonym KEEPS the letter. Coining a replacement for an
 * industry standard is worse than printing the word, because a coinage sends an EDA reader looking
 * for an entity that does not exist. That list is short on purpose and is not a place to park a word
 * that is merely inconvenient. Note also that "permitted" is not "required": where a glyph can carry
 * the meaning, the glyph is still the better answer.
 *
 * `copy.letterRule.test.ts` enforces the rule against the copy sources themselves and quotes the
 * entry below when it reports an offender.
 */

export interface BlockedTerm {
  /** The term that must not be written. Matched case-insensitively, whole word. */
  readonly term: string;
  /** What to write instead. A phrase when the honest replacement is a rewrite. */
  readonly replacement: string;
  /** Why this replacement keeps the technical meaning. */
  readonly note: string;
}

/**
 * The map. Ordered roughly by how much of the product each term touches.
 *
 * This is documentation with teeth rather than a lookup the app runs: the rule is enforced on the
 * LETTER, so a new offending word is caught whether or not it is listed here. The list exists so
 * that the same idea is reworded the same way twice.
 */
export const BLOCKED_TERMS: readonly BlockedTerm[] = [
  // --- the owner's own vocabulary -------------------------------------------------------------
  {
    term: "Verify",
    replacement: "Validate",
    note: "The capture pipeline already calls this validating: proving a downloaded asset matches the record it was collected for. Same act, same strength of claim. Prefer the check mark on a control that can hold one, and keep the word for prose.",
  },
  {
    term: "Display",
    replacement: "Show",
    note: "Plain verb for the same thing. On a control, the `action.view` eye mark carries it with no word at all; the word is for prose.",
  },
  {
    term: "Copy",
    replacement: "Place ... On Clipboard",
    note: "FIRST resort is the `action.duplicate` mark carrying the verb while the label carries the object alone - a copy mark beside `Path` says what `Copy Path` said, in less space. The written form above is for the tooltip and the accessible name, which still have to state the complete action. `Duplicate` is right when an object really is copied (a part, a variant) and WRONG for a clipboard write: duplicating an MPN would mean making a second MPN.",
  },
  {
    term: "Summary",
    replacement: "Overview",
    note: "Same reduced-to-the-essentials sense, no claim of arithmetic.",
  },
  {
    term: "Apply",
    replacement: "Commit, or Set",
    note: "Commit where the change is written and persisted; Set where it only takes effect now. Picking per site keeps the label honest about durability.",
  },
  {
    term: "Quantity",
    replacement: "Count",
    note: "Every use in this product is a whole number of pieces or boards, which is what a count is.",
  },
  {
    term: "Category",
    replacement: "Class, or Group",
    note: "Class for a component's own classification; Group for a bucket of pins or rows. A tag mark next to the value can remove the need for either word where the value speaks for itself.",
  },
  {
    term: "Library",
    replacement: "Catalog",
    note: "The thing is a curated, versioned collection of parts, which is a catalog. On a control the `nav.library` mark can carry it with no word. Note the EDA sense of the word survives in DATA - a KiCad .kicad_sym library name is a file name and is not touched.",
  },

  // --- status and action vocabulary ------------------------------------------------------------
  {
    term: "Retry / Try Again",
    replacement: "Rerun",
    note: "The action runs the same operation again, which is what rerunning is. Note `retries` and `retried` are already clear of the letter, so prose can still say a retry happened.",
  },
  {
    term: "Retrying",
    replacement: "Rerunning",
    note: "Matches Rerun.",
  },
  {
    term: "Busy",
    replacement: "In Use",
    note: "Names WHO is holding it rather than how it feels, and pairs with Free.",
  },
  {
    term: "Synced",
    replacement: "Aligned",
    note: "Already the word this product uses for a local copy that matches its remote.",
  },
  {
    term: "Healthy",
    replacement: "Sound",
    note: "Standard engineering sense: intact, nothing broken. Used for both a scanned catalog and a backend that passed its health check.",
  },
  {
    term: "Already",
    replacement: "In Force, Present, or now",
    note: "In Force where a value is the one in effect (the vocabulary this product already uses for that); Present where a record exists; `now` in prose.",
  },
  {
    term: "Mandatory",
    replacement: "Required",
    note: "Same obligation, and it matches the word used elsewhere in the target rules.",
  },
  {
    term: "Supplementary",
    replacement: "Additional",
    note: "Same sense of kept-but-not-active.",
  },
  {
    term: "Primary",
    replacement: "Main",
    note: "Same sense of the first-choice one of a set.",
  },
  {
    term: "Buy",
    replacement: "Purchase",
    note: "Same transaction; the noun form is what a distributor link is for.",
  },

  // --- domain nouns ---------------------------------------------------------------------------
  {
    term: "Repository",
    replacement: "Git remote, or Git checkout",
    note: "Split by which half is meant: the remote endpoint work is pushed to, or the local working tree on disk. `Repo` is rejected - it is a clipped form, and the rule asks for real words.",
  },
  {
    term: "Identity",
    replacement: "Identification",
    note: "The exact-part question: which manufacturer part number this record is. Identification is the ordinary word for establishing that and loses nothing.",
  },
  {
    term: "History",
    replacement: "Timeline",
    note: "A chronological record of what happened, which is what these surfaces show - and what the PartTimeline component was already called. ONE SITE IS SETTLED DIFFERENTLY, and is recorded here so a later pass does not 'correct' it back: where the word names git's own storage, write Commits. `Stored In Git History` is now `Stored In Git Commits` in the Library Sync section, because a file is stored in a COMMIT and `Git Timeline` names no git entity at all. Timeline remains right for a record of events over time, which is what the part timeline is.",
  },
  {
    term: "Policy",
    replacement: "Rules",
    note: "A target definition policy is a set of rules; naming them rules says the same thing and reads plainly in a heading.",
  },
  {
    term: "Type",
    replacement: "Kind",
    note: "Already this product's word for a closed set of variants ('choose the kind and package').",
  },
  {
    term: "Family",
    replacement: "Series",
    note: "ST's own word for a group of parts that share silicon. Note an actual family NAME arriving from the index is data and is not touched.",
  },
  {
    term: "Key (an API key)",
    replacement: "Credential",
    note: "What is being stored is the secret that authenticates this machine to a provider. Credential is the general, accurate term; the provider's own name for it stays intact in DATA. A SPECIFICATION key is a different thing and takes a different word: the headline group is now Main Specifications, on both sides at once, since its label originates in `dossier/vocabulary.py` and a one-sided rename would leave the two surfaces naming the same group differently. A key in a stored RECORD is a field, which is what `Fields this build does not read` now says.",
  },
  {
    term: "Availability",
    replacement: "Stock",
    note: "The noun carries the letter where the adjective Available does not, so the two are not interchangeable here. Every site asking about availability in this product is asking how much of the part a distributor holds, which is stock; `Product Status and Stock` names the two facts that section reports rather than the abstraction over them.",
  },
  {
    term: "Binary (storage)",
    replacement: "Large File",
    note: "The setting governs Git LFS, whose name is literally Large File Storage, so this is the underlying system's own word.",
  },
  {
    term: "Directory",
    replacement: "Folder",
    note: "Same filesystem object, and Folder is what the rest of this product's pickers say.",
  },
  {
    term: "Delivery",
    replacement: "Updates",
    note: "The section is about how new revisions reach a machine, which is what updates are.",
  },
  {
    term: "Lifecycle",
    replacement: "Product Status",
    note: "ONE CONCEPT, ONE SPELLING. The column reports where a part sits between introduction and obsolescence, and it was being called two things at once: `Life Stage` in search results and `Lifecycle` in the component workspace. Product Status is what the distributors themselves call this field, so it is the word a person already reads on the source page, and it beats the coinage `Life Stage` that no catalogue uses. The provider spec KEYS this is read out of (`Lifecycle`, `Part Status`) are payload data and are never touched - renaming one would stop the value being found.",
  },
  {
    term: "Supply",
    replacement: "Power (the noun), or provide / offer (the verb)",
    note: "A pin's supply is its power domain. A provider that can supply a CAD set provides or offers it.",
  },
  {
    term: "System (an STM32 pin class)",
    replacement: "Additional Functions",
    note: "This section holds the signals that are NOT AF-muxed - ADC and DAC inputs, wakeup, RTC references. ST's datasheets call exactly that set the additional functions, so the replacement is MORE precise than the label it replaces.",
  },
  {
    term: "Topology",
    replacement: "Structure",
    note: "How the socket nodes are arranged and joined. Structure keeps that and drops nothing this surface actually reports.",
  },
  {
    term: "Layout (a drawn arrangement)",
    replacement: "Arrangement",
    note: "Used for the drawn pin arrangement of a package. PCB layout as a discipline does not appear in these strings.",
  },
  {
    term: "Geometry",
    replacement: "Outline",
    note: "What is missing when a package cannot be drawn is its outline.",
  },
  {
    term: "Capability",
    replacement: "capabilities",
    note: "The plural is clear of the letter and reads correctly in every site here.",
  },
  {
    term: "Physical",
    replacement: "hardware, or package",
    note: "hardware for a real build or a real placement; package for a position on a package.",
  },
  {
    term: "Hybrid",
    replacement: "Mixed",
    note: "The positions in question hold more than one kind of arrangement at once.",
  },
  {
    term: "Recovery",
    replacement: "repair, or rescue",
    note: "repair where something broken is being fixed (rebuilding a DbLib); rescue where access to a locked device is being regained.",
  },
  {
    term: "Safety",
    replacement: "safe-state",
    note: "The rules govern declared safe states, which is the narrower and more accurate claim.",
  },
  {
    term: "Technology",
    replacement: "Method",
    note: "The consuming design chooses HOW to switch, select or isolate - a method.",
  },
  {
    term: "Applicability",
    replacement: "Scope",
    note: "Which targets the rules reach.",
  },
  {
    term: "Security (a provider gate)",
    replacement: "protection, or a challenge",
    note: "What a provider page actually interposes is a sign-in or a challenge; naming it that is more specific than calling it security.",
  },

  // --- function words and adverbs --------------------------------------------------------------
  {
    term: "every",
    replacement: "each, or all",
    note: "each for one-at-a-time distribution, all for the set taken together.",
  },
  {
    term: "only",
    replacement: "just, alone, or sole",
    note: "just before a verb, alone after a noun, sole for a single-member set.",
  },
  {
    term: "yet",
    replacement: "so far, or drop it",
    note: "'No timeline so far' says what 'no history yet' said. Often the word carries nothing and can go.",
  },
  {
    term: "you / your",
    replacement: "the, this, or a rewrite without the reader in it",
    note: "The product can talk about the catalog instead of about the reader: 'your components' becomes 'the components'. Where an instruction genuinely needs a subject, name the actor ('Stockroom captures each file').",
  },
  {
    term: "by",
    replacement: "from, per, via, or through",
    note: "from for origin, per for a grouping key, via / through for a route.",
  },
  {
    term: "may",
    replacement: "can, or might",
    note: "can for permission or capability, might for possibility.",
  },
  {
    term: "stay / stays",
    replacement: "remain / remains",
    note: "Identical sense of continuing unchanged.",
  },
  {
    term: "automatically",
    replacement: "the adjective automatic, or unattended",
    note: "'adopted automatically' becomes 'adoption is automatic'. The adjective is clear of the letter; the adverb cannot be.",
  },
  {
    term: "silently",
    replacement: "in silence",
    note: "Same claim, as a phrase.",
  },
  {
    term: "cleanly",
    replacement: "without force",
    note: "Closing Altium cleanly means closing it without killing the process, which is what this says.",
  },
  {
    term: "manually",
    replacement: "a rewrite naming the actor",
    note: "'you do not need to import them manually' becomes 'no one needs to import them'.",
  },
  {
    term: "genuinely",
    replacement: "in fact",
    note: "Same emphasis on the real state rather than the assumed one.",
  },
  {
    term: "exactly",
    replacement: "drop it, or name the state (as is)",
    note: "'left exactly as it is' becomes 'left as it is': the adverb was insisting on a claim the sentence already makes. Where the emphasis is load-bearing, say what was preserved instead of how faithfully.",
  },
  {
    term: "partway",
    replacement: "during the run, or mid-run",
    note: "'failed partway through' becomes 'failed during the run', which also says WHICH run. Note the ordinary phrase 'part of the way' carries the letter and is no escape.",
  },
  {
    term: "atomically",
    replacement: "in one atomic switch, or as one change",
    note: "The adjective is clear of the letter and the noun states what the unit of change is, which is the point being made.",
  },
  {
    term: "quietly",
    replacement: "in silence",
    note: "Matches the entry for silently; 'quietly counted as deleted' becomes 'counted as deleted in silence'.",
  },
  {
    term: "beyond",
    replacement: "past",
    note: "Same sense of lying further along.",
  },
  {
    term: "everything",
    replacement: "all of it",
    note: "Same totality.",
  },
  {
    term: "always",
    replacement: "at all times, or name the occasion (each run)",
    note: "'the compiler always inventories X' becomes 'each run inventories X', which is also more concrete.",
  },
  {
    term: "reliably",
    replacement: "a rewrite stating what makes it work",
    note: "'resolves a link reliably' becomes 'is what makes the link resolve' - the same promise without the adverb.",
  },
  {
    term: "externally",
    replacement: "from outside",
    note: "Same source-of-evidence claim.",
  },
  {
    term: "Fully",
    replacement: "drop the intensifier, or All-",
    note: "'Fully Exclusive Positions' becomes 'All-Exclusive Positions': every part in the set is exclusive there, which is what fully was doing.",
  },
];

/**
 * A term this codebase is PERMITTED to write with the letter in it, and why no replacement exists.
 *
 * This is a different kind of entry from a proper name. `DigiKey` is exempt because spelling another
 * company's registered name differently would be a factual error. These are exempt because they are
 * STANDARDISED and SYNONYM-FREE: an EDA reader knows the term, the standard or the tool defines it,
 * and every candidate replacement either names a different entity or is a coinage this industry has
 * never used. A coined near-synonym is the worse outcome - it sends a reader looking for something
 * that does not exist.
 *
 * TWO THINGS THIS LIST IS NOT.
 *
 *  - It is not a licence to print the word. Where a glyph, a mark or the asset itself can carry the
 *    meaning, that is still the preferred answer; permitted is not required.
 *  - It is not a dumping ground. A word that is merely inconvenient, or that has an accurate
 *    replacement someone did not like, belongs in `BLOCKED_TERMS` with that replacement. The gate
 *    holds this list to a hard ceiling so that growth has to be argued for rather than assumed.
 */
export interface AllowedTerm {
  /** The permitted term. Matched case-insensitively, whole word, with an optional plural `s`. */
  readonly term: string;
  /** One line: why this standard has no honest replacement. */
  readonly why: string;
}

/**
 * Owner-approved product vocabulary whose ordinary wording is part of the interface contract.
 * These entries are not technical-standard exemptions; each is retained because the proposed
 * replacement changed the action, status, or familiar UI concept a person was being shown.
 */
export const APPROVED_PRODUCT_TERMS: readonly AllowedTerm[] = [
  {
    term: "Apply",
    why: "Apply is the approved confirmation verb for activating reviewed attachments and local Design Studio changes; Commit incorrectly implies a Git operation.",
  },
  {
    term: "Applying",
    why: "Applying is the in-progress form of the approved Apply action and must describe the same operation while it runs.",
  },
  {
    term: "Layout",
    why: "Layout is the established Design Studio inspector domain; Arrangement does not name the same editable CSS and composition surface.",
  },
  {
    term: "Retry",
    why: "Retry is the familiar recovery action for a failed provider attempt; Rerun suggests a completed batch rather than the same failed request.",
  },
  {
    term: "History",
    why: "Build History is the approved record of prior Catalog Build runs; Timeline implies a chronological visualization that this disclosure does not provide.",
  },
  {
    term: "Synchronization",
    why: "Catalog Synchronization names the established remote-alignment capability; Convergence describes an outcome rather than the capability itself.",
  },
];

export const INDUSTRY_TERMS: readonly AllowedTerm[] = [
  {
    term: "Catalog Repository",
    why: "The accepted domain model names the GitHub-backed collaboration authority the Catalog Repository; Git remote or checkout names only one implementation edge and loses product ownership semantics.",
  },
  {
    term: "Ready",
    why: "Guided Setup has one owner-approved terminal verdict named Ready; Prepared is a separate historical UI status and would contradict the accepted setup contract.",
  },
  {
    term: "Courtyard",
    why: "IPC-7351's own name for the placement envelope of a land pattern; a keep-out is a DIFFERENT PCB entity, so renaming it would tell an EDA reader something false about the drawing.",
  },
  {
    term: "Layer",
    why: "A PCB and a drawing are both defined as stacks of layers by every tool and every fabricator; no one-word English alternative names the same thing.",
  },
  {
    term: "Symbol",
    why: "The schematic-side asset, opposite the footprint's board side; `Schematic` names the whole sheet rather than the part on it, and `Schematic Part` is a coinage no EDA tool uses.",
  },
  {
    term: "Compatibility",
    why: "Two parts can be compatible without being interchangeable, and this product reports exactly that gap - `Interchange` would upgrade the claim to one Stockroom has not validated.",
  },
];

/** Lower-cased first word of each term, for the lookup below. */
const INDEX: ReadonlyMap<string, BlockedTerm> = new Map(
  BLOCKED_TERMS.map((t) => [/^[A-Za-z-]+/.exec(t.term)?.[0].toLowerCase() ?? t.term, t]),
);

/**
 * The recorded replacement for a word, if this map has one. Used by the lint to say what to write
 * instead of the word it just rejected, so a failure is a fix rather than a puzzle.
 */
export function suggestReplacement(word: string): BlockedTerm | undefined {
  return INDEX.get(word.toLowerCase());
}
