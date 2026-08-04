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
  ComponentSourcesView,
  FactAlternate,
  SourceRecordView,
} from "../../api/workspaceTypes";
import { Text, useText } from "../../lib/copy";
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
import { ExternalIcon } from "../icons";
import { SourceNote, SourceStateBadge } from "./SheetParts";

export type SourcesSheetTab = "fields" | "records" | "changes" | "diagnostics";

const SOURCES_TABS: readonly TabItem<SourcesSheetTab>[] = [
  { id: "fields", label: "Field Sources", copyId: "component-browser.sources-tab-fields" },
  { id: "records", label: "Source Records", copyId: "component-browser.sources-tab-records" },
  { id: "changes", label: "Changes", copyId: "component-browser.sources-tab-changes" },
  {
    id: "diagnostics",
    label: "Diagnostics",
    copyId: "component-browser.sources-tab-diagnostics",
  },
];

/**
 * The fields an alternate can be put in force on.
 *
 * `editField` writes a canonical RECORD attribute, so this is exactly the set of attributes it can
 * reach. A specification key is not one of them - it lives in `specs`, is written through a
 * different seam that carries per-key provenance, and offering an Apply here that the backend
 * would reject with "unknown field" is worse than offering none.
 */
export const APPLICABLE_FIELDS: ReadonlySet<string> = new Set([
  "display_name",
  "mpn",
  "manufacturer",
  "description",
  "value",
]);

/** Whether this alternate can be applied as-is: a known field, and a plain scalar value. */
export function canApplyAlternate(fieldId: string, alternate: FactAlternate): boolean {
  if (!APPLICABLE_FIELDS.has(fieldId)) return false;
  const raw = alternate.rawValue;
  return typeof raw === "string" || typeof raw === "number" || typeof raw === "boolean";
}

export function SourcesSheet({
  componentId,
  componentName,
  sources,
  onApplyAlternate,
  applying,
  refresh,
  enrich,
}: {
  componentId: string;
  /** The display name the nested visual diff titles itself with. */
  componentName: string;
  sources: ComponentSourcesView;
  onApplyAlternate: (fieldId: string, value: unknown) => void;
  applying: boolean;
  /** The sourcing refresh action, owned by the workspace so the job lives above this sheet. */
  refresh: { run: () => void; running: boolean };
  /** The enrichment surface, passed in so this sheet never re-implements enrichment. */
  enrich: ReactNode;
}) {
  const [tab, setTab] = useState<SourcesSheetTab>("fields");
  const tabsLabel = useText("component-browser.sources-tabs", "Sources and history");

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
            sources={sources}
            onApplyAlternate={onApplyAlternate}
            applying={applying}
          />
        ) : tab === "records" ? (
          <SourceRecordsPanel records={sources.records} refresh={refresh} enrich={enrich} />
        ) : tab === "changes" ? (
          <ChangesPanel componentId={componentId} componentName={componentName} />
        ) : (
          <DiagnosticsPanel componentId={componentId} sources={sources} />
        )}
      </TabPanel>
    </div>
  );
}

// ------------------------------------------------------------------ field sources

function FieldSourcesPanel({
  sources,
  onApplyAlternate,
  applying,
}: {
  sources: ComponentSourcesView;
  onApplyAlternate: (fieldId: string, value: unknown) => void;
  applying: boolean;
}) {
  const emptyValue = useText("component-browser.no-value", "None");
  const tableLabel = useText("component-browser.field-sources-title", "Attributed Fields");
  const applyLabel = useText("component-browser.field-apply", "Apply");

  if (sources.fields.length === 0) {
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
      count={sources.fields.length}
      note={
        <Text id="component-browser.field-sources-note">
          The value in force for each field, the source that supplied it, and every other answer
          that was offered. Applying an alternate records which source it came from.
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
        {sources.fields.map((field) => (
          <tr
            key={field.id}
            data-dev-id="component-browser.field-source-row"
            className="border-b border-line/60 align-top last:border-b-0"
          >
            <td className="px-3 py-1.5 text-t2">{field.label}</td>
            <td className="px-3 py-1.5">
              <span className="tnum font-mono text-t1">
                {field.formattedValue || emptyValue}
              </span>
              {field.alternates.length > 0 ? (
                <ul className="mt-1 flex flex-col gap-1">
                  {field.alternates.map((alternate) => (
                    <li
                      key={`${alternate.sourceId}:${alternate.formattedValue}`}
                      className="flex items-baseline gap-2 text-2xs text-t3"
                    >
                      <span className="tnum font-mono">
                        {alternate.formattedValue || emptyValue}
                      </span>
                      <span>{alternate.sourceLabel || alternate.sourceId}</span>
                      {canApplyAlternate(field.id, alternate) ? (
                        <button
                          type="button"
                          data-dev-id="component-browser.field-source-apply"
                          disabled={applying}
                          aria-label={`${applyLabel} ${alternate.formattedValue} ${field.label}`}
                          onClick={() => onApplyAlternate(field.id, alternate.rawValue)}
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
              <SourceNote source={field.source} />
              {field.source?.fetchedAt ? (
                <span className="mt-0.5 block text-2xs text-t3">{field.source.fetchedAt}</span>
              ) : null}
            </td>
            <td className="px-3 py-1.5">
              <Badge size="sm" tone={field.state === "conflict" ? "warn" : "neutral"}>
                {field.state}
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
  records,
  refresh,
  enrich,
}: {
  records: SourceRecordView[];
  refresh: { run: () => void; running: boolean };
  enrich: ReactNode;
}) {
  const undated = useText("component-browser.undated", "Undated");
  const refreshing = useText("component-browser.source-refreshing", "Refreshing...");
  const refreshLabel = useText("component-browser.source-refresh", "Refresh Sourcing");

  return (
    <div className="flex flex-col gap-4">
      <Section
        title="Source Records"
        copyId="component-browser.sources-title"
        count={records.length}
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
        {records.length === 0 ? (
          <EmptyState id="component-browser.sources-empty">
            No captured source records.
          </EmptyState>
        ) : (
          <ul className="flex flex-col gap-1">
            {records.map((record) => (
              <li
                key={record.id}
                data-dev-id="component-browser.source-record-row"
                className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-card border border-line bg-raise px-3 py-1.5"
              >
                <span className="flex-none text-2xs font-semibold text-t1">{record.label}</span>
                <SourceStateBadge state={record.state} />
                <span className="flex-none text-2xs text-t3">{record.fetchedAt || undated}</span>
                {record.file ? (
                  <span className="min-w-0 flex-1 truncate font-mono text-2xs text-t3" title={record.file}>
                    {record.file}
                  </span>
                ) : null}
                {record.digest ? (
                  <span className="flex-none font-mono text-2xs text-t3" title={record.digest}>
                    {record.digest.slice(0, 12)}
                  </span>
                ) : null}
                {record.url ? (
                  <a
                    href={record.url}
                    target="_blank"
                    rel="noreferrer"
                    aria-label={record.label}
                    className="flex-none rounded-control px-1 text-t2 transition-colors hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc"
                  >
                    <ExternalIcon />
                  </a>
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
    return <LoadingState id="component-browser.changes-loading">Loading this component's history...</LoadingState>;
  }
  if (history.isError) {
    return (
      <ErrorState
        id="component-browser.changes-failed"
        onRetry={() => history.refetch()}
      >
        This component's history could not be read.
      </ErrorState>
    );
  }
  if (commits.length === 0) {
    return (
      <EmptyState id="component-browser.changes-empty">
        No history yet. This component has not been committed.
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
                      Loading this component's history...
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
                                {field.status}
                              </Badge>
                              <span className="flex-none font-mono text-t3">{field.key}</span>
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
  sources,
}: {
  componentId: string;
  sources: ComponentSourcesView;
}) {
  const [open, setOpen] = useState(false);
  const [rawOpen, setRawOpen] = useState(false);
  // The canonical record is fetched only when it is actually asked for: the raw shape is the one
  // thing on this sheet the projection deliberately does not carry.
  const detail = usePartDetailQuery(rawOpen ? componentId : null);
  const { diagnostics } = sources;
  const unknown = useText("component-browser.unknown", "unknown");
  const showLabel = useText("component-browser.diagnostics-show", "Show Diagnostics");
  const hideLabel = useText("component-browser.diagnostics-hide", "Hide Diagnostics");
  const showRaw = useText("component-browser.diagnostics-show-raw", "Show Canonical Record");
  const hideRaw = useText("component-browser.diagnostics-hide-raw", "Hide Canonical Record");

  return (
    <Section
      title="Diagnostics"
      copyId="component-browser.diagnostics-title"
      count={diagnostics.unknownKeys.length}
      action={
        <Button
          data-dev-id="component-browser.diagnostics-toggle"
          small
          aria-expanded={open}
          onClick={() => setOpen((current) => !current)}
        >
          {open ? hideLabel : showLabel}
        </Button>
      }
      note={
        <Text id="component-browser.diagnostics-note">
          Technical truth about how this record was produced. Collapsed because nobody opens a
          component to read it, and reachable because sometimes it is the only thing that answers.
        </Text>
      }
    >
      {open ? (
        <div className="flex flex-col gap-2">
          <dl className="rounded-card border border-line bg-raise px-3 py-1">
            <DiagnosticRow
              label={<Text id="component-browser.schema-version">Schema version</Text>}
              value={String(diagnostics.schemaVersion)}
            />
            <DiagnosticRow
              label={<Text id="component-browser.derived-by">Derived by</Text>}
              value={diagnostics.derivedBy || unknown}
            />
            <DiagnosticRow
              label={<Text id="component-browser.derived-at">Derived at</Text>}
              value={diagnostics.derivedAt || unknown}
            />
            <DiagnosticRow
              label={<Text id="component-browser.hash-symbol">Symbol hash</Text>}
              value={diagnostics.hashes.symbolContent || unknown}
            />
            <DiagnosticRow
              label={<Text id="component-browser.hash-footprint">Footprint hash</Text>}
              value={diagnostics.hashes.footprintContent || unknown}
            />
            <DiagnosticRow
              label={<Text id="component-browser.hash-model">Model hash</Text>}
              value={diagnostics.hashes.modelFile || unknown}
            />
            <DiagnosticRow
              label={<Text id="component-browser.unknown-keys">keys written by a newer build</Text>}
              value={diagnostics.unknownKeys.join(", ") || unknown}
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
              <p className="text-2xs text-err">
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
