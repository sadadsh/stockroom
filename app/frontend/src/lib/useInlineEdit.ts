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
import { useRef, useState } from "react";

export function useInlineEdit(value: string, onSave: (next: string) => void) {
  const [editing, setEditing] = useState(false);
  // What the person has TYPED. Only meaningful while editing, which is why the draft below is
  // derived rather than stored: outside an edit the draft simply IS the underlying value.
  const [typed, setTyped] = useState(value);
  const active = useRef(false);

  // The draft, derived. This used to be a second piece of state kept in step by an effect, which
  // cost a wasted render every time a different part was selected or a save landed - and left one
  // frame in which the field was not editing but still showed the previous edit's text. Derived,
  // the two cannot disagree and there is no frame to be wrong in.
  const draft = editing ? typed : value;

  function begin() {
    active.current = true;
    setTyped(value);
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
    setTyped(value);
    setEditing(false);
  }

  return { editing, draft, setDraft: setTyped, begin, commit, cancel };
}
