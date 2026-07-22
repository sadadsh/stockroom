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
        "group flex min-w-0 items-center gap-1.5 rounded-control px-1.5 py-1 text-left transition-colors hover:bg-raise2 disabled:cursor-not-allowed disabled:hover:bg-transparent " +
        (empty ? "italic text-t3 " : "text-t1 ") +
        (mono ? "font-mono tnum " : "") +
        (displayClassName ?? "text-base")
      }
    >
      <span className={"min-w-0 " + (truncate ? "truncate" : "break-words")}>
        {empty ? placeholder : value}
      </span>
    </button>
  );
}
