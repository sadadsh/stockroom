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
import { Button, StatusText } from "../primitives";
import { ExternalIcon } from "../icons";
import {
  alternateCandidates,
  displayWithUnit,
  isEmptyState,
  specRowTone,
} from "./specificationRows";
import { SpecificationEditor } from "./SpecificationEditor";
import { SpecStateLabel } from "./SpecificationState";

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
      className="border-b border-line/60 last:border-b-0"
    >
      <div className="flex min-h-[24px] items-baseline gap-2 px-2 py-1">
        <span className="ui-property-label w-[9.5rem] flex-none break-words">{record.label}</span>
        <span
          data-dev-id="component-browser.spec-value"
          // Wraps, never truncates: a value is often the ONLY representation of itself on the
          // screen, and half of one is not a smaller version of it. Tabular figures so a column
          // of measurements stacks on its place values instead of reflowing as it updates.
          className={
            "min-w-0 flex-1 break-words tnum ui-property-value" +
            (noValue ? " ui-disabled" : "") +
            (prominent && !noValue ? " font-medium" : "")
          }
        >
          {value || <SpecStateLabel state={state} />}
        </span>
        {preferred?.sourceLabel ? (
          <span
            data-dev-id="component-browser.spec-source"
            className="ui-component-metadata max-w-[7rem] flex-none break-words text-right"
            title={preferred.tierLabel}
          >
            {preferred.sourceLabel}
          </span>
        ) : null}
        <StatusText tone={specRowTone(state)} className="flex-none">
          <SpecStateLabel state={state} />
        </StatusText>
        {hasEvidence ? (
          <button
            type="button"
            data-dev-id="component-browser.spec-evidence-toggle"
            aria-expanded={open}
            aria-label={evidenceLabel({ label: record.label })}
            onClick={() => setOpen((current) => !current)}
            className={
              "ui-component-metadata flex-none rounded-control px-1 text-t3 transition-colors " +
              "hover:bg-control-hover hover:text-t1 focus-visible:outline focus-visible:outline-2 " +
              "focus-visible:outline-offset-1 focus-visible:outline-focus"
            }
          >
            {alternates.length > 0 ? (
              <Text
                id="component-browser.spec-alternate-count"
                values={{ count: alternates.length }}
              >
                {"{count} other"}
              </Text>
            ) : (
              <Text id="component-browser.spec-evidence-open">Evidence</Text>
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
            {"Outside the category constraint: {detail}"}
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
 * Every control here has an endpoint behind it. `Use <Source> Value` sets the preferred source,
 * `Add Override` records a reviewed value, `Clear Override` withdraws one, and `View Source` opens
 * the place the source can actually be read. A control with nowhere to go is not rendered at all.
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
  const useValueLabel = useCopyFormatter(
    "component-browser.spec-use-value",
    "Use {source} Value",
  );
  const viewSourceLabel = useCopyFormatter("component-browser.spec-view-source", "View {source}");
  const writeFailed = useText(
    "component-browser.spec-write-failed",
    "That change was not saved. The value below is still what the library holds.",
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
      className="flex flex-col gap-1 border-t border-line/60 bg-band/60 px-2 py-1.5 pl-[10rem]"
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
              <Button
                small
                data-dev-id="component-browser.spec-use-alternate"
                data-source-id={candidate.sourceId}
                disabled={busy}
                onClick={() =>
                  void run({
                    kind: "set-preferred-source",
                    key: record.key,
                    sourceId: candidate.sourceId,
                  })
                }
              >
                {useValueLabel({ source: candidate.sourceLabel })}
              </Button>
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
          {preferred && !overridden && record.sourceCandidates.length > 1 ? (
            <Button
              small
              data-dev-id="component-browser.spec-clear-preferred-source"
              disabled={busy}
              onClick={() => void run({ kind: "clear-preferred-source", key: record.key })}
            >
              <Text id="component-browser.spec-clear-preferred-source">Use Ranked Source</Text>
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
          className="ui-component-metadata text-err"
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
