/**
 * Data provenance and history: where every answer above came from, and what has happened to it.
 *
 * It is LAST in the column and that placement is the point. "DigiKey supplied data, Mouser is not
 * connected" is an explanation, and an explanation is only wanted once the thing it explains has
 * been read. A source ledger at the top of a sourcing column answers a question nobody has yet
 * asked, above the stock figure they opened the component for.
 *
 * Six questions, in the order a person asks them once they have decided to doubt something:
 * which sources are involved, where do they disagree, what has a person already decided, how did
 * the data get here, what has changed since, and - only in developer mode - what does the storage
 * actually look like.
 *
 * THE TRANSLATION RULE. Nothing on this surface shows a raw backend key, a schema number or a
 * projection version. Those are true and they are useless: a person reading "Schema version 4"
 * cannot do anything with it, and a person reading "1 field was created by a newer Stockroom
 * version and is read-only" can. `provenanceText.tsx` owns every one of those translations, and
 * the raw forms are confined to Technical Diagnostics, which only appears in developer mode.
 */
import { useState, type ReactNode } from "react";
import type {
  CompatibilityView,
  DossierDiagnostics,
  FieldConflictView,
  ManualOverrideView,
  ProvenanceView,
  RevisionEvent,
} from "../../api/dossierTypes";
import { Text, useCopyFormatter, useText } from "../../lib/copy";
import { useDevMode } from "../../lib/devMode";
import { formatTimestamp } from "../../lib/formatValue";
import { Button, StatusText } from "../primitives";
import { SourcingSection, SourcingSubSection } from "./SourcingParts";
import { SourceStateLabel, useCompatibilityNotice } from "./provenanceText";
import { sourceStateOf, sourceStateTone } from "./provenanceVocabulary";

export function ProvenanceHistory({
  provenance,
  revisions,
  diagnostics,
  onViewProvenance,
}: {
  provenance: ProvenanceView;
  revisions: readonly RevisionEvent[];
  diagnostics: DossierDiagnostics;
  /** The full ledger, for the reader who wants every candidate rather than every disagreement. */
  onViewProvenance: () => void;
}) {
  const { enabled: developerMode } = useDevMode();
  const intake = revisions.filter((event) => event.section === "intake");
  const changes = revisions.filter((event) => event.section === "changes");
  // The five names, resolved through the SAME copy ids the sub-headings carry, so rewording one
  // rewords both and the summary can never name a section by a word the heading does not use.
  const sourcesTitle = useText("component-browser.sources-title", "Data Sources");
  const conflictsTitle = useText("component-browser.conflicts-title", "Field Conflicts");
  const overridesTitle = useText("component-browser.overrides-title", "Manual Overrides");
  const intakeTitle = useText(
    "component-browser.intake-title",
    "Import and Enrichment Timeline",
  );
  const revisionsTitle = useText("component-browser.revisions-title", "Revision Timeline");

  // Five headings and five sentences to say nothing happened is what this block used to render on
  // any component nobody had sourced. Each sub-section now appears only when it has rows, and the
  // silent ones are NAMED ONCE on a single metadata line - so "which of the five is empty" is
  // still answerable, in one line instead of ten.
  const silent = [
    provenance.sources.length === 0 ? sourcesTitle : "",
    provenance.conflicts.length === 0 ? conflictsTitle : "",
    provenance.manualOverrides.length === 0 ? overridesTitle : "",
    intake.length === 0 ? intakeTitle : "",
    changes.length === 0 ? revisionsTitle : "",
  ].filter(Boolean);

  return (
    <SourcingSection
      devId="component-browser.provenance"
      title={
        <Text id="component-browser.provenance-title">Sources and Timeline</Text>
      }
      collapsed
    >
      <CompatibilityBanner compatibility={provenance.compatibility} />
      {provenance.sources.length > 0 ? <DataSources sources={provenance.sources} /> : null}
      {provenance.conflicts.length > 0 ? (
        <FieldConflicts conflicts={provenance.conflicts} />
      ) : null}
      {provenance.manualOverrides.length > 0 ? (
        <ManualOverrides overrides={provenance.manualOverrides} />
      ) : null}
      {intake.length > 0 ? (
        <History
          devId="component-browser.provenance-intake"
          title={<Text id="component-browser.intake-title">Import and Enrichment Timeline</Text>}
          events={intake}
        />
      ) : null}
      {changes.length > 0 ? (
        <History
          devId="component-browser.provenance-revisions"
          title={<Text id="component-browser.revisions-title">Revision Timeline</Text>}
          events={changes}
        />
      ) : null}
      <NothingRecorded sections={silent} />
      {/* Developer territory only. A storage key is the honest answer to exactly one question, and
          nobody opens a component to ask it. */}
      {developerMode ? <TechnicalDiagnostics diagnostics={diagnostics} /> : null}
      <div className="px-2 py-1">
        <Button small data-dev-id="component-browser.provenance-all" onClick={onViewProvenance}>
          <Text id="component-browser.provenance-all">View Data Provenance</Text>
        </Button>
      </div>
    </SourcingSection>
  );
}

/**
 * The silent sub-sections, as one line.
 *
 * Middle dots rather than a sentence each, because this is compact metadata and that is what the
 * separator vocabulary is for. It is a STATEMENT, not a control: nothing here can be clicked, and
 * the full ledger is one button below.
 */
function NothingRecorded({ sections }: { sections: readonly string[] }) {
  const line = useCopyFormatter(
    "component-browser.provenance-nothing",
    "Nothing recorded: {sections}",
  );
  if (sections.length === 0) return null;
  return (
    <p
      data-dev-id="component-browser.provenance-nothing"
      className="ui-component-metadata border-b border-line/60 px-2 py-1"
    >
      {line({ sections: sections.join(" · ") })}
    </p>
  );
}

/**
 * The one diagnostic that is also a consequence, said as the consequence.
 *
 * The affected fields are named on request rather than listed by default: the count is what makes
 * the warning actionable, and the names are what makes it checkable.
 */
function CompatibilityBanner({ compatibility }: { compatibility: CompatibilityView }) {
  const [open, setOpen] = useState(false);
  const viewLabel = useText("component-browser.compatibility-view", "View Affected Fields");
  const hideLabel = useText("component-browser.compatibility-hide", "Hide Affected Fields");
  const notice = useCompatibilityNotice(compatibility);
  if (!notice) return null;
  return (
    <div data-dev-id="component-browser.compatibility-notice" className="px-2 py-1">
      {/* The sentence was already resolved through the copy layer by `useCompatibilityNotice`,
          which is where its ids and its count live. Wrapping it in a second copy id would
          register a default that changes with the data. */}
      <p className="ui-property-value text-warn">{notice.text}</p>
      {notice.fields.length > 0 ? (
        <>
          <Button
            small
            data-dev-id="component-browser.compatibility-view"
            aria-expanded={open}
            onClick={() => setOpen((current) => !current)}
            className="mt-1"
          >
            {open ? hideLabel : viewLabel}
          </Button>
          {open ? (
            <ul className="mt-1 flex flex-col">
              {notice.fields.map((field) => (
                <li
                  key={`${field.origin}:${field.key}`}
                  data-dev-id="component-browser.compatibility-field"
                  className="ui-property-value py-0.5"
                >
                  {field.label}
                </li>
              ))}
            </ul>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

/**
 * `Source | Fields Used | Retrieved | State` - the user-facing shape of the ledger.
 *
 * Four columns, because those are the four things a person checks: who is involved, how much of
 * what is on screen came from them, how old it is, and whether they actually answered.
 */
function DataSources({ sources }: { sources: ProvenanceView["sources"] }) {
  const tableLabel = useText("component-browser.provenance-sources", "Data sources");
  return (
    <SourcingSubSection
      devId="component-browser.provenance-sources"
      title={<Text id="component-browser.sources-title">Data Sources</Text>}
      count={sources.length}
    >
      <div className="overflow-x-auto">
        <table className="w-full border-collapse" aria-label={tableLabel}>
            <thead>
              <tr className="border-b border-line-dark [&>th]:border-r [&>th]:border-line/50 [&>th:last-child]:border-r-0">
                <th scope="col" className="ui-table-header px-2 py-1 text-left">
                  <Text id="component-browser.source-col-source">Source</Text>
                </th>
                <th scope="col" className="ui-table-header px-2 py-1 text-right">
                  <Text id="component-browser.source-col-fields">Fields Used</Text>
                </th>
                <th scope="col" className="ui-table-header px-2 py-1 text-left">
                  <Text id="component-browser.source-col-retrieved">Retrieved</Text>
                </th>
                <th scope="col" className="ui-table-header px-2 py-1 text-left">
                  <Text id="component-browser.source-col-state">State</Text>
                </th>
              </tr>
            </thead>
            <tbody>
              {sources.map((source) => {
                const state = sourceStateOf(source.state);
                const stamp = source.fetchedAt ? formatTimestamp(source.fetchedAt) : null;
                return (
                  <tr
                    key={source.id}
                    data-dev-id="component-browser.source-state"
                    // Same grid treatment as the offers table: alternating tint, 1px cell rules.
                    className="border-b border-line/60 last:border-b-0 even:bg-row-alt [&>td]:border-r [&>td]:border-line/50 [&>td:last-child]:border-r-0"
                  >
                    <td className="px-2 py-1 align-baseline">
                      <span className="ui-row-secondary block truncate">{source.label}</span>
                    </td>
                    <td className="px-2 py-1 align-baseline">
                      <span className="ui-property-value ui-numeric block">
                        {source.fieldCount}
                      </span>
                    </td>
                    <td className="px-2 py-1 align-baseline">
                      <span
                        className="ui-component-metadata block truncate"
                        title={stamp?.title}
                      >
                        {stamp?.text ?? ""}
                      </span>
                    </td>
                    <td className="px-2 py-1 align-baseline">
                      <StatusText tone={sourceStateTone(state)}>
                        <SourceStateLabel state={state} />
                      </StatusText>
                    </td>
                  </tr>
                );
              })}
          </tbody>
        </table>
      </div>
    </SourcingSubSection>
  );
}

/** Where the sources disagree, as fields with named answers rather than as a state on a key. */
function FieldConflicts({ conflicts }: { conflicts: readonly FieldConflictView[] }) {
  const inForceLabel = useText("component-browser.conflict-in-force", "In force");
  return (
    <SourcingSubSection
      devId="component-browser.provenance-conflicts"
      title={<Text id="component-browser.conflicts-title">Field Conflicts</Text>}
      count={conflicts.length}
    >
      {conflicts.map((conflict) => (
          <div
            key={conflict.field}
            data-dev-id="component-browser.conflict-row"
            data-conflict-field={conflict.field}
            className="border-b border-line/60 px-2 py-1 last:border-b-0"
          >
            <span className="ui-row-secondary block truncate">{conflict.label}</span>
            <ul className="flex flex-col">
              {conflict.candidates.map((candidate) => (
                <li
                  key={`${candidate.sourceId}:${candidate.displayValue}`}
                  className="flex items-baseline gap-1.5"
                >
                  <span className="ui-property-value min-w-0 flex-1 break-words">
                    {candidate.displayValue}
                  </span>
                  <span className="ui-component-metadata flex-none truncate">
                    {candidate.sourceLabel}
                  </span>
                  {candidate.inForce ? (
                    <StatusText tone="ok" className="flex-none">
                      {inForceLabel}
                    </StatusText>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        ))}
    </SourcingSubSection>
  );
}

/**
 * What a person has already decided, and what it displaced.
 *
 * A typed value and a pinned source are different decisions and are reported differently: showing
 * a pin as a value would put a blank where a real answer is in force.
 */
function ManualOverrides({ overrides }: { overrides: readonly ManualOverrideView[] }) {
  const replacedText = useCopyFormatter(
    "component-browser.override-replaced",
    "Replaced {value} from {source}",
  );
  const pinnedText = useCopyFormatter(
    "component-browser.override-pinned",
    "Pinned to {source}",
  );
  const reviewedText = useCopyFormatter(
    "component-browser.override-reviewed",
    "Reviewer {who}",
  );
  return (
    <SourcingSubSection
      devId="component-browser.provenance-overrides"
      title={<Text id="component-browser.overrides-title">Manual Overrides</Text>}
      count={overrides.length}
    >
      {overrides.map((override) => {
          const stamp = override.reviewedAt ? formatTimestamp(override.reviewedAt) : null;
          return (
            <div
              key={override.field}
              data-dev-id="component-browser.override-row"
              data-override-field={override.field}
              className="border-b border-line/60 px-2 py-1 last:border-b-0"
            >
              <span className="ui-row-secondary block truncate">{override.field}</span>
              <span className="ui-property-value block break-words">
                {override.hasValue
                  ? String(override.value ?? "")
                  : pinnedText({
                      source: override.preferredSourceLabel || override.preferredSource,
                    })}
              </span>
              <span className="ui-component-metadata block break-words" title={stamp?.title}>
                {[
                  override.replacedSource
                    ? replacedText({
                        value: String(override.replacedValue ?? ""),
                        source: override.replacedSourceLabel || override.replacedSource,
                      })
                    : "",
                  override.reviewedBy ? reviewedText({ who: override.reviewedBy }) : "",
                  stamp?.text ?? "",
                  override.note,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
            </div>
          );
        })}
    </SourcingSubSection>
  );
}

/**
 * One dated history. The projection decided which events belong in it; this renders them.
 *
 * It is only mounted when it HAS events: the "nothing happened" case is one shared line in
 * `NothingRecorded`, not a heading and a sentence per history.
 */
function History({
  devId,
  title,
  events,
}: {
  devId: string;
  title: ReactNode;
  events: readonly RevisionEvent[];
}) {
  const undated = useText("component-browser.undated", "Undated");
  return (
    <SourcingSubSection devId={devId} title={title} count={events.length}>
      <ul className="flex flex-col">
          {events.map((event, index) => {
            const stamp = event.at ? formatTimestamp(event.at) : null;
            return (
              <li
                key={`${event.kind}:${event.at}:${index}`}
                data-dev-id="component-browser.history-event"
                data-event-kind={event.kind}
                className="flex items-baseline gap-2 border-b border-line/60 px-2 py-1 last:border-b-0"
              >
                <span className="ui-property-value min-w-0 flex-1 break-words">
                  {event.summary}
                </span>
                <span
                  className="ui-component-metadata flex-none truncate"
                  title={stamp?.title}
                >
                  {stamp?.text ?? undated}
                </span>
              </li>
            );
          })}
      </ul>
    </SourcingSubSection>
  );
}

/**
 * The storage truth, in developer mode only.
 *
 * Monospace, because this genuinely is text a machine wrote: schema numbers, derivation
 * identifiers, content hashes and the keys a newer build left behind. That is exactly the audience
 * it is for, and exactly why it is not on the normal path.
 */
function TechnicalDiagnostics({ diagnostics }: { diagnostics: DossierDiagnostics }) {
  const none = useText("component-browser.diagnostics-none", "None");
  const rows: Array<[string, string, string]> = [
    [
      "component-browser.diag-record-schema",
      "Record schema",
      String(diagnostics.recordSchemaVersion),
    ],
    ["component-browser.diag-derived-by", "Derivation", diagnostics.derivedBy || none],
    ["component-browser.diag-category", "Category schema", diagnostics.categorySchema || none],
    ["component-browser.diag-symbol-hash", "Symbol hash", diagnostics.hashes.symbolContent || none],
    [
      "component-browser.diag-footprint-hash",
      "Footprint hash",
      diagnostics.hashes.footprintContent || none,
    ],
    ["component-browser.diag-model-hash", "Model hash", diagnostics.hashes.modelFile || none],
    [
      "component-browser.diag-unknown-keys",
      "Keys this build does not read",
      diagnostics.unknownKeys.join(", ") || none,
    ],
  ];
  return (
    <SourcingSubSection
      devId="component-browser.provenance-diagnostics"
      title={<Text id="component-browser.diagnostics-title">Technical Diagnostics</Text>}
    >
      <dl className="flex flex-col">
        {rows.map(([id, label, value]) => (
          <div
            key={id}
            className="flex items-baseline gap-2 border-b border-line/60 px-2 py-1 last:border-b-0"
          >
            <dt className="ui-property-label w-[7.5rem] flex-none">
              <Text id={id}>{label}</Text>
            </dt>
            <dd className="ui-machine-text min-w-0 flex-1 truncate" title={value}>
              {value}
            </dd>
          </div>
        ))}
      </dl>
    </SourcingSubSection>
  );
}
