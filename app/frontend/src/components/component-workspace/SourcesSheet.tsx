/**
 * Sources & History, in full: where every answer came from, what was captured, what changed, and
 * the technical truth underneath.
 *
 * Four tabs, because these are four different questions and answering them on one sheet made the
 * old surface a list of everything nobody could navigate:
 *
 *   Field Sources  - which value is in force for each field, who said it, what else was offered.
 *   Source Records - what was actually captured from each source, and what happened to it.
 *   Changes        - the component's git timeline, from the SAME endpoints the detail sheet used.
 *   Diagnostics    - schema, derivation, hashes, unknown keys, raw record. Collapsed by default.
 *
 * Diagnostics is collapsed on purpose. It is real, reachable technical truth, and it is also the
 * one region here nobody opens a component to read - leaving it expanded would put record hashes
 * above the question the person came with.
 */
import { useState, type ReactNode } from "react";
import {
  usePartDetailQuery,
  usePartDiff,
  usePartHistory,
} from "../../api/queries";
import type {
  CompatibilityView,
  DossierDiagnostics,
  ProvenanceView,
  RecordFieldView,
  SourceLedgerEntry,
} from "../../api/dossierTypes";
import { Text, useCopyFormatter, useText } from "../../lib/copy";
import { useDevMode } from "../../lib/devMode";
import { formatTimestamp } from "../../lib/formatValue";
import {
  Badge,
  Button,
  DataTable,
  EmptyState,
  ErrorState,
  LoadingState,
  Section,
  TabPanel,
  TabStrip,
  type TabItem,
} from "../primitives";
import { DiffModal } from "../DiffModal";
import { SourceNote, SourceStateBadge } from "./SheetParts";
import { SpecStateLabel } from "./SpecificationState";
import { useCompatibilityNotice } from "./provenanceText";
import { humanizeKey } from "./provenanceVocabulary";
import { canApplyAlternate, otherCandidates } from "./sourceCandidates";

export type SourcesSheetTab = "fields" | "records" | "changes" | "diagnostics";

const SOURCES_TABS: readonly TabItem<SourcesSheetTab>[] = [
  { id: "fields", label: "Field Sources", copyId: "component-browser.sources-tab-fields" },
  { id: "records", label: "Source Records", copyId: "component-browser.sources-tab-records" },
  { id: "changes", label: "Changes", copyId: "component-browser.sources-tab-changes" },
  {
    id: "diagnostics",
    label: "Technical Diagnostics",
    copyId: "component-browser.sources-tab-diagnostics",
  },
];

export function SourcesSheet({
  componentId,
  componentName,
  provenance,
  diagnostics,
  onApplyAlternate,
  applying,
  refresh,
  enrich,
}: {
  componentId: string;
  /** The display name the nested visual diff titles itself with. */
  componentName: string;
  provenance: ProvenanceView;
  diagnostics: DossierDiagnostics;
  onApplyAlternate: (fieldId: string, value: unknown) => void;
  applying: boolean;
  /** The sourcing refresh action, owned by the workspace so the job lives above this sheet. */
  refresh: { run: () => void; running: boolean };
  /** The enrichment surface, passed in so this sheet never re-implements enrichment. */
  enrich: ReactNode;
}) {
  const [tab, setTab] = useState<SourcesSheetTab>("fields");
  const tabsLabel = useText("component-browser.sources-tabs", "Sources and timeline");

  return (
    <div data-dev-id="component-browser.sources-sheet" className="flex flex-col gap-3">
      <TabStrip
        tabs={SOURCES_TABS}
        active={tab}
        onSelect={setTab}
        idBase="component-sources"
        devIdBase="component-browser.sources"
        density="compact"
        aria-label={tabsLabel}
      />
      <TabPanel idBase="component-sources" tab={tab}>
        {tab === "fields" ? (
          <FieldSourcesPanel
            fields={provenance.recordFields}
            onApplyAlternate={onApplyAlternate}
            applying={applying}
          />
        ) : tab === "records" ? (
          <SourceRecordsPanel sources={provenance.sources} refresh={refresh} enrich={enrich} />
        ) : tab === "changes" ? (
          <ChangesPanel componentId={componentId} componentName={componentName} />
        ) : (
          <DiagnosticsPanel
            componentId={componentId}
            diagnostics={diagnostics}
            compatibility={provenance.compatibility}
          />
        )}
      </TabPanel>
    </div>
  );
}

// ------------------------------------------------------------------ field sources

function FieldSourcesPanel({
  fields,
  onApplyAlternate,
  applying,
}: {
  fields: RecordFieldView[];
  onApplyAlternate: (fieldId: string, value: unknown) => void;
  applying: boolean;
}) {
  const emptyValue = useText("component-browser.no-value", "None");
  const tableLabel = useText("component-browser.field-sources-title", "Attributed Fields");
  const applyLabel = useText("component-browser.field-apply", "Commit");

  if (fields.length === 0) {
    return (
      <EmptyState id="component-browser.field-sources-empty">
        No field carries an attribution.
      </EmptyState>
    );
  }
  return (
    <Section
      title="Attributed Fields"
      copyId="component-browser.field-sources-title"
      count={fields.length}
      note={
        <Text id="component-browser.field-sources-note">
          The value in force for each field, the source that supplied it, and all other answers
          that were offered. Committing an alternate records which source it came from.
        </Text>
      }
    >
      <DataTable
        label={tableLabel}
        headings={[
          <Text key="f" id="component-browser.field-col-name">
            Field
          </Text>,
          <Text key="v" id="component-browser.field-col-value">
            In Force
          </Text>,
          <Text key="s" id="component-browser.field-col-source">
            Source
          </Text>,
          <Text key="a" id="component-browser.field-col-state">
            Agreement
          </Text>,
        ]}
      >
        {fields.map((field) => (
          <tr
            key={field.key}
            data-dev-id="component-browser.field-source-row"
            className="border-b border-line/60 align-top last:border-b-0"
          >
            <td className="px-3 py-1.5 text-t2">{field.label}</td>
            <td className="px-3 py-1.5">
              <span className="tnum font-mono text-t1">{field.displayValue || emptyValue}</span>
              {otherCandidates(field).length > 0 ? (
                <ul className="mt-1 flex flex-col gap-1">
                  {otherCandidates(field).map((alternate) => (
                    <li
                      key={`${alternate.sourceId}:${alternate.displayValue}`}
                      className="flex items-baseline gap-2 text-2xs text-t3"
                    >
                      <span className="tnum font-mono">
                        {alternate.displayValue || emptyValue}
                      </span>
                      <span>{alternate.sourceLabel || alternate.sourceId}</span>
                      {canApplyAlternate(field.key, alternate) ? (
                        <button
                          type="button"
                          data-dev-id="component-browser.field-source-apply"
                          disabled={applying}
                          aria-label={`${applyLabel} ${alternate.displayValue} ${field.label}`}
                          onClick={() => onApplyAlternate(field.key, alternate.value)}
                          className="rounded-control px-1 font-medium text-acc transition-colors hover:brightness-125 disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc"
                        >
                          {applyLabel}
                        </button>
                      ) : null}
                    </li>
                  ))}
                </ul>
              ) : null}
            </td>
            <td className="px-3 py-1.5">
              <SourceNote source={field.preferredSource} />
              {field.preferredSource?.retrievedAt ? (
                <span className="mt-0.5 block text-2xs text-t3">
                  {formatTimestamp(field.preferredSource.retrievedAt).text}
                </span>
              ) : null}
            </td>
            <td className="px-3 py-1.5">
              {/* The quality vocabulary, not the storage token. `unverified` is a state name in
                  the record; `Unverified` is the word a person reads everywhere else. */}
              <Badge size="sm" tone={field.conflictState === "conflicting" ? "warn" : "neutral"}>
                <SpecStateLabel state={field.verificationState} />
              </Badge>
            </td>
          </tr>
        ))}
      </DataTable>
    </Section>
  );
}

// ------------------------------------------------------------------ source records

function SourceRecordsPanel({
  sources,
  refresh,
  enrich,
}: {
  sources: SourceLedgerEntry[];
  refresh: { run: () => void; running: boolean };
  enrich: ReactNode;
}) {
  const undated = useText("component-browser.undated", "Undated");
  const fieldsAnswered = useCopyFormatter("component-browser.fields-used", "{count} fields");
  const refreshing = useText("component-browser.source-refreshing", "Refreshing...");
  const refreshLabel = useText("component-browser.source-refresh", "Refresh Sourcing");

  return (
    <div className="flex flex-col gap-4">
      <Section
        title="Source Records"
        copyId="component-browser.sources-title"
        count={sources.length}
        action={
          <Button
            data-dev-id="component-browser.source-refresh"
            small
            disabled={refresh.running}
            onClick={refresh.run}
          >
            {refresh.running ? refreshing : refreshLabel}
          </Button>
        }
      >
        {sources.length === 0 ? (
          <EmptyState id="component-browser.sources-empty">
            No captured source records.
          </EmptyState>
        ) : (
          <ul className="flex flex-col gap-1">
            {sources.map((source) => (
              <li
                key={source.id}
                data-dev-id="component-browser.source-record-row"
                className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-card border border-line bg-raise px-3 py-1.5"
              >
                <span className="flex-none text-2xs font-semibold text-t1">{source.label}</span>
                <SourceStateBadge state={source.state} />
                <span className="flex-none text-2xs text-t3">
                  {source.fetchedAt ? formatTimestamp(source.fetchedAt).text : undated}
                </span>
                <span className="flex-none text-2xs text-t3">
                  {fieldsAnswered({ count: source.fieldCount })}
                </span>
                {source.payloadRef ? (
                  <span
                    className="min-w-0 flex-1 truncate font-mono text-2xs text-t3"
                    title={source.payloadRef}
                  >
                    {source.payloadRef}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </Section>

      {/* Enrichment is a LOOKUP, not a capture, so it sits beside the capture ledger rather than
          inside it. Reused whole: nothing about enrichment is re-decided here. */}
      <div data-dev-id="component-browser.enrich">{enrich}</div>
    </div>
  );
}

// ------------------------------------------------------------------ changes

/** A 40-char sha in its familiar short form. */
function shortSha(sha: string): string {
  return sha.slice(0, 7);
}

function formatValue(value: unknown, absent: string): string {
  if (value == null || value === "") return absent;
  if (Array.isArray(value)) return `${value.length}`;
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/**
 * The component's git timeline, read through the SAME hooks the detail sheet used
 * (`usePartHistory` + `usePartDiff` over `api.partDiff`). No new endpoint: the record's history
 * already exists, and a second way to ask for it would be a second answer to drift from.
 *
 * A commit that moved a symbol or a footprint offers the VISUAL diff, which is the only honest
 * way to read a geometry change: "symbol_content_hash changed" is a true field row and tells a
 * person nothing about what moved. The overlay is a modal opened from inside this sheet, which is
 * itself a modal - the nesting the shared modal stack was built to make safe.
 */
function ChangesPanel({ componentId, componentName }: { componentId: string; componentName: string }) {
  const history = usePartHistory(componentId);
  const [selected, setSelected] = useState<string | null>(null);
  const [visualDiff, setVisualDiff] = useState<string | null>(null);
  const commits = history.data?.commits ?? [];
  const index = selected ? commits.findIndex((commit) => commit.sha === selected) : -1;
  // The previous version of THIS component is the next-older entry in its own history; "" when
  // the selection is the commit that created it.
  const older = index >= 0 && index + 1 < commits.length ? commits[index + 1].sha : "";
  const diff = usePartDiff(componentId, older, index >= 0 ? commits[index].sha : null);
  const absent = useText("component-browser.no-value", "None");
  const visualDiffLabel = useText("component-browser.change-diff", "Visual Diff");
  // Only the kinds this commit actually moved get an overlay, and only while the commit whose
  // assets they describe is still the selected one.
  const assets = diff.data?.assets;
  const hasVisual = !!assets && (assets.symbol || assets.footprint);

  if (history.isLoading) {
    return <LoadingState id="component-browser.changes-loading">Loading this component's timeline...</LoadingState>;
  }
  if (history.isError) {
    return (
      <ErrorState
        id="component-browser.changes-failed"
        onRetry={() => history.refetch()}
      >
        This component's timeline could not be read.
      </ErrorState>
    );
  }
  if (commits.length === 0) {
    return (
      <EmptyState id="component-browser.changes-empty">
        No timeline so far. This component has not been committed.
      </EmptyState>
    );
  }

  return (
    <Section
      title="Changes"
      copyId="component-browser.changes-title"
      count={history.data?.count ?? commits.length}
    >
      <ul className="flex flex-col gap-1">
        {commits.map((commit) => {
          const active = selected === commit.sha;
          return (
            <li
              key={commit.sha}
              className="overflow-hidden rounded-card border border-line bg-raise"
            >
              <button
                type="button"
                data-dev-id="component-browser.change-entry"
                aria-expanded={active}
                onClick={() => setSelected(active ? null : commit.sha)}
                className="flex w-full items-start gap-3 px-3 py-1.5 text-left transition-colors hover:bg-raise2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc"
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-2xs text-t1">{commit.subject}</span>
                  <span className="block truncate text-2xs text-t3">
                    {`${commit.author} ${commit.iso_date}`}
                  </span>
                </span>
                <span className="tnum flex-none font-mono text-2xs text-t3">
                  {shortSha(commit.sha)}
                </span>
              </button>
              {active ? (
                <div className="border-t border-line px-3 py-2">
                  {diff.isLoading ? (
                    <LoadingState dense id="component-browser.changes-loading">
                      Loading this component's timeline...
                    </LoadingState>
                  ) : diff.isError || !diff.data ? (
                    <ErrorState
                      dense
                      id="component-browser.changes-diff-failed"
                      onRetry={() => diff.refetch()}
                    >
                      The changes in this commit could not be read.
                    </ErrorState>
                  ) : (
                    <div className="flex flex-col gap-2">
                      {hasVisual ? (
                        <Button
                          small
                          data-dev-id="component-browser.change-diff"
                          onClick={() => setVisualDiff(commit.sha)}
                          className="self-start"
                        >
                          {visualDiffLabel}
                        </Button>
                      ) : null}
                      {diff.data.fields.length === 0 ? (
                        <EmptyState dense id="component-browser.changes-no-fields">
                          No field changes in this commit.
                        </EmptyState>
                      ) : (
                        <ul className="flex flex-col gap-1">
                          {diff.data.fields.map((field) => (
                            <li key={field.key} className="flex items-baseline gap-2 text-2xs">
                              <Badge
                                size="sm"
                                tone={
                                  field.status === "added"
                                    ? "ok"
                                    : field.status === "removed"
                                      ? "err"
                                      : "neutral"
                                }
                              >
                                <ChangeStatusLabel status={field.status} />
                              </Badge>
                              {/* Named, with the storage key one hover away. A column of
                                  `manufacturer_part_number_raw` is not a change log anybody can
                                  read, and the raw key is still the thing to search for. */}
                              <span className="flex-none text-t3" title={field.key}>
                                {humanizeKey(field.key)}
                              </span>
                              <span className="min-w-0 flex-1 break-words text-t2">
                                {field.status === "added"
                                  ? formatValue(field.after, absent)
                                  : field.status === "removed"
                                    ? formatValue(field.before, absent)
                                    : `${formatValue(field.before, absent)} -> ${formatValue(field.after, absent)}`}
                              </span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  )}
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>

      {/* Nested inside the Sources & History sheet, which is itself a modal. The stack gives it
          the higher z-index and sole ownership of Escape, so closing it returns to the sheet
          rather than dismissing both. */}
      {visualDiff && assets ? (
        <DiffModal
          open
          partId={componentId}
          partName={componentName}
          a={older}
          b={visualDiff}
          assets={assets}
          onClose={() => setVisualDiff(null)}
        />
      ) : null}
    </Section>
  );
}

// ------------------------------------------------------------------ diagnostics

function DiagnosticsPanel({
  componentId,
  diagnostics,
  compatibility,
}: {
  componentId: string;
  diagnostics: DossierDiagnostics;
  compatibility: CompatibilityView;
}) {
  const [open, setOpen] = useState(false);
  const [rawOpen, setRawOpen] = useState(false);
  const { enabled: developerMode } = useDevMode();
  // The canonical record is fetched only when it is actually asked for: the raw shape is the one
  // thing on this sheet the projection deliberately does not carry.
  const detail = usePartDetailQuery(rawOpen ? componentId : null);
  const none = useText("component-browser.diagnostics-none", "None");
  const showLabel = useText("component-browser.diagnostics-show", "Show Diagnostics");
  const hideLabel = useText("component-browser.diagnostics-hide", "Hide Diagnostics");
  const showRaw = useText("component-browser.diagnostics-show-raw", "Show Canonical Record");
  const hideRaw = useText("component-browser.diagnostics-hide-raw", "Hide Canonical Record");
  const notice = useCompatibilityNotice(compatibility);

  return (
    <Section
      title="Technical Diagnostics"
      copyId="component-browser.diagnostics-title"
      count={diagnostics.unknownKeys.length}
      action={
        developerMode ? (
          <Button
            data-dev-id="component-browser.diagnostics-toggle"
            small
            aria-expanded={open}
            onClick={() => setOpen((current) => !current)}
          >
            {open ? hideLabel : showLabel}
          </Button>
        ) : undefined
      }
      note={
        <Text id="component-browser.diagnostics-note">
          What the storage for this component looks like underneath. It is here because it is
          sometimes the sole thing that answers, and behind developer mode because a schema number
          is not something a person can act on.
        </Text>
      }
    >
      {/* The one diagnostic that is ALSO a consequence for the person, said as that consequence:
          a count, a cause and a limitation, rather than a schema number and a list of keys. */}
      {/* Already resolved through the copy layer by `useCompatibilityNotice`, which owns its ids
          and its count. A second copy id here would register a default that moves with the data. */}
      {notice ? (
        <p className="text-2xs text-warn">
          {notice.text}
        </p>
      ) : null}
      {!developerMode ? (
        <p className="text-2xs text-t3">
          <Text id="component-browser.diagnostics-developer-only">
            Turn on developer mode to read the schema version, the derivation identifier, the
            content hashes and the storage fields this build does not understand.
          </Text>
        </p>
      ) : null}
      {developerMode && open ? (
        <div className="flex flex-col gap-2">
          <dl className="rounded-card border border-line bg-raise px-3 py-1">
            <DiagnosticRow
              label={<Text id="component-browser.schema-version">Record schema</Text>}
              value={String(diagnostics.recordSchemaVersion)}
            />
            <DiagnosticRow
              label={<Text id="component-browser.derived-by">Derivation</Text>}
              value={diagnostics.derivedBy || none}
            />
            <DiagnosticRow
              label={<Text id="component-browser.category-schema">Class schema</Text>}
              value={diagnostics.categorySchema || none}
            />
            <DiagnosticRow
              label={<Text id="component-browser.hash-symbol">Symbol hash</Text>}
              value={diagnostics.hashes.symbolContent || none}
            />
            <DiagnosticRow
              label={<Text id="component-browser.hash-footprint">Footprint hash</Text>}
              value={diagnostics.hashes.footprintContent || none}
            />
            <DiagnosticRow
              label={<Text id="component-browser.hash-model">Model hash</Text>}
              value={diagnostics.hashes.modelFile || none}
            />
            <DiagnosticRow
              label={
                <Text id="component-browser.unknown-keys">Fields this build does not read</Text>
              }
              value={diagnostics.unknownKeys.join(", ") || none}
            />
          </dl>
          <Button
            data-dev-id="component-browser.diagnostics-raw"
            small
            aria-expanded={rawOpen}
            onClick={() => setRawOpen((current) => !current)}
          >
            {rawOpen ? hideRaw : showRaw}
          </Button>
          {rawOpen ? (
            detail.isLoading ? (
              <p className="text-2xs text-t3">
                <Text id="component-browser.raw-loading">Loading the canonical record...</Text>
              </p>
            ) : detail.error || !detail.data ? (
              <p className="text-2xs text-err-text">
                <Text id="component-browser.raw-failed">
                  Could not load the canonical record.
                </Text>
              </p>
            ) : (
              <pre className="max-h-[320px] overflow-auto rounded-card border border-line bg-field p-3 font-mono text-2xs text-t2">
                {JSON.stringify(detail.data, null, 2)}
              </pre>
            )
          ) : null}
        </div>
      ) : null}
    </Section>
  );
}

/** What one commit did to one field, in words rather than in the diff's own token. */
function ChangeStatusLabel({ status }: { status: string }) {
  if (status === "added") return <Text id="component-browser.change-added">Added</Text>;
  if (status === "removed") return <Text id="component-browser.change-removed">Removed</Text>;
  return <Text id="component-browser.change-changed">Changed</Text>;
}

function DiagnosticRow({ label, value }: { label: ReactNode; value: string }) {
  return (
    <div className="flex items-baseline gap-3 border-b border-line/60 py-1 last:border-b-0">
      <dt className="flex-none text-2xs text-t2">{label}</dt>
      <dd className="min-w-0 flex-1 truncate text-right font-mono text-2xs text-t1" title={value}>
        {value}
      </dd>
    </div>
  );
}
