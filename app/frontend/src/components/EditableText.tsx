/**
 * A click-to-edit text value. Click the value to edit it inline; Enter (or blur)
 * saves, Escape cancels. A no-op edit (unchanged value) never fires onSave, so we
 * never send a pointless mutation. Empty values read as a quiet, fillable hint
 * rather than a hard error, because editing is how you complete a part.
 *
 * One `active` guard resolves the two inline-edit races: committing on Enter also
 * blurs the input (which would commit again), and Escape unmounts the input
 * (whose blur would otherwise save). Whichever path fires first clears the guard,
 * so the field saves at most once and never on cancel.
 */
import { useEffect, useRef, useState, type KeyboardEvent } from "react";

interface Props {
  value: string;
  onSave: (next: string) => void;
  label: string;
  placeholder?: string;
  multiline?: boolean;
  mono?: boolean;
  disabled?: boolean;
  displayClassName?: string;
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
}: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const active = useRef(false);

  // Keep the draft in sync when the underlying value changes (e.g. a different
  // part is selected) but never clobber an in-progress edit.
  useEffect(() => {
    if (!editing) setDraft(value);
  }, [value, editing]);

  function begin() {
    active.current = true;
    setDraft(value);
    setEditing(true);
  }

  function commit() {
    if (!active.current) return;
    active.current = false;
    setEditing(false);
    const next = draft.trim();
    if (next !== value) onSave(next);
  }

  function cancel() {
    active.current = false;
    setDraft(value);
    setEditing(false);
  }

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
      (mono ? "tnum " : "");
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
        (mono ? "tnum " : "") +
        (displayClassName ?? "text-base")
      }
    >
      <span className="min-w-0 break-words">{empty ? placeholder : value}</span>
    </button>
  );
}
