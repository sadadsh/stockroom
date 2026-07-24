/**
 * One collapsible settings row (the Settings IA remake): a full-width header the
 * user can scan without scrolling a wall of open cards - the title, a LIVE summary
 * of the section's state on the right, and a caret. The content card mounts only
 * while open, so a collapsed section costs nothing. Controlled by the page (the
 * Machine Setup band jumps sections open), with aria-expanded carrying the state
 * for tests and assistive tech alike.
 */
import { type ReactNode } from "react";
import { Card } from "./primitives";
import { Text } from "../lib/copy";

export function SettingsDisclosure({
  title,
  titleId,
  hint,
  hintId,
  summary,
  open,
  onToggle,
  children,
  "data-dev-id": devId,
}: {
  title: string;
  titleId?: string;
  hint?: string;
  hintId?: string;
  summary?: ReactNode;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
  "data-dev-id"?: string;
}) {
  return (
    <section className="border-b border-line last:border-b-0" data-dev-id={devId}>
      <button
        type="button"
        aria-expanded={open}
        onClick={onToggle}
        data-testid={devId ? `${devId}.header` : undefined}
        className="flex h-[44px] w-full items-center gap-2.5 rounded-control px-1.5 text-left transition-colors hover:bg-[var(--c-hover)] focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-acc"
      >
        <span
          aria-hidden
          className={
            "flex-none text-t3 transition-transform duration-150 " +
            (open ? "rotate-90" : "")
          }
        >
          {/* a small right-pointing caret, rotated down when open */}
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
            <path d="M3 1.5 7 5 3 8.5" stroke="currentColor" strokeWidth="1.5"
                  strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </span>
        <span className="min-w-0 flex-1 truncate text-sm font-medium text-t1">
          {titleId ? <Text id={titleId}>{title}</Text> : title}
        </span>
        {summary ? (
          <span className="flex flex-none items-center gap-1.5 text-xs text-t3">{summary}</span>
        ) : null}
      </button>
      {open ? (
        <div className="pb-4 pl-6 pr-1.5 pt-0.5">
          {hint ? (
            <p className="mb-2.5 text-xs text-t3">
              {hintId ? <Text id={hintId}>{hint}</Text> : hint}
            </p>
          ) : null}
          <Card className="px-4 py-3.5">{children}</Card>
        </div>
      ) : null}
    </section>
  );
}
