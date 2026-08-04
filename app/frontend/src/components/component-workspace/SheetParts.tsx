/**
 * The pieces every exhaustive sheet is built from.
 *
 * A modal is the only surface in this workspace allowed to scroll, so the three sheets are long
 * by design - and a long surface is exactly where three slightly different section headers, two
 * spellings of "nothing here", and four ways of attributing a value stop reading as one product.
 * These are shared so that never happens, and so a reader learns the vocabulary once: a section
 * says what it holds and how many, an attribution says which source answered and when, and an
 * empty region says what is absent rather than showing a spinner or a fabricated placeholder.
 */
import type { ReactNode } from "react";
import type { FactSource, SourceState } from "../../api/workspaceTypes";
import { Text, useText } from "../../lib/copy";
import { Badge } from "../primitives";
import { SOURCE_STATE_LABEL, sourceStateOf, sourceStateTone } from "./workspaceStatus";

/** One titled block of a sheet. `count` is the real projected total, never a rounded claim. */
export function SheetSection({
  devId,
  title,
  copyId,
  count,
  note,
  action,
  children,
}: {
  devId?: string;
  title: string;
  /**
   * The copy id for the heading, when the heading is COPY. A section whose title is DATA (a
   * projected group label, a distributor's name) passes none: routing server data through the
   * copy layer would let an override rename one library's group and silently rename it in every
   * other place that group appears.
   */
  copyId?: string;
  count?: number;
  /** A sentence qualifying what the section is, when the title alone would overclaim. */
  note?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section data-dev-id={devId} aria-label={title} className="flex flex-col gap-1.5">
      <header className="flex items-baseline gap-2">
        <h2 className="text-xs font-semibold text-t1">
          {copyId ? <Text id={copyId}>{title}</Text> : title}
        </h2>
        {count != null ? (
          <span className="flex-none text-2xs tabular-nums text-t3">{count}</span>
        ) : null}
        {action ? <span className="ml-auto flex-none">{action}</span> : null}
      </header>
      {note ? <p className="text-2xs leading-relaxed text-t3">{note}</p> : null}
      {children}
    </section>
  );
}

/** An honest empty block: it names what is absent. */
export function SheetEmpty({ id, children }: { id: string; children: string }) {
  return (
    <p className="rounded-card border border-line bg-raise px-3 py-2 text-2xs text-t3">
      <Text id={id}>{children}</Text>
    </p>
  );
}

/**
 * Where one value came from.
 *
 * A value with no recorded source is MANUAL, which is a real provenance and is said out loud -
 * an unattributed blank would read as an oversight rather than as "a person typed this".
 */
export function SourceNote({ source }: { source?: FactSource | null }) {
  const manual = useText("component-browser.manual", "Manual");
  if (!source) return <span className="flex-none text-2xs text-t3">{manual}</span>;
  return (
    <span className="flex-none text-2xs text-t3" title={source.fetchedAt ?? undefined}>
      {source.label || source.id}
    </span>
  );
}

/** One source's outcome, in the closed per-source vocabulary. */
export function SourceStateBadge({ state }: { state: SourceState | undefined }) {
  const resolved = sourceStateOf(state);
  return (
    <Badge size="sm" tone={sourceStateTone(resolved)}>
      {SOURCE_STATE_LABEL[resolved]}
    </Badge>
  );
}

/** The table shell the sheets share: bordered header row, tabular figures, horizontal scroll. */
export function SheetTable({
  devId,
  headings,
  children,
  label,
}: {
  devId?: string;
  headings: ReactNode[];
  children: ReactNode;
  label: string;
}) {
  return (
    // A wide table is the ONE thing allowed its own horizontal scroller: the alternative is a
    // sheet whose own body scrolls sideways, which moves every other section with it.
    <div data-dev-id={devId} className="overflow-x-auto rounded-card border border-line bg-raise">
      <table className="w-full text-left text-2xs" aria-label={label}>
        <thead className="text-t3">
          <tr className="border-b border-line">
            {headings.map((heading, index) => (
              <th key={index} scope="col" className="whitespace-nowrap px-3 py-1.5 font-medium">
                {heading}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="text-t1">{children}</tbody>
      </table>
    </div>
  );
}
