/**
 * Dev Mode v2 inspect-first shell state: the one element selection that drives the Selection pane,
 * the Tokens tab and the Copy tab, plus the two overlay toggles (pointing mode and the all-at-once
 * id badges) and the highlighted design tokens of that selection.
 *
 * None of this is part of the saved override document, so it is deliberately outside the draft
 * reducer: it is never snapshotted for undo and never written back to source.
 */
import { useCallback, useMemo, useState } from "react";

export function useDevModeSelection() {
  const [selectedDevId, setSelectedDevId] = useState<string | null>(null);
  const [inspect, setInspect] = useState(false);
  const [showIds, setShowIds] = useState(false);
  const [highlightedVars, setHighlightedVars] = useState<string[]>([]);

  const selectDevId = useCallback((id: string | null) => setSelectedDevId(id), []);
  const setInspectMode = useCallback((value: boolean) => setInspect(value), []);
  const toggleInspect = useCallback(() => setInspect((v) => !v), []);
  const toggleShowIds = useCallback(() => setShowIds((v) => !v), []);
  const selectVars = useCallback((vars: string[]) => setHighlightedVars(vars), []);

  const api = useMemo(
    () => ({
      selectedDevId,
      selectDevId,
      inspect,
      toggleInspect,
      showIds,
      toggleShowIds,
      highlightedVars,
      selectVars,
    }),
    [
      selectedDevId,
      selectDevId,
      inspect,
      toggleInspect,
      showIds,
      toggleShowIds,
      highlightedVars,
      selectVars,
    ],
  );

  return { api, setInspectMode };
}
