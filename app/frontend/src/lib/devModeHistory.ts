/**
 * Undo/redo for dev mode: one snapshot stack over the WHOLE override draft.
 *
 * History is deliberately not per-facet. Every edit - token, copy, icon, box, behavior - lands in
 * the same draft, so a snapshot of that draft is a complete history step and a new facet cannot
 * silently fall outside the stack.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { DevModeDraft } from "./devModeDraft";

/**
 * `restore` must write all five draft slices in one go; this hook flags the write as a history
 * restore first, so the snapshot effect does not record the restore as a fresh edit.
 */
export function useDevModeHistory(draft: DevModeDraft, restore: (next: DevModeDraft) => void) {
  const currentSnapshot = JSON.stringify(draft);
  const lastSnapshotRef = useRef(currentSnapshot);
  const undoRef = useRef<string[]>([]);
  const redoRef = useRef<string[]>([]);
  const restoringHistoryRef = useRef(false);
  // The stacks live in refs so recording history does not itself create another snapshot. Keep a
  // small revision counter in the context memo dependencies so Undo/Redo enable immediately after
  // a ref-only stack mutation.
  const [historyRevision, setHistoryRevision] = useState(0);

  useEffect(() => {
    if (currentSnapshot === lastSnapshotRef.current) return;
    if (restoringHistoryRef.current) {
      restoringHistoryRef.current = false;
    } else {
      undoRef.current = [...undoRef.current.slice(-49), lastSnapshotRef.current];
      redoRef.current = [];
    }
    lastSnapshotRef.current = currentSnapshot;
    setHistoryRevision((revision) => revision + 1);
  }, [currentSnapshot]);

  const restoreSnapshot = useCallback(
    (raw: string) => {
      const next = JSON.parse(raw) as DevModeDraft;
      restoringHistoryRef.current = true;
      restore(next);
    },
    [restore],
  );

  const undo = useCallback(() => {
    const previous = undoRef.current.pop();
    if (!previous) return;
    redoRef.current.push(lastSnapshotRef.current);
    restoreSnapshot(previous);
  }, [restoreSnapshot]);

  const redo = useCallback(() => {
    const next = redoRef.current.pop();
    if (!next) return;
    undoRef.current.push(lastSnapshotRef.current);
    restoreSnapshot(next);
  }, [restoreSnapshot]);

  const canUndo = undoRef.current.length > 0;
  const canRedo = redoRef.current.length > 0;

  const api = useMemo(
    () => ({ canUndo, canRedo, undo, redo }),
    [canUndo, canRedo, undo, redo],
  );

  return { api, historyRevision, undo, redo };
}

/**
 * Ctrl/Cmd+Z undoes and Ctrl/Cmd+Shift+Z redoes, but only while dev mode is on and only when the
 * keystroke is not aimed at a text field - otherwise this would steal the browser's own undo from
 * the copy editor and every other input in the app.
 */
export function useDevModeHistoryKeys(enabled: boolean, undo: () => void, redo: () => void) {
  useEffect(() => {
    function onHistoryKey(event: KeyboardEvent) {
      if (!enabled || !(event.ctrlKey || event.metaKey) || event.altKey) return;
      const target = event.target;
      if (target instanceof Element && target.matches("input, textarea, [contenteditable='true']")) return;
      if (event.key.toLowerCase() !== "z") return;
      event.preventDefault();
      if (event.shiftKey) redo();
      else undo();
    }
    window.addEventListener("keydown", onHistoryKey);
    return () => window.removeEventListener("keydown", onHistoryKey);
  }, [enabled, undo, redo]);
}
