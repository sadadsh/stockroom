/**
 * One specification, with its provenance attached to it.
 *
 * The PREFERRED VALUE is the visually primary thing in the row - more visible than its label, its
 * source and its state, all three of which describe it. The label column is fixed so the values
 * line up down the column; there is no colon after a label, and there is no card around a
 * specification.
 *
 * Provenance lives HERE, on the row it is about, rather than in a disconnected "Attributed Fields"
 * panel elsewhere on the screen. A source name means nothing until you can see which value it is
 * arguing about, and a list of disagreements detached from the fields they concern is a list
 * nobody can act on.
 *
 * A row with no value is still a row. An expected field nobody supplied renders as `Missing`, in
 * its proper place in its proper group, because a hole a person can see is the entire point of a
 * category schema - and it is a hole that cannot be inferred from an empty string.
 */
import { useRef, useState } from "react";
import type { SourceCandidate, SpecificationRecord } from "../../api/dossierTypes";
import type { SpecificationWrite } from "../../api/queries";
import { Text, useCopyFormatter, useText } from "../../lib/copy";
import { formatTimestamp } from "../../lib/formatValue";
import { Icon } from "../Icon";
import { Button, StatusText } from "../primitives";
import { ExternalIcon } from "../icons";
import {
  alternateCandidates,
  displayWithUnit,
  isEmptyState,
  specRowTone,
} from "./specificationRows";
import { SpecificationEditor } from "./SpecificationEditor";
import { SpecStateLabel, useSpecStateText } from "./SpecificationState";

export interface SpecificationRowProps {
  record: SpecificationRecord;
  /** Key specifications carry weight 500; everything else stays at the body weight. */
  emphasise?: boolean;
  /** Run one write. `undefined` while another row's write is in flight. */
  onWrite: (write: SpecificationWrite) => Promise<unknown>;
  /** True while ANY specification write is in flight, so the column cannot be double-submitted. */
  busy: boolean;
  /** Where a named source can actually be looked at, when such a place exists. */
  sourceUrl: (sourceId: string) => string;
}

/**
 * The text tone a state word takes when it stands in the value cell.
 *
 * `neutral` is the DISABLED tier rather than a colour: `Not Reported` and `Not Applicable` are not
 * problems, and spending a hue on them would make every quiet row look like a finding.
 */
const SPEC_STATE_TEXT: Record<"ok" | "warn" | "err" | "neutral", string> = {
  ok: "text-ok-text",
  warn: "text-warn",
  err: "text-err-text",
  neutral: "ui-disabled",
};

export function SpecificationRow({
  record,
  emphasise = false,
  onWrite,
  busy,
  sourceUrl,
}: SpecificationRowProps) {
  const [open, setOpen] = useState(false);
  const [failure, setFailure] = useState("");
  const state = record.verificationState;
  const value = displayWithUnit(record);
  const alternates = alternateCandidates(record);
  const preferred = record.preferredSource;
  const noValue = isEmptyState(state);
  const evidenceLabel = useCopyFormatter(
    "component-browser.spec-evidence",
    "Source evidence for {label}",
  );
  const stateText = useSpecStateText();
  /**
   * SHOW THE EXCEPTION, NOT THE RULE.
   *
   * The row used to carry three pieces of metadata around every value - a source tier, a state, and
   * the word `Evidence` - so an eighteen-row column printed fifty-four metadata items around
   * eighteen answers. Almost all of it was true of almost every row, and a label true of every row
   * distinguishes nothing.
   *
   *   `Unverified`   the rule, not an exception: it comes off the row and lives in the disclosure.
   *   `Unattributed` jargon for "nobody said where this came from". An absent source is not worth a
   *                  word; a real source NAME still is, so that keeps its cell.
   *   `Not Reported` / `Not Applicable`  a dash at rest, with the exact word in the tooltip, in the
   *                  accessible name, in `data-spec-state` and in the disclosure. A JUDGMENT CALL:
   *                  the earlier rule wanted all six states visually distinct at a glance, and this
   *                  trades first-glance distinction between two non-actionable states for calm.
   *   `Missing`      keeps its word and its amber, always. It is the one absence a person can act
   *                  on, and surfacing it is the entire reason a category schema exists.
   *   `Conflicting`  a quiet marker rather than a sentence. It stays findable three ways: this
   *                  marker, the count in the header's quality summary, and the Conflicts filter.
   */
  const quiet = state === "not_reported" || state === "not_applicable";

  // Nothing to disclose is a control that must not exist: a row with one agreeing source and no
  // override to withdraw has no second surface behind it, and a disclosure that opens onto
  // nothing is a dead click path.
  const hasEvidence = alternates.length > 0 || preferred !== null || !noValue || record.expectedForCategory;

  // Weight 500 is spent on the values worth looking at first, and nowhere else. A key fact, a
  // disagreement and a gap the category expects are the three a person is scanning for; bolding
  // every value would make all of them ordinary again.
  const needsReview = state === "conflicting" || state === "missing";
  const prominent = emphasise || needsReview;

  return (
    <div
      data-dev-id="component-browser.spec-row"
      data-spec-key={record.key}
      data-spec-state={state}
      data-spec-importance={record.importance}
      // Compact rows align on a fixed label column. A quiet alternating wash and hover state keep
      // each value on its line without boxing every label and value into separate cells.
      className="even:bg-row-alt/50 hover:bg-[var(--c-hover)]"
    >
      <div className="flex min-h-[24px] items-baseline gap-2 px-2 py-1">
        <span className="ui-property-label w-[9.5rem] flex-none break-words pr-3">
          {record.label}
        </span>
        <span
          data-dev-id="component-browser.spec-value"
          // Wraps, never truncates: a value is often the ONLY representation of itself on the
          // screen, and half of one is not a smaller version of it. Tabular figures so a column
          // of measurements stacks on its place values instead of reflowing as it updates.
          // When the cell stands in for a state, it carries the state's TONE and - for the two
          // quiet states - the exact word as its accessible name and its tooltip, so a dash is
          // never a sighted-only distinction.
          aria-label={noValue ? stateText[state] : undefined}
          title={noValue ? stateText[state] : undefined}
          className={
            "min-w-0 flex-1 break-words tnum ui-property-value" +
            (noValue ? " " + SPEC_STATE_TEXT[specRowTone(state)] : "") +
            (prominent && !noValue ? " font-medium" : "")
          }
        >
          {value || (quiet ? "—" : <SpecStateLabel state={state} />)}
        </span>
        {/* A source NAME is information; the absence of one is not. The projection reports an
            unattributed value as the literal word `Unattributed`, which was the least useful thing
            on the line and appeared on most of them, so only a real provider name gets a cell. The
            tier and the unattributed fact both remain in the disclosure. */}
        {preferred?.sourceLabel && preferred.sourceId ? (
          <span
            data-dev-id="component-browser.spec-source"
            className="ui-component-metadata max-w-[7rem] flex-none break-words text-right"
            title={preferred.tierLabel}
          >
            {preferred.sourceLabel}
          </span>
        ) : null}
        {/* THE STATE CELL EARNS ITS PLACE ONLY WHEN IT SAYS SOMETHING THE VALUE CELL DOES NOT.
            A row with no value already prints its state where the value would be, so this cell was
            printing the same word a second time on the same line: `Dielectric  Not Reported  Not
            Reported`, and `Tolerance  Missing  Missing`. That doubled the visual weight of exactly
            the rows carrying the least information. One of the two, never both - and the one kept is
            the value cell, because that is where the reader is already looking. The nine quality
            words themselves are untouched: `Missing`, `Not Reported` and `Not Applicable` remain
            distinct, and `data-spec-state` still carries the state for anything asserting on it. */}
        {/* The state cell earns its place only for an EXCEPTIONAL state. A row with no value
            already prints its state where the value would be (it was printing the same word twice
            on one line: `Dielectric  Not Reported  Not Reported`), and `Unverified` is true of
            nearly every value that has one. A conflict gets a marker instead of a sentence. */}
        {noValue || state === "unverified" ? null : state === "conflicting" ? (
          <span
            data-dev-id="component-browser.spec-conflict-marker"
            aria-label={stateText.conflicting}
            title={stateText.conflicting}
            className="flex-none text-warn"
          >
            <Icon id="status.warn" className="h-3 w-3" />
          </span>
        ) : (
          <StatusText tone={specRowTone(state)} className="flex-none">
            <SpecStateLabel state={state} />
          </StatusText>
        )}
        {hasEvidence ? (
          <button
            type="button"
            data-dev-id="component-browser.spec-evidence-toggle"
            aria-expanded={open}
            aria-label={evidenceLabel({ label: record.label })}
            // The tooltip carries the same complete phrase the accessible name does, because the
            // visible text is now a chevron.
            title={evidenceLabel({ label: record.label })}
            onClick={() => setOpen((current) => !current)}
            className={
              "ui-component-metadata flex-none rounded-control px-1 text-t3 transition-colors " +
              "hover:bg-control-hover hover:text-t1 focus-visible:outline focus-visible:outline-2 " +
              "focus-visible:outline-offset-1 focus-visible:outline-focus"
            }
          >
            {/* `{count} other` stays a WORD, because the number is real information the glyph
                cannot carry. With no alternates the control said `Evidence` on nearly every row of
                the column - a column of one repeated word - so it becomes a disclosure chevron. The
                complete action name is still on the control, in `aria-label` and as its tooltip,
                which is what an icon-only control owes a keyboard and a screen reader. */}
            {alternates.length > 0 ? (
              <Text
                id="component-browser.spec-alternate-count"
                values={{ count: alternates.length }}
              >
                {"{count} other"}
              </Text>
            ) : (
              <Icon
                id="detail.chevron-right"
                className={
                  "h-3 w-3 transition-transform duration-150 " + (open ? "rotate-90" : "")
                }
              />
            )}
          </button>
        ) : null}
      </div>

      {record.constraintViolation ? (
        // Reported, and the value is left exactly as the source gave it. Rewriting a distributor's
        // answer to satisfy our own rule would hide the disagreement that matters.
        <p
          data-dev-id="component-browser.spec-constraint"
          className="ui-component-metadata px-2 pb-1 pl-[10rem] text-warn"
        >
          <Text
            id="component-browser.spec-constraint-violation"
            values={{ detail: record.constraintViolation }}
          >
            {"Outside the class constraint: {detail}"}
          </Text>
        </p>
      ) : null}

      {open ? (
        <SpecificationEvidence
          record={record}
          alternates={alternates}
          busy={busy}
          failure={failure}
          onFailure={setFailure}
          onWrite={onWrite}
          sourceUrl={sourceUrl}
        />
      ) : null}
    </div>
  );
}

/**
 * The evidence behind one value: what is in force, what else was offered, and what can be done.
 *
 * Source ordering is fixed by the product. This surface shows competing evidence, permits an
 * explicit reviewed override, and opens the source when a real destination exists.
 */
function SpecificationEvidence({
  record,
  alternates,
  busy,
  failure,
  onFailure,
  onWrite,
  sourceUrl,
}: {
  record: SpecificationRecord;
  alternates: SourceCandidate[];
  busy: boolean;
  failure: string;
  onFailure: (message: string) => void;
  onWrite: (write: SpecificationWrite) => Promise<unknown>;
  sourceUrl: (sourceId: string) => string;
}) {
  const [editing, setEditing] = useState(false);
  // Where focus goes when the editor closes. An editor that dumps focus on the body leaves a
  // keyboard user at the top of the document, having lost the row they were working on.
  const panelRef = useRef<HTMLDivElement | null>(null);
  const preferred = record.preferredSource;
  // Stated by the projection, not inferred from the winning source's id. A reviewed decision is a
  // fact about the record; reading it back out of the value it produced is how the two disagree.
  const override = record.override;
  const pin = record.preferredSourcePin;
  const overridden = override !== null;
  // NOT named `use...`: it is the formatter a hook returned, not a hook, and it is called inside a
  // `.map()` below. A plain function wearing the hook prefix makes the rules-of-hooks check
  // unenforceable exactly where it matters, and reads as a conditional hook call to anyone scanning.
  const viewSourceLabel = useCopyFormatter("component-browser.spec-view-source", "View {source}");
  const writeFailed = useText(
    "component-browser.spec-write-failed",
    "That change was not saved. The value below is still what the catalog holds.",
  );

  async function run(write: SpecificationWrite): Promise<void> {
    onFailure("");
    try {
      await onWrite(write);
      setEditing(false);
    } catch (error) {
      // The row REVERTS - nothing was written to the cache - and says so. A write that silently
      // appears to have saved is worse than one that visibly did not.
      onFailure(error instanceof Error && error.message ? error.message : writeFailed);
    }
  }

  return (
    <div
      ref={panelRef}
      data-dev-id="component-browser.spec-provenance"
      // OPAQUE. `bg-band/60` compounded against whatever row it opened under, so the attached
      // evidence read differently on an even row than on an odd one; the alternating-row tint is
      // the surface a data row actually sits on, so the drawer takes it outright.
      className="flex flex-col gap-1 border-t border-line/60 bg-row-alt px-2 py-1.5 pl-[10rem]"
    >
      {preferred ? (
        <p className="ui-component-metadata">
          <Text
            id="component-browser.spec-in-force"
            values={{ source: preferred.sourceLabel, tier: preferred.tierLabel }}
          >
            {"In force from {source} ({tier})"}
          </Text>
          <RetrievedAt at={preferred.retrievedAt} />
        </p>
      ) : (
        <p className="ui-component-metadata">
          <Text id="component-browser.spec-no-source">No source has offered a value.</Text>
        </p>
      )}

      {override && override.replacedSource ? (
        <p data-dev-id="component-browser.spec-override-replaced" className="ui-component-metadata">
          <Text
            id="component-browser.spec-override-replaced"
            values={{
              value: override.replacedValue ?? "",
              source: override.replacedSourceLabel || override.replacedSource,
            }}
          >
            {"Reviewed value, overriding {value} from {source}"}
          </Text>
        </p>
      ) : null}

      {pin ? (
        <p
          data-dev-id="component-browser.spec-pin-state"
          data-pin-in-force={pin.inForce ? "true" : "false"}
          className="ui-component-metadata"
        >
          {pin.inForce ? (
            <Text
              id="component-browser.spec-pin-in-force"
              values={{ source: pin.sourceLabel || pin.sourceId }}
            >
              {"Pinned to {source}"}
            </Text>
          ) : overridden ? (
            // A pin that reports itself in force while an override decides the value is a control
            // that lies about what it did, so say which one is actually deciding.
            <Text
              id="component-browser.spec-pin-outranked"
              values={{ source: pin.sourceLabel || pin.sourceId }}
            >
              {"Pinned to {source}, not in force while a reviewed value stands"}
            </Text>
          ) : (
            <Text
              id="component-browser.spec-pin-silent"
              values={{ source: pin.sourceLabel || pin.sourceId }}
            >
              {"Pinned to {source}, not in force because it no longer offers this field"}
            </Text>
          )}
        </p>
      ) : null}

      {alternates.length > 0 ? (
        <ul data-dev-id="component-browser.spec-alternates" className="flex flex-col gap-1">
          {alternates.map((candidate) => (
            <li
              key={`${candidate.sourceId}:${candidate.originalKey}:${candidate.displayValue}`}
              data-dev-id="component-browser.spec-alternate"
              className="flex flex-wrap items-baseline gap-1.5"
            >
              <span className="ui-property-value">{candidate.displayValue}</span>
              <span className="ui-component-metadata">
                {`${candidate.sourceLabel} · ${candidate.tierLabel}`}
                <RetrievedAt at={candidate.retrievedAt} />
              </span>
              {sourceUrl(candidate.sourceId) ? (
                <a
                  data-dev-id="component-browser.spec-view-source"
                  href={sourceUrl(candidate.sourceId)}
                  target="_blank"
                  rel="noreferrer"
                  aria-label={viewSourceLabel({ source: candidate.sourceLabel })}
                  title={viewSourceLabel({ source: candidate.sourceLabel })}
                  className={
                    "inline-flex flex-none items-center rounded-control p-0.5 text-t2 " +
                    "transition-colors hover:text-t1 focus-visible:outline focus-visible:outline-2 " +
                    "focus-visible:outline-offset-1 focus-visible:outline-focus"
                  }
                >
                  <ExternalIcon className="h-3.5 w-3.5" />
                </a>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}

      {editing ? (
        <SpecificationEditor
          record={record}
          busy={busy}
          failure={failure}
          onCancel={() => {
            setEditing(false);
            // Deferred one frame: the control does not exist until the editor has unmounted.
            requestAnimationFrame(() =>
              panelRef.current
                ?.querySelector<HTMLButtonElement>(
                  '[data-dev-id="component-browser.spec-add-override"]',
                )
                ?.focus(),
            );
          }}
          onSubmit={run}
        />
      ) : (
        <div className="flex flex-wrap items-center gap-1.5">
          {/* A field the category says this kind of component does not have is not a gap
              somebody can fill, so the control that would fill it is not offered at all rather
              than offered and refused. */}
          {record.applicability === "not_applicable" ? null : (
            <Button
              small
              data-dev-id="component-browser.spec-add-override"
              disabled={busy}
              onClick={() => setEditing(true)}
            >
              {overridden ? (
                <Text id="component-browser.spec-edit-override">Edit Override</Text>
              ) : (
                <Text id="component-browser.spec-add-override">Add Override</Text>
              )}
            </Button>
          )}
          {overridden ? (
            <Button
              small
              data-dev-id="component-browser.spec-clear-override"
              disabled={busy}
              onClick={() => void run({ kind: "clear-override", key: record.key })}
            >
              <Text id="component-browser.spec-clear-override">Clear Override</Text>
            </Button>
          ) : null}
        </div>
      )}

      {failure && !editing ? (
        // A write that came from one of the row's own controls rather than the editor. It still
        // lands on the surface that failed, beside the control that ran it.
        <p
          data-dev-id="component-browser.spec-write-failed"
          role="alert"
          className="ui-component-metadata text-err-text"
        >
          {failure}
        </p>
      ) : null}
    </div>
  );
}
/**
 * When a source last said this.
 *
 * The relative form is what a person reads at a glance, and it is only honest with the exact time
 * one hover away - "4 min ago" cannot be turned back into a date, and a retrieval time nobody can
 * pin down is a retrieval time nobody can act on. `formatTimestamp` returns the pair together for
 * exactly that reason, so the half that makes it honest cannot be dropped.
 */
function RetrievedAt({ at }: { at: string }) {
  const stamp = formatTimestamp(at);
  const label = useCopyFormatter("component-browser.spec-retrieved", "Retrieved {when}");
  if (!stamp.text) return null;
  return (
    <span className="ui-component-metadata" title={stamp.title}>
      {` · ${label({ when: stamp.text })}`}
    </span>
  );
}
