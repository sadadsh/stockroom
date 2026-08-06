/**
 * The product's STATE vocabulary, in one place.
 *
 * Before this, every route answered "nothing here yet", "still loading", and "that failed" in its
 * own words and its own markup: the parts picker wrote a centred div and a bare Try Again button,
 * the workspace regions wrote a dim paragraph, the exhaustive sheets wrote a bordered paragraph,
 * and three of them said "Loading X..." with three different type sizes. Same three states, five
 * treatments, and none of the picker's strings went through the copy layer at all.
 *
 * These are those states as ONE object each, so a person learns the difference between them once:
 *
 *   Loading      - we asked and have not been answered yet. Never used for "there is nothing".
 *   Empty        - we were answered, and the answer is that there is nothing. Names what is absent.
 *   Warning      - it works, and something about it is worth knowing before you rely on it.
 *   Unavailable  - the capability is not offered here (not configured, not required, not carried).
 *                  Distinct from Empty on purpose: "no credentials" is not "no results".
 *   Error        - it failed. Says what failed in a person's words, and offers the retry when the
 *                  action is genuinely repeatable.
 *
 * A raw exception is never one of these. `ErrorState` takes a written message; a caller holding an
 * `Error` is expected to translate it, because a stack trace in the middle of a panel is not a
 * state, it is a leak.
 *
 * Every string arrives through the copy layer. The primitives take a copy `id` and a plain-string
 * default rather than a ReactNode, which is what makes the default the diff baseline the Design
 * panel edits against.
 */
import type { HTMLAttributes, ReactNode } from "react";
import { Text, useText } from "../lib/copy";
import { Button, Dot, SectionHeading, type BadgeTone } from "./primitives";

function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

// --------------------------------------------------------------------------- route header

/**
 * The one docked chrome header: the thin band at the top of a route column or a docked panel.
 *
 * 26px is not decoration. The rail wordmark, the Components list title and the Projects title
 * strip all sit on ONE horizontal line across the window, and a 4px difference between them reads
 * as a mis-registration rather than as variety (measured on the owner's window, 2026-07-26).
 * `devIds.parity.test.ts` gates every file in that family for exactly that reason, so the height
 * stays a literal.
 *
 * It was 34px. The desktop density this product is being held to puts a panel title strip at
 * 24-26px, and the strip is a LABEL: at 34px it spent a third of its height on air while the rows
 * beneath it were being packed to 24. Changing the picker alone would have mis-registered it
 * against the rail, so the whole shared line moved together and both gates moved with it.
 *
 * `right` is a trailing COUNT and deliberately sits next to the title rather than flush to the
 * far edge: every call site passes a number, and flushing separated the number from the noun it
 * counts by ~290px on a 320px panel. `actions` is the slot for something that really is a control
 * and really does want the edge.
 */
export function RouteHeader({
  right,
  actions,
  className,
  children,
  ...rest
}: { right?: ReactNode; actions?: ReactNode } & HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cx(
        "flex h-[26px] flex-none items-center gap-2 border-b border-line bg-band px-2.5",
        className,
      )}
      {...rest}
    >
      {/* min-w-0 so `truncate` has something to shrink against now that the span sizes to its
          content instead of being stretched by a justify-between. */}
      <span className="min-w-0 truncate text-xs font-semibold text-t2">{children}</span>
      {right != null ? (
        <span className="flex-none text-2xs tabular-nums text-t3">{right}</span>
      ) : null}
      {actions != null ? <span className="ml-auto flex-none">{actions}</span> : null}
    </div>
  );
}

// --------------------------------------------------------------------------- section header

/**
 * One titled block inside a surface: what it holds, how many, and at most one action.
 *
 * Lifted out of `component-workspace/SheetParts.tsx`, where it was the sheets' private
 * `SheetSection`. Nothing about it was ever workspace-specific, and keeping it there is what let
 * the settings groups and the project workbenches each grow a slightly different heading row.
 */
export function SectionHeader({
  title,
  copyId,
  count,
  action,
  className,
}: {
  title: string;
  /**
   * The copy id, when the heading is COPY. A heading that is DATA (a projected group label, a
   * distributor's name) passes none: routing server data through the copy layer would let an
   * override rename one library's group and silently rename that group everywhere it appears.
   */
  copyId?: string;
  count?: number;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <header className={cx("flex items-baseline gap-2", className)}>
      {/* The typography is `SectionHeading`'s decision, not a second one taken here. */}
      <SectionHeading dense as="h2">
        {copyId ? <Text id={copyId}>{title}</Text> : title}
      </SectionHeading>
      {count != null ? (
        <span className="flex-none text-2xs tabular-nums text-t3">{count}</span>
      ) : null}
      {action ? <span className="ml-auto flex-none">{action}</span> : null}
    </header>
  );
}

/** A section: its header, an optional qualifying note, and its body. */
export function Section({
  devId,
  title,
  copyId,
  count,
  note,
  action,
  className,
  children,
}: {
  devId?: string;
  title: string;
  copyId?: string;
  count?: number;
  /** A sentence qualifying what the section is, when the title alone would overclaim. */
  note?: ReactNode;
  action?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section
      data-dev-id={devId}
      aria-label={title}
      className={cx("flex flex-col gap-1.5", className)}
    >
      <SectionHeader title={title} copyId={copyId} count={count} action={action} />
      {note ? <p className="text-2xs leading-relaxed text-t3">{note}</p> : null}
      {children}
    </section>
  );
}

// --------------------------------------------------------------------------- product states

/** The closed set of product states. `data-product-state` carries it into the DOM for tests. */
export type ProductState = "loading" | "empty" | "warning" | "unavailable" | "error";

/**
 * Shared props for the five states.
 *
 * `children` is a plain string, not a node: it is the copy layer's default AND its diff baseline,
 * and an element cannot be either.
 */
export interface ProductStateProps {
  /** The copy id for the message. Every user-visible string here is overridable. */
  id: string;
  /** The default message. Sentence case prose. */
  children: string;
  /**
   * The compact form used INSIDE an already-bounded region (a workspace region, a table cell):
   * no border and no fill, because a box inside a box is the card soup this pass exists to remove.
   * The default block form carries the hairline surface and stands alone.
   */
  dense?: boolean;
  devId?: string;
  className?: string;
}

const STATE_TEXT: Record<ProductState, string> = {
  loading: "text-t3",
  empty: "text-t3",
  warning: "text-warn",
  unavailable: "text-t3",
  error: "text-err-text",
};

/** The one shell all five states render in, so they differ by TONE and wording, never by shape. */
function StateShell({
  state,
  id,
  children,
  dense = false,
  devId,
  className,
  leading,
  trailing,
  live,
}: ProductStateProps & {
  state: ProductState;
  /** A glyph or spinner before the message. */
  leading?: ReactNode;
  /** An action after the message (a retry). */
  trailing?: ReactNode;
  /** Announce the message when it appears, for states a person is waiting on. */
  live?: "polite" | "assertive";
}) {
  return (
    <div
      data-dev-id={devId}
      data-product-state={state}
      role={state === "error" ? "alert" : undefined}
      aria-live={live}
      className={cx(
        "flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1.5 text-2xs leading-relaxed",
        dense ? "py-2" : "rounded-card border border-line bg-raise px-3 py-2",
        STATE_TEXT[state],
        className,
      )}
    >
      {leading}
      <span className="min-w-0 flex-1 break-words">
        <Text id={id}>{children}</Text>
      </span>
      {trailing}
    </div>
  );
}

/**
 * We asked and have not been answered yet.
 *
 * The spinner is a ring rather than a skeleton because a skeleton claims a shape the answer may
 * not have. `motion-reduce` stops it spinning for a person who asked for stillness; it stays a
 * visible ring so the state is still legible without motion.
 */
export function LoadingState(props: ProductStateProps) {
  return (
    <StateShell
      {...props}
      state="loading"
      live="polite"
      leading={
        <svg
          aria-hidden
          viewBox="0 0 16 16"
          className="h-3 w-3 flex-none animate-spin motion-reduce:animate-none"
        >
          <circle
            cx="8"
            cy="8"
            r="6"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeDasharray="28"
            strokeDashoffset="10"
          />
        </svg>
      }
    />
  );
}

/** We were answered, and there is nothing. Names what is absent, never a spinner or a fake row. */
export function EmptyState(props: ProductStateProps) {
  return <StateShell {...props} state="empty" />;
}

/** It works, and something about it is worth knowing first. */
export function WarningState(props: ProductStateProps) {
  return <StateShell {...props} state="warning" leading={<Dot tone="warn" />} />;
}

/**
 * The capability is not offered here.
 *
 * Kept apart from `EmptyState` deliberately: "this machine has no credentials for that source"
 * and "that source answered and stocks nothing" are different sentences, and collapsing them is
 * what once let a broken API read as a part nobody sells.
 */
export function UnavailableState(props: ProductStateProps) {
  return <StateShell {...props} state="unavailable" leading={<Dot tone="neutral" />} />;
}

/**
 * It failed.
 *
 * `children` is a WRITTEN message. Callers holding an `Error` translate it first: a raw exception
 * is not a product state, and the one thing a person can do with a stack trace in a panel is
 * screenshot it.
 */
export function ErrorState({
  onRetry,
  retryDevId,
  retryPending,
  ...props
}: ProductStateProps & {
  /** Offer a retry only when the action is genuinely repeatable. */
  onRetry?: () => void;
  retryDevId?: string;
  retryPending?: boolean;
}) {
  return (
    <StateShell
      {...props}
      state="error"
      live="assertive"
      leading={<Dot tone="err" />}
      trailing={
        onRetry ? (
          <RetryAction onRetry={onRetry} devId={retryDevId} pending={retryPending} />
        ) : undefined
      }
    />
  );
}

/**
 * The retry control, on its own.
 *
 * One label for the whole app. It said "Try Again", "Retry" and "Reload" in three places, which
 * made a repeatable action look like three different affordances.
 */
export function RetryAction({
  onRetry,
  id = "state.retry",
  label = "Rerun",
  devId,
  pending = false,
}: {
  onRetry: () => void;
  id?: string;
  label?: string;
  devId?: string;
  pending?: boolean;
}) {
  const resolved = useText(id, label);
  const pendingLabel = useText("state.retrying", "Rerunning");
  return (
    <Button
      small
      data-dev-id={devId}
      onClick={onRetry}
      disabled={pending}
      aria-busy={pending || undefined}
      className="flex-none"
    >
      {pending ? pendingLabel : resolved}
    </Button>
  );
}

// Module scope: the table reads nothing local, so it is allocated once rather than per notice.
const NOTICE_TONE_TEXT: Record<BadgeTone, string> = {
  ok: "text-ok-text",
  warn: "text-warn",
  err: "text-err-text",
  neutral: "text-t3",
};

/**
 * A one-line note inside a section: a qualification, not a state of the whole surface.
 *
 * Use it when the content around it is fine and one thing about it needs saying. A notice that is
 * really the state of the whole region is one of the five states above, not this.
 */
export function InlineNotice({
  tone = "neutral",
  id,
  children,
  devId,
  action,
  className,
}: {
  tone?: BadgeTone;
  id: string;
  children: string;
  devId?: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <p
      data-dev-id={devId}
      className={cx(
        "flex min-w-0 items-center gap-2 text-2xs leading-relaxed",
        NOTICE_TONE_TEXT[tone],
        className,
      )}
    >
      <Dot tone={tone} />
      <span className="min-w-0 flex-1 break-words">
        <Text id={id}>{children}</Text>
      </span>
      {action}
    </p>
  );
}

// --------------------------------------------------------------------------- bounded region

/**
 * One bounded information region: a title, what it has, and a way to the rest.
 *
 * Lifted out of `component-workspace/WorkspaceRegion.tsx`. The contract it encodes is general and
 * is the reason the component workspace does not scroll: a region never grows past the band it
 * was given, it says how many items it is standing in for, and when there are more it hands off
 * to a modal rather than to a scrollbar.
 */
export function Region({
  devId,
  title,
  copyId,
  count,
  onViewAll,
  viewAllLabel = "View All",
  viewAllCopyId = "component-browser.view-all",
  viewAllDevId = "component-browser.view-all",
  className,
  children,
}: {
  devId: string;
  title: string;
  copyId: string;
  count?: number;
  onViewAll?: () => void;
  viewAllLabel?: string;
  viewAllCopyId?: string;
  viewAllDevId?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section
      data-dev-id={devId}
      aria-label={title}
      className={cx(
        "flex min-h-0 min-w-0 flex-col overflow-hidden rounded-card border border-line bg-raise px-3 py-2",
        className,
      )}
    >
      <header className="mb-1 flex flex-none items-center gap-2">
        <span className="min-w-0 truncate text-2xs font-semibold text-t1">
          <Text id={copyId}>{title}</Text>
        </span>
        {count != null ? (
          <span className="flex-none text-2xs tabular-nums text-t3">{count}</span>
        ) : null}
        {onViewAll ? (
          <button
            type="button"
            data-dev-id={viewAllDevId}
            onClick={onViewAll}
            className="ml-auto flex-none rounded-control px-1.5 py-0.5 text-2xs font-medium text-t2 transition-colors hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc"
          >
            <Text id={viewAllCopyId}>{viewAllLabel}</Text>
          </button>
        ) : null}
      </header>
      <div className="min-h-0 flex-1 overflow-hidden">{children}</div>
    </section>
  );
}

// --------------------------------------------------------------------------- compact fact row

const FACT_VALUE_TONE = { t1: "text-t1", t2: "text-t2", warn: "text-warn" } as const;

/**
 * One label-and-value line in a packed region.
 *
 * This shape was hand-written twelve times across the Overview regions, the compact information
 * tabs and the diagnostics list, with three different value colours and two different border
 * treatments for what is the same row. `as="li"` because half of those live in a real list and
 * half do not, and a `div` inside a `ul` is not a list item.
 */
export function FactRow({
  label,
  value,
  detail,
  action,
  mono = true,
  tone = "t1",
  as = "div",
  devId,
  title,
  className,
}: {
  label: ReactNode;
  value?: ReactNode;
  /** A second, quieter line under the label (a source, a qualifier). */
  detail?: ReactNode;
  action?: ReactNode;
  /** Values are machine data by default, so figures line up column to column. */
  mono?: boolean;
  tone?: "t1" | "t2" | "warn";
  as?: "div" | "li";
  devId?: string;
  /** The untruncated label, for the native tooltip. */
  title?: string;
  className?: string;
}) {
  const Element = as;
  return (
    <Element
      data-dev-id={devId}
      className={cx(
        "flex items-baseline gap-2 border-b border-line/60 py-1 last:border-b-0",
        className,
      )}
    >
      <span className="min-w-0 flex-1">
        <span className="block truncate text-2xs text-t2" title={title}>
          {label}
        </span>
        {detail != null ? (
          <span className="block truncate text-2xs text-t3">{detail}</span>
        ) : null}
      </span>
      {value != null ? (
        <span
          className={cx(
            "flex-none text-2xs font-semibold",
            mono && "tnum font-mono",
            FACT_VALUE_TONE[tone],
          )}
        >
          {value}
        </span>
      ) : null}
      {action}
    </Element>
  );
}

// --------------------------------------------------------------------------- attention item

/** How loud one attention item is. The three the projection emits, and nothing else. */
export type AttentionSeverity = "blocking" | "warning" | "info";

const SEVERITY_TONE: Record<AttentionSeverity, BadgeTone> = {
  blocking: "err",
  warning: "warn",
  info: "neutral",
};

/**
 * One thing that is wrong with the thing you are looking at, and the way to it.
 *
 * The action is a LINK to where the repair happens, never a claim that pressing it performs one.
 * Its accessible name carries the item's title, because "Resolve" repeated four times down a list
 * tells a screen-reader user which button they are on and nothing about what it resolves.
 */
export function AttentionItem({
  severity,
  title,
  detail,
  onAction,
  actionLabel = "Resolve",
  actionCopyId = "component-browser.attention-resolve",
  devId,
  actionDevId,
}: {
  severity: AttentionSeverity | string;
  title: string;
  detail?: string;
  onAction?: () => void;
  actionLabel?: string;
  actionCopyId?: string;
  devId?: string;
  actionDevId?: string;
}) {
  const resolved = useText(actionCopyId, actionLabel);
  return (
    <li
      data-dev-id={devId}
      className="flex items-start gap-2 border-b border-line/60 py-1.5 last:border-b-0"
    >
      <span className="mt-1 flex-none">
        <Dot tone={SEVERITY_TONE[severity as AttentionSeverity] ?? "neutral"} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-2xs font-medium text-t1" title={title}>
          {title}
        </span>
        {detail ? (
          <span className="block truncate text-2xs text-t3" title={detail}>
            {detail}
          </span>
        ) : null}
      </span>
      {onAction ? (
        <button
          type="button"
          data-dev-id={actionDevId}
          onClick={onAction}
          aria-label={`${resolved}: ${title}`}
          className="flex-none rounded-control px-1.5 py-0.5 text-2xs font-medium text-acc transition-colors hover:brightness-125 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc"
        >
          <Text id={actionCopyId}>{actionLabel}</Text>
        </button>
      ) : null}
    </li>
  );
}

// --------------------------------------------------------------------------- data table

/**
 * The table shell: a bordered header row, tabular figures, and its OWN horizontal scroller.
 *
 * The scroller is the point. A wide table is the one thing allowed to scroll sideways, because
 * the alternative is a whole sheet that scrolls sideways and drags every other section with it.
 */
export function DataTable({
  devId,
  headings,
  label,
  className,
  children,
}: {
  devId?: string;
  headings: ReactNode[];
  label: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      data-dev-id={devId}
      className={cx("overflow-x-auto rounded-card border border-line bg-raise", className)}
    >
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
