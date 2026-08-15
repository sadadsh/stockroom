/**
 * One permanent settings capability card.
 *
 * Settings used to render every capability as an identical collapsed row. That made a theme
 * choice, an automatic health check, a credential form, and destructive recovery look like the
 * same kind of button. The category navigation already limits how much is visible, so a second
 * disclosure layer only hid meaning. Cards now state scope, live status, and consequence before
 * exposing their controls.
 */
import { type ReactNode } from "react";
import { Text } from "../lib/copy";

function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

export function SettingsDisclosure({
  title,
  titleId,
  hint,
  hintId,
  summary,
  children,
  className,
  "data-dev-id": devId,
}: {
  title: string;
  titleId?: string;
  hint?: string;
  hintId?: string;
  summary?: ReactNode;
  children: ReactNode;
  className?: string;
  "data-dev-id"?: string;
}) {
  return (
    <section
      aria-labelledby={devId ? `${devId}.title` : undefined}
      className={cx(
        "flex min-w-0 scroll-mt-3 flex-col overflow-hidden rounded-card border border-line bg-raise outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
        className,
      )}
      data-dev-id={devId}
      tabIndex={-1}
    >
      <div
        data-testid={devId ? `${devId}.header` : undefined}
        className="flex min-h-[54px] items-start gap-3 border-b border-line bg-band px-3.5 py-3"
      >
        <div className="min-w-0 flex-1">
          <h2 id={devId ? `${devId}.title` : undefined} className="text-sm font-semibold text-t1">
            {titleId ? <Text id={titleId}>{title}</Text> : title}
          </h2>
          {hint ? (
            <p className="mt-0.5 max-w-[72ch] text-xs leading-relaxed text-t3">
              {hintId ? <Text id={hintId}>{hint}</Text> : hint}
            </p>
          ) : null}
        </div>
        {summary ? (
          <span
            className="mt-0.5 flex flex-none items-center gap-1.5 whitespace-nowrap rounded-control border border-line bg-field px-2 py-1 text-2xs font-medium text-t2"
            data-testid="settings.summary"
          >
            {summary}
          </span>
        ) : null}
      </div>
      <div className="min-w-0 px-3.5 py-3.5">{children}</div>
    </section>
  );
}
