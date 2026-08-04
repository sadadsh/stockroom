/**
 * One bounded region of the component workspace: a title, what it has, and a way to the rest.
 *
 * Every information region on this surface is the same object - it never grows past the band it
 * was given, it says how many items it is standing in for, and when there are more it hands off to
 * a modal rather than to a scrollbar. Sharing the shell is what keeps that promise identical in
 * four places instead of four regions that each drifted their own way out of the viewport.
 */
import type { ReactNode } from "react";
import { Text } from "../../lib/copy";

export function Region({
  devId,
  title,
  copyId,
  count,
  onViewAll,
  viewAllLabel = "View All",
  viewAllCopyId = "component-browser.view-all",
  viewAllDevId = "component-browser.view-all",
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
  children: ReactNode;
}) {
  return (
    <section
      data-dev-id={devId}
      aria-label={title}
      className="flex min-h-0 min-w-0 flex-col overflow-hidden rounded-card border border-line bg-raise px-3 py-2"
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

/** An honest empty region: it says what is absent, never a spinner or a fabricated placeholder row. */
export function Empty({ id, children }: { id: string; children: string }) {
  return (
    <p className="py-2 text-2xs text-t3">
      <Text id={id}>{children}</Text>
    </p>
  );
}
