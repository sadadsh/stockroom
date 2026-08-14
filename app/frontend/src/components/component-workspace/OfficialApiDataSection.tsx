import { useMemo, useState } from "react";

import type {
  OfficialApiDataRow,
  OfficialApiDataView,
  OfficialApiProviderData,
} from "../../api/dossierTypes";
import { Text, useText } from "../../lib/copy";
import { formatCount, formatTimestamp } from "../../lib/formatValue";
import { StatusText } from "../primitives";
import { SourcingSection } from "./SourcingParts";

function matchingRows(provider: OfficialApiProviderData, query: string): OfficialApiDataRow[] {
  const needle = query.trim().toLocaleLowerCase();
  if (!needle) return provider.rows;
  return provider.rows.filter((row) =>
    `${row.path}\n${row.displayValue}\n${row.kind}`.toLocaleLowerCase().includes(needle),
  );
}

function byEndpoint(rows: readonly OfficialApiDataRow[]): Array<[string, OfficialApiDataRow[]]> {
  const groups = new Map<string, OfficialApiDataRow[]>();
  for (const row of rows) {
    const group = groups.get(row.endpoint) ?? [];
    group.push(row);
    groups.set(row.endpoint, group);
  }
  return Array.from(groups);
}

function ProviderState({ state }: { state: string }) {
  if (!state) return null;
  const tone = state === "success" ? "ok" : state === "failed" ? "err" : "warn";
  return <StatusText tone={tone}>{state.replaceAll("_", " ")}</StatusText>;
}

const ROW_PAGE_SIZE = 100;

function EndpointDisclosure({
  endpoint,
  rows,
  forceOpen,
}: {
  endpoint: string;
  rows: readonly OfficialApiDataRow[];
  forceOpen: boolean;
}) {
  const [opened, setOpened] = useState(false);
  const [page, setPage] = useState(0);
  const expanded = forceOpen || opened;
  const pageCount = Math.max(1, Math.ceil(rows.length / ROW_PAGE_SIZE));
  const visiblePage = Math.min(page, pageCount - 1);
  const visibleRows = rows.slice(
    visiblePage * ROW_PAGE_SIZE,
    (visiblePage + 1) * ROW_PAGE_SIZE,
  );
  return (
    <details
      open={expanded}
      onToggle={(event) => {
        if (!forceOpen) setOpened(event.currentTarget.open);
      }}
      data-dev-id="component-browser.official-api-endpoint"
      className="border-b border-line/50 last:border-b-0"
    >
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-1 marker:hidden">
        <code className="ui-row-secondary min-w-0 flex-1 break-all">{endpoint}</code>
        <span className="ui-component-metadata ui-numeric">{formatCount(rows.length)}</span>
      </summary>
      {expanded ? (
        <div className="border-t border-line/40">
          {visibleRows.map((row) => (
            <div
              key={row.path || "$"}
              data-dev-id="component-browser.official-api-row"
              data-value-kind={row.kind}
              className="grid grid-cols-[minmax(9rem,0.9fr)_minmax(0,1.1fr)] gap-2 border-b border-line/40 px-3 py-1 last:border-b-0"
            >
              <code className="ui-component-metadata break-all" title={row.path}>
                {row.path || "$"}
              </code>
              <span className="ui-property-value break-all">{row.displayValue}</span>
            </div>
          ))}
          {pageCount > 1 ? (
            <div className="flex items-center justify-end gap-2 px-3 py-1">
              <button
                type="button"
                disabled={visiblePage === 0}
                onClick={() => setPage((current) => Math.max(0, current - 1))}
                className="ui-component-metadata disabled:opacity-40"
              >
                Previous
              </button>
              <span className="ui-component-metadata ui-numeric">
                {visiblePage + 1} / {pageCount}
              </span>
              <button
                type="button"
                disabled={visiblePage + 1 === pageCount}
                onClick={() => setPage((current) => Math.min(pageCount - 1, current + 1))}
                className="ui-component-metadata disabled:opacity-40"
              >
                Next
              </button>
            </div>
          ) : null}
        </div>
      ) : null}
    </details>
  );
}

function ProviderDisclosure({
  provider,
  rows,
  forceOpen,
}: {
  provider: OfficialApiProviderData;
  rows: readonly OfficialApiDataRow[];
  forceOpen: boolean;
}) {
  const [opened, setOpened] = useState(false);
  const expanded = forceOpen || opened;
  const stamp = provider.fetchedAt ? formatTimestamp(provider.fetchedAt) : null;
  return (
    <details
      open={expanded}
      onToggle={(event) => {
        if (!forceOpen) setOpened(event.currentTarget.open);
      }}
      data-dev-id="component-browser.official-api-provider"
      data-provider={provider.provider}
      className="border-b border-line/70 last:border-b-0"
    >
      <summary className="flex cursor-pointer list-none items-center gap-2 px-2 py-1.5 marker:hidden">
        <span className="ui-row-primary min-w-0 flex-1">{provider.providerLabel}</span>
        <ProviderState state={provider.state} />
        <span className="ui-component-metadata ui-numeric">{formatCount(rows.length)}</span>
      </summary>
      {expanded ? (
        <div className="border-t border-line/60 bg-panel-2/30">
          {stamp || provider.payloadRef ? (
            <div className="ui-component-metadata break-all border-b border-line/50 px-2 py-1">
              {[stamp?.text, provider.payloadRef].filter(Boolean).join(" · ")}
            </div>
          ) : null}
          {(forceOpen ? [["Search Results", [...rows]] as [string, OfficialApiDataRow[]]] : byEndpoint(rows)).map(([endpoint, endpointRows]) => (
            <EndpointDisclosure
              key={endpoint}
              endpoint={endpoint}
              rows={endpointRows}
              forceOpen={forceOpen}
            />
          ))}
        </div>
      ) : null}
    </details>
  );
}

/**
 * Every exact leaf from every retained official provider response.
 *
 * The actionable projections remain above this section; this is the lossless answer to “what did
 * the APIs actually hand us?”. Paths preserve structure, explicit nulls and empty containers are
 * shown as returned, and search narrows rows without deleting or reinterpreting provider data.
 */
export function OfficialApiDataSection({ data }: { data: OfficialApiDataView }) {
  const [query, setQuery] = useState("");
  const searchLabel = useText("component-browser.official-api-search", "Search official API data");
  const providers = useMemo(
    () =>
      data.providers
        .map((provider) => ({ provider, rows: matchingRows(provider, query) }))
        .filter(({ rows }) => rows.length > 0),
    [data.providers, query],
  );

  return (
    <SourcingSection
      devId="component-browser.official-api-data"
      title={<Text id="component-browser.official-api-data-title">Official API Data</Text>}
      action={
        data.fieldCount > 0 ? (
          <span className="ui-component-metadata ui-numeric">{formatCount(data.fieldCount)}</span>
        ) : undefined
      }
    >
      <div className="border-b border-line px-2 py-1">
        <input
          type="search"
          data-dev-id="component-browser.official-api-search"
          aria-label={searchLabel}
          placeholder={`${searchLabel}…`}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          className={
            "ui-property-value h-[22px] w-full rounded-control border border-line bg-field px-1.5 " +
            "focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-1 " +
            "focus-visible:outline-focus"
          }
        />
      </div>
      {providers.map(({ provider, rows }) => (
        <ProviderDisclosure
          key={provider.provider}
          provider={provider}
          rows={rows}
          forceOpen={Boolean(query)}
        />
      ))}
      {query && providers.length === 0 ? (
        <p className="ui-component-metadata px-2 py-2">
          <Text id="component-browser.official-api-no-match">No official API field matches.</Text>
        </p>
      ) : null}
    </SourcingSection>
  );
}
