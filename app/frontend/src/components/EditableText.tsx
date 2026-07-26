/**
 * A click-to-edit text value. Click the value to edit it inline; Enter (or blur)
 * saves, Escape cancels. Empty values read as a quiet, fillable hint rather than
 * a hard error, because editing is how you complete a part. All the save-once /
 * never-on-cancel logic lives in useInlineEdit (locked by its own test); this
 * component is only the view.
 */
import type { KeyboardEvent } from "react";
import { useInlineEdit } from "../lib/useInlineEdit";

interface Props {
  value: string;
  onSave: (next: string) => void;
  label: string;
  placeholder?: string;
  multiline?: boolean;
  mono?: boolean;
  disabled?: boolean;
  displayClassName?: string;
  // Clamp the resting display to a single line with an ellipsis (for a long value like a
  // datasheet URL that must not wrap the row); editing still opens the full field.
  truncate?: boolean;
  // Clamp the resting display to N lines with an ellipsis (for a verbose note that should
  // not sprawl the rail); editing still opens the full field. Ignored when `truncate` is set.
  clampLines?: number;
  // A clean label to SHOW when not editing (e.g. a datasheet's host instead of the
  // raw URL). Editing still operates on `value`, so nothing about save changes.
  display?: string;
}

export function EditableText({
  value,
  onSave,
  label,
  placeholder = "Add",
  multiline = false,
  mono = false,
  disabled = false,
  displayClassName,
  truncate = false,
  clampLines,
  display,
}: Props) {
  const { editing, draft, setDraft, begin, commit, cancel } = useInlineEdit(
    value,
    onSave,
  );

  function onKeyDown(e: KeyboardEvent) {
    if (e.key === "Escape") {
      e.preventDefault();
      cancel();
    } else if (e.key === "Enter" && (!multiline || e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      commit();
    }
  }

  if (editing) {
    const shared =
      "w-full rounded-control border border-line2 bg-field px-2 py-1 text-base text-t1 outline-none focus:border-acc " +
      // Machine values edit in the mono readout face with tabular figures, so the
      // field looks like the value it replaces (no face swap on click).
      (mono ? "font-mono tnum " : "");
    return multiline ? (
      <textarea
        autoFocus
        rows={3}
        aria-label={label}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={onKeyDown}
        onBlur={commit}
        className={shared + "resize-y"}
      />
    ) : (
      <input
        autoFocus
        aria-label={label}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={onKeyDown}
        onBlur={commit}
        className={shared}
      />
    );
  }

  const empty = !value;
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={begin}
      aria-label={`Edit ${label}`}
      className={
        // max-w-full is LOAD-BEARING for `truncate`. This button is sized by its CONTENT, so a long
        // unbroken value (a URL has no spaces to break at) made it wider than its own parent and the
        // inner truncating span inherited that width - so it never ellipsised and simply overflowed.
        // MEASURED in the owner's real window 2026-07-25: button 345/345 and span 333/333 inside a
        // 197px parent. `min-w-0` alone cannot fix this; it permits shrinking below content, it does
        // not impose a ceiling.
        "group flex min-w-0 max-w-full items-center gap-1.5 rounded-control px-1.5 py-1 text-left transition-colors hover:bg-raise2 disabled:cursor-not-allowed disabled:hover:bg-transparent " +
        (empty ? "italic text-t3 " : "text-t1 ") +
        (mono ? "font-mono tnum " : "") +
        (displayClassName ?? "text-base")
      }
    >
      <span
        className={"min-w-0 " + (truncate ? "truncate" : "break-words")}
        style={
          !truncate && clampLines
            ? {
                display: "-webkit-box",
                WebkitLineClamp: clampLines,
                WebkitBoxOrient: "vertical",
                overflow: "hidden",
              }
            : undefined
        }
      >
        {empty ? placeholder : (display ?? value)}
      </span>
    </button>
  );
}
