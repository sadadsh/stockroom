/**
 * Dev Mode v2 inspect-first shell state: the one element selection that drives the Selection pane,
 * the Tokens tab and the Copy tab, plus the two overlay toggles (pointing mode and the all-at-once
 * id badges) and the highlighted design tokens of that selection.
 *
 * None of this is part of the saved override document, so it is deliberately outside the draft
 * reducer: it is never snapshotted for undo and never written back to source.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  designIdSelector,
  ensureDesignOccurrenceIdentities,
  exactDesignTargetAuthority,
  rebindExactDesignTargetAuthority,
  releaseExactDesignTargetAuthority,
  upgradeExactDesignTargetAuthority,
  type ExactDesignTargetAuthority,
} from "./designIdentity";

interface SelectionState {
  selectedDevId: string | null;
  selectedTarget: ExactDesignTargetAuthority | null;
}

export function useDevModeSelection() {
  const [selection, setSelection] = useState<SelectionState>({
    selectedDevId: null,
    selectedTarget: null,
  });
  const [inspect, setInspect] = useState(false);
  const [showIds, setShowIds] = useState(false);
  const [highlightedVars, setHighlightedVars] = useState<string[]>([]);

  const selectTarget = useCallback((element: Element | null) => {
    const target = exactDesignTargetAuthority(element);
    setSelection({ selectedDevId: target?.id ?? null, selectedTarget: target });
  }, []);
  const selectDevId = useCallback((id: string | null) => {
    if (!id) {
      setSelection({ selectedDevId: null, selectedTarget: null });
      return;
    }
    const matches = Array.from(document.querySelectorAll(designIdSelector(id)))
      .filter((element) => !element.closest("[data-design-studio-chrome]"));
    const target = matches.length === 1 ? exactDesignTargetAuthority(matches[0]) : null;
    setSelection({ selectedDevId: id, selectedTarget: target });
  }, []);
  const setInspectMode = useCallback((value: boolean) => setInspect(value), []);
  const toggleInspect = useCallback(() => setInspect((v) => !v), []);
  const toggleShowIds = useCallback(() => setShowIds((v) => !v), []);
  const selectVars = useCallback((vars: string[]) => setHighlightedVars(vars), []);

  useEffect(() => {
    const target = selection.selectedTarget;
    if (!target) return;
    const reconcileTarget = () => {
      const matches = Array.from(target.element.ownerDocument.querySelectorAll(designIdSelector(target.id)))
        .filter((element) => !element.closest("[data-design-studio-chrome]"));
      if (target.element.isConnected) {
        const upgraded = upgradeExactDesignTargetAuthority(target);
        if (!upgraded) {
          releaseExactDesignTargetAuthority(target);
          setSelection((current) => current.selectedTarget === target
            ? { selectedDevId: null, selectedTarget: null }
            : current);
          return;
        }
        if (upgraded !== target) {
          setSelection((current) => current.selectedTarget === target
            ? { selectedDevId: upgraded.id, selectedTarget: upgraded }
            : current);
        }
        return;
      }
      ensureDesignOccurrenceIdentities(target.element.ownerDocument);
      // Rebind only a selection that remained semantically unique. Once it has upgraded to an
      // occurrence address, a lone surviving peer is not proof of the removed occurrence.
      if (target.overrideId === target.id && matches.length === 1) {
        const rebound = rebindExactDesignTargetAuthority(target, matches[0]);
        if (rebound) {
          setSelection((current) => current.selectedTarget === target
            ? { selectedDevId: rebound.id, selectedTarget: rebound }
            : current);
          return;
        }
      }
      releaseExactDesignTargetAuthority(target);
      setSelection((current) => current.selectedTarget === target
        ? { selectedDevId: null, selectedTarget: null }
        : current);
    };
    const observer = new MutationObserver(reconcileTarget);
    observer.observe(document.documentElement, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [selection.selectedTarget]);

  const api = useMemo(
    () => ({
      selectedDevId: selection.selectedDevId,
      selectedTarget: selection.selectedTarget,
      selectDevId,
      selectTarget,
      inspect,
      toggleInspect,
      showIds,
      toggleShowIds,
      highlightedVars,
      selectVars,
    }),
    [
      selection.selectedDevId,
      selection.selectedTarget,
      selectDevId,
      selectTarget,
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
