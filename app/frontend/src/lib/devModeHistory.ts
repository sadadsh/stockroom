/**
 * Undo/redo for dev mode: one snapshot stack over the WHOLE override draft.
 *
 * History is deliberately not per-facet. Every edit - token, copy, icon, box, behavior - lands in
 * the same draft, so a snapshot of that draft is a complete history step and a new facet cannot
 * silently fall outside the stack.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { DevModeDraft } from "./devModeDraft";

export interface DevModeHistoryParticipant {
  read: () => string;
  restore: (snapshot: string) => void;
}

interface DevModeHistorySnapshot {
  draft: string;
  participants: Record<string, string>;
}

/**
 * `restore` must write all five draft slices in one go; this hook flags the write as a history
 * restore first, so the snapshot effect does not record the restore as a fresh edit.
 */
export function useDevModeHistory(draft: DevModeDraft, restore: (next: DevModeDraft) => void) {
  const currentSnapshot = JSON.stringify(draft);
  const participantsRef = useRef(new Map<string, DevModeHistoryParticipant>());
  const lastSnapshotRef = useRef<DevModeHistorySnapshot>({
    draft: currentSnapshot,
    participants: {},
  });
  const undoRef = useRef<DevModeHistorySnapshot[]>([]);
  const redoRef = useRef<DevModeHistorySnapshot[]>([]);
  const restoringDraftRef = useRef<string | null>(null);
  // The stacks live in refs so recording history does not itself create another snapshot. Keep a
  // small revision counter in the context memo dependencies so Undo/Redo enable immediately after
  // a ref-only stack mutation.
  const [historyRevision, setHistoryRevision] = useState(0);

  const captureSnapshot = useCallback((draftSnapshot: string): DevModeHistorySnapshot => {
    const participants: Record<string, string> = {};
    for (const [key, participant] of participantsRef.current) {
      participants[key] = participant.read();
    }
    return { draft: draftSnapshot, participants };
  }, []);

  const registerParticipant = useCallback(
    (key: string, participant: DevModeHistoryParticipant) => {
      participantsRef.current.set(key, participant);
      if (!(key in lastSnapshotRef.current.participants)) {
        lastSnapshotRef.current = {
          ...lastSnapshotRef.current,
          participants: {
            ...lastSnapshotRef.current.participants,
            [key]: participant.read(),
          },
        };
      }
      return () => {
        if (participantsRef.current.get(key) === participant) {
          participantsRef.current.delete(key);
        }
      };
    },
    [],
  );

  useEffect(() => {
    if (currentSnapshot === lastSnapshotRef.current.draft) return;
    if (restoringDraftRef.current === currentSnapshot) {
      restoringDraftRef.current = null;
    } else {
      undoRef.current = [...undoRef.current.slice(-49), lastSnapshotRef.current];
      redoRef.current = [];
      lastSnapshotRef.current = captureSnapshot(currentSnapshot);
    }
    setHistoryRevision((revision) => revision + 1);
  }, [captureSnapshot, currentSnapshot]);

  const restoreSnapshot = useCallback(
    (snapshot: DevModeHistorySnapshot) => {
      for (const [key, raw] of Object.entries(snapshot.participants)) {
        participantsRef.current.get(key)?.restore(raw);
      }
      const next = JSON.parse(snapshot.draft) as DevModeDraft;
      restoringDraftRef.current = snapshot.draft;
      lastSnapshotRef.current = snapshot;
      restore(next);
    },
    [restore],
  );

  const replaceAtomically = useCallback(
    (nextDraft: DevModeDraft, participantKey: string, participantSnapshot: string) => {
      const participant = participantsRef.current.get(participantKey);
      if (!participant) {
        throw new Error(`Unknown Dev Mode history participant: ${participantKey}`);
      }
      undoRef.current = [
        ...undoRef.current.slice(-49),
        captureSnapshot(lastSnapshotRef.current.draft),
      ];
      redoRef.current = [];
      const draftSnapshot = JSON.stringify(nextDraft);
      const next = captureSnapshot(draftSnapshot);
      next.participants[participantKey] = participantSnapshot;
      participant.restore(participantSnapshot);
      restoringDraftRef.current = draftSnapshot;
      lastSnapshotRef.current = next;
      restore(nextDraft);
      setHistoryRevision((revision) => revision + 1);
    },
    [captureSnapshot, restore],
  );

  const undo = useCallback(() => {
    const previous = undoRef.current.pop();
    if (!previous) return;
    redoRef.current.push(captureSnapshot(lastSnapshotRef.current.draft));
    restoreSnapshot(previous);
    setHistoryRevision((revision) => revision + 1);
  }, [captureSnapshot, restoreSnapshot]);

  const redo = useCallback(() => {
    const next = redoRef.current.pop();
    if (!next) return;
    undoRef.current.push(captureSnapshot(lastSnapshotRef.current.draft));
    restoreSnapshot(next);
    setHistoryRevision((revision) => revision + 1);
  }, [captureSnapshot, restoreSnapshot]);

  const canUndo = undoRef.current.length > 0;
  const canRedo = redoRef.current.length > 0;

  const api = useMemo(
    () => ({ canUndo, canRedo, undo, redo }),
    [canUndo, canRedo, undo, redo],
  );

  return {
    api,
    historyRevision,
    undo,
    redo,
    registerParticipant,
    replaceAtomically,
  };
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
