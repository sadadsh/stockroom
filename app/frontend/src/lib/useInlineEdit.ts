/**
 * The state machine behind an inline click-to-edit field, extracted so its one
 * hard invariant is testable in isolation: a field saves AT MOST ONCE per edit
 * and NEVER on cancel. In a real browser both races fire a second commit that
 * the unit DOM (jsdom) cannot reproduce (it does not dispatch blur on an
 * unmounted input), so the guard is locked here by driving commit()/cancel()
 * directly rather than through simulated events.
 *
 * The guard is a ref (not state) because it must flip synchronously within a
 * single tick: commit() and cancel() clear it immediately, so any second commit
 * queued in the same tick (Enter-then-blur, Escape-then-blur) is a no-op.
 */
import { useEffect, useRef, useState } from "react";

export function useInlineEdit(value: string, onSave: (next: string) => void) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const active = useRef(false);

  // Keep the draft in sync when the underlying value changes (a different part is
  // selected, or a save lands) but never clobber an in-progress edit.
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

  return { editing, draft, setDraft, begin, commit, cancel };
}
