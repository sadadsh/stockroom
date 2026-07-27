/**
 * Bulk import: paste a list of part numbers (or a BOM CSV) and land them all.
 *
 * The surface exists because adding parts one at a time is the wall a real sourcing document
 * runs into - the owner's Component Register is 169 orderable line items, and every per-part
 * step multiplies by 169.
 *
 * PRIOR ART evaluated in this repo, and what was taken vs rejected:
 * - `AltiumDbLibSection`'s EmbedAllModelsButton is the app's existing long-running bulk action.
 *   ADOPTED wholesale: run as a job, state the count in the button, report a partial run as a
 *   problem rather than a success with a footnote.
 * - Its toast-only reporting was REJECTED here. One line can say "embedded 38 of 40"; it cannot
 *   say WHICH of 169 parts fell short and what each is missing, and that list is the whole
 *   value of the report.
 * - `useJob` + the SSE progress stream: ADOPTED unchanged, so this surface streams exactly like
 *   every other long job instead of inventing a second progress mechanism.
 * - A third-party table/grid library was REJECTED: five columns of plain text need no library,
 *   and the design contract explicitly wants a borderless text table rather than a grid widget's
 *   default chrome.
 *
 * Design contract (docs/design/design-rules.md): one focal point (the paste well and the action
 * that states its own count), no pills for data, no card-in-card, hierarchy from type and space.
 * Outcomes are TEXT in a semantic color, not badges - the smallest element that carries the
 * meaning, which is the rule.
 */
import { useMemo, useState } from "react";
import type { BulkImportItem, BulkImportResult } from "../api/types";
import { useBulkImport } from "../api/queries";
import { Button } from "./primitives";
import { Text } from "../lib/copy";

// Outcome tiers in the order a reader needs them: what landed, what was already there, then the
// two that want attention. `tone` maps to the semantic text colors, never a surface tint.
const TIERS: { status: string; label: string; tone: string }[] = [
  { status: "added", label: "Added", tone: "text-ok" },
  { status: "would-add", label: "Would Add", tone: "text-ok" },
  { status: "exists", label: "Already There", tone: "text-t2" },
  { status: "duplicate", label: "Duplicate", tone: "text-t3" },
  { status: "incomplete", label: "Needs More", tone: "text-warn" },
  { status: "error", label: "Failed", tone: "text-err" },
];

function looksLikeCsv(text: string): boolean {
  // A BOM CSV declares an MPN column in its header; a plain list never has one. Reading the
  // header is a fact about the text, so the user is never asked to classify their own paste.
  const first = text.split("\n", 1)[0]?.toLowerCase() ?? "";
  return (
    first.includes(",") &&
    /(^|,)\s*(mpn|manufacturer part number|part ?number|part#)\s*(,|$)/.test(first)
  );
}

function countEntries(text: string, csv: boolean): number {
  const lines = text
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l && !l.startsWith("#"));
  // Matches the backend exactly: a list de-duplicates, a CSV drops its header row. A button that
  // promises a count the run will not honour is the thing the Altium action was careful to avoid.
  return csv ? Math.max(0, lines.length - 1) : new Set(lines).size;
}

function Row({ item }: { item: BulkImportItem }) {
  const tier = TIERS.find((t) => t.status === item.status);
  const resolved = item.mpn && item.mpn !== item.query;
  return (
    <tr className="align-baseline hover:bg-field">
      <td className="py-1.5 pr-3 font-mono text-xs text-t1">{item.query}</td>
      <td className="py-1.5 pr-3 font-mono text-xs text-t2">
        {resolved ? item.mpn : <span className="text-t3">&mdash;</span>}
      </td>
      <td className="py-1.5 pr-3 text-xs text-t2">
        {item.display_name || <span className="text-t3">&mdash;</span>}
      </td>
      <td className="whitespace-nowrap py-1.5 pr-3 text-xs">
        <span className={tier?.tone ?? "text-t2"}>{tier?.label ?? item.status}</span>
      </td>
      <td className="py-1.5 text-xs text-t3">
        {item.error || (item.missing.length ? `Missing ${item.missing.join(", ")}` : "")}
      </td>
    </tr>
  );
}

function Summary({ result }: { result: BulkImportResult }) {
  const tiers = TIERS.filter((t) => (result.counts[t.status] ?? 0) > 0);
  return (
    <div className="flex flex-wrap items-baseline gap-x-7 gap-y-2">
      {tiers.map((t) => (
        <div key={t.status} className="min-w-0">
          <div className={`font-mono text-xl font-semibold tnum ${t.tone}`}>
            {result.counts[t.status]}
          </div>
          <div className="mt-0.5 text-2xs text-t2">{t.label}</div>
        </div>
      ))}
    </div>
  );
}

export function BulkImportSection() {
  const [text, setText] = useState("");
  const [showAll, setShowAll] = useState(false);
  const job = useBulkImport();
  const csv = useMemo(() => looksLikeCsv(text), [text]);
  const count = useMemo(() => countEntries(text, csv), [text, csv]);
  const busy = job.status === "running";
  const result = job.result;
  // Only the rows that need a decision are shown by default. A 169-row table where 160 rows say
  // "Added" buries the 9 that do not, and those 9 are what the reader came for.
  const attention = useMemo(
    () => (result?.items ?? []).filter((i) => i.status === "incomplete" || i.status === "error"),
    [result],
  );
  const rows = showAll ? (result?.items ?? []) : attention;

  return (
    // NOT a Panel. Inside the Add-A-Part dialog a bordered surface is a card in a card (design
    // rule 3), and in light theme its hairline vanished anyway, leaving a floating heading over a
    // grey box. A top hairline is the same separator the step strip above already uses, so this
    // lane reads as a peer of the single-part lane instead of a louder box nested in it.
    <div data-dev-id="ingest.bulk" className="mt-1 border-t border-line pt-4">
      <div className="flex items-baseline justify-between gap-3">
        <div className="text-sm font-semibold text-t1">
          <Text id="bulk.title">Import A List</Text>
        </div>
        {count > 0 ? (
          <span className="text-2xs text-t3">
            <span className="font-mono tnum">{count}</span>
            {csv ? " rows" : " part numbers"}
          </span>
        ) : null}
      </div>
      <p className="mt-0.5 text-xs text-t3">
        <Text id="bulk.hint">
          One part number per line, or a BOM CSV. A distributor stock number is resolved to the manufacturer part first.
        </Text>
      </p>
      <textarea
        data-dev-id="ingest.bulk-input"
        value={text}
        onChange={(e) => setText(e.target.value)}
        disabled={busy}
        spellCheck={false}
        rows={4}
        placeholder={"595-TPD6E05U06RVZR\n603-RC0402FR-07100RL\nSN74LVC1G08DBVR"}
        className="mt-3 w-full resize-y rounded-control bg-field px-3 py-2.5 font-mono text-xs text-t1 placeholder:text-t3 focus:outline-none focus:ring-1 focus:ring-acc disabled:opacity-60"
      />

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button
          data-dev-id="ingest.bulk-import"
          variant="accent"
          disabled={busy || count === 0}
          onClick={() => job.start({ text, format: csv ? "csv" : "list" })}
        >
          {count > 0 ? `Import ${count} ${count === 1 ? "Part" : "Parts"}` : "Import"}
        </Button>
        {/* Secondary, and it must LOOK it: as a filled `soft` button it out-shouted the disabled
            primary next to it, so the safe-but-lesser action read as the main one. */}
        <Button
          data-dev-id="ingest.bulk-preview"
          disabled={busy || count === 0}
          onClick={() => job.start({ text, format: csv ? "csv" : "list", dryRun: true })}
        >
          <Text id="bulk.preview">Preview Without Writing</Text>
        </Button>
        {busy ? (
          <span
            className="min-w-0 flex-1 truncate text-xs text-t2"
            data-dev-id="ingest.bulk-progress"
          >
            {job.progress?.message ?? "Starting"}
          </span>
        ) : null}
      </div>

      {busy && job.progress?.pct != null ? (
        <div className="mt-2.5 h-0.5 w-full overflow-hidden rounded-control bg-field">
          <div
            className="h-full bg-acc transition-[width] duration-200"
            style={{ width: `${Math.round((job.progress.pct ?? 0) * 100)}%` }}
          />
        </div>
      ) : null}

      {job.status === "error" ? (
        <p className="mt-3 text-xs text-err" data-dev-id="ingest.bulk-error">
          {job.error}
        </p>
      ) : null}

      {result ? (
        <div className="mt-4" data-dev-id="ingest.bulk-result">
          <Summary result={result} />
          {attention.length === 0 && !showAll ? (
            <p className="mt-3 text-xs text-t2">
              <Text id="bulk.all-clean">
                Every part in the list was handled. Nothing needs attention.
              </Text>
            </p>
          ) : null}
          {rows.length > 0 ? (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full min-w-[34rem] text-left">
                <thead>
                  <tr className="border-b border-line text-2xs text-t3">
                    <th className="pb-1.5 pr-3 font-normal">You Pasted</th>
                    <th className="pb-1.5 pr-3 font-normal">Resolved To</th>
                    <th className="pb-1.5 pr-3 font-normal">Part</th>
                    <th className="pb-1.5 pr-3 font-normal">Outcome</th>
                    <th className="pb-1.5 font-normal">Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((item, i) => (
                    <Row key={`${item.query}-${i}`} item={item} />
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          {result.items.length > attention.length ? (
            <button
              type="button"
              data-dev-id="ingest.bulk-toggle"
              className="mt-2.5 text-2xs text-t2 underline-offset-2 hover:text-t1 hover:underline"
              onClick={() => setShowAll((v) => !v)}
            >
              {showAll
                ? `Show Only What Needs Attention (${attention.length})`
                : `Show All ${result.items.length} Rows`}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
