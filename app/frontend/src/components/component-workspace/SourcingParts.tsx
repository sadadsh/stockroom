/**
 * The shapes every section of the Sourcing and Resources column is built from.
 *
 * There are three of them and there is deliberately no fourth. A column that invents a heading
 * band per section is how six sections end up with six different densities, and a column whose
 * property rows are assembled per call site is how the label width stops lining up two sections
 * down. Both were true of this column before it was one order of six named sections.
 *
 * None of these is a card. A section is a heading band and the rows under it, separated by 1px
 * rules and a small surface change - the whole column is one contiguous surface, not a stack of
 * floating panels with padding between them.
 */
import type { ReactNode } from "react";
import { Icon } from "../Icon";

/**
 * A quiet heading row with at most one action. Primary content can keep its rows open; secondary
 * evidence uses the same heading as a native disclosure summary. A rule and label are enough—filled
 * bands repeated across every category were the visual noise this surface is removing.
 */
export function SourcingSection({
  devId,
  title,
  action,
  collapsed = false,
  children,
}: {
  devId: string;
  title: ReactNode;
  /** The section's own toolbar. A refresh or a "view everything" control, never a status. */
  action?: ReactNode;
  /** Keep secondary evidence to one quiet row until somebody asks for it. */
  collapsed?: boolean;
  children: ReactNode;
}) {
  const heading = (
    <>
      <h3 className="ui-section-title min-w-0 flex-1 truncate">{title}</h3>
      {action ? <span className="ml-auto flex-none">{action}</span> : null}
    </>
  );
  if (collapsed) {
    return (
      <section data-dev-id={devId} className="border-b border-line last:border-b-0">
        <details className="group">
          <summary className="flex min-h-[28px] cursor-pointer list-none items-center gap-2 px-2 py-1 hover:bg-[var(--c-hover)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-inset focus-visible:outline-focus">
            {heading}
            <Icon
              id="detail.chevron-right"
              className="h-3 w-3 flex-none text-t3 transition-transform group-open:rotate-90"
            />
          </summary>
          <div className="border-t border-line">{children}</div>
        </details>
      </section>
    );
  }
  return (
    <section data-dev-id={devId} className="border-b border-line last:border-b-0">
      <header className="flex min-h-[21px] items-center gap-2 border-b border-line px-2 py-0.5">
        {heading}
      </header>
      <div>{children}</div>
    </section>
  );
}

/**
 * One question inside a section.
 *
 * Provenance and history is six questions, and six sections in the column would have put "Manual
 * Overrides" at the same weight as "Distributor Offers". A sub-heading is a property label, not a
 * second section title, so the section it sits in stays the thing being read.
 */
export function SourcingSubSection({
  devId,
  title,
  count,
  children,
}: {
  devId: string;
  title: ReactNode;
  /** How many rows are under it. Muted and un-badged: a number beside a heading, not a pill. */
  count?: number;
  children: ReactNode;
}) {
  return (
    <section data-dev-id={devId} className="border-b border-line/60 last:border-b-0">
      <header className="flex min-h-[20px] items-baseline gap-2 px-2 pt-1">
        <h4 className="ui-property-label min-w-0 truncate">{title}</h4>
        {count === undefined ? null : (
          <span className="ui-component-metadata flex-none">{count}</span>
        )}
      </header>
      <div>{children}</div>
    </section>
  );
}

/** Compact secondary facts without removing them from the column's accessible reading order. */
export function SourcingDisclosure({
  devId,
  label,
  icon = "status.info",
  children,
}: {
  devId: string;
  label: ReactNode;
  icon?: string | null;
  children: ReactNode;
}) {
  return (
    <details data-dev-id={devId} className="group border-t border-line/60">
      <summary className="flex min-h-[24px] cursor-pointer list-none items-center gap-1.5 px-2 py-1 text-xs font-medium text-t2 hover:bg-[var(--c-hover)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-inset focus-visible:outline-focus">
        {icon ? <Icon id={icon} className="h-3.5 w-3.5 flex-none text-t3" /> : null}
        <span>{label}</span>
        <Icon
          id="detail.chevron-right"
          className="ml-auto h-3 w-3 flex-none text-t3 transition-transform group-open:rotate-90"
        />
      </summary>
      <div>{children}</div>
    </details>
  );
}

/**
 * One label and its value.
 *
 * The label column is a fixed width so every value in the column starts at the same left edge,
 * whichever section it is in. There is no colon after the label: the alignment already says which
 * of the two is the name.
 */
export function PropertyRow({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="flex min-h-[24px] items-baseline gap-2 px-2 py-1.5 hover:bg-[var(--c-hover)]">
      <span className="ui-property-label w-[7.5rem] flex-none">{label}</span>
      <span className="min-w-0 flex-1">{children}</span>
    </div>
  );
}
