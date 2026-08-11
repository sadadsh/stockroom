/**
 * The dev mode on/off switch, the ARRANGE switch inside it, and the label the copy editor is
 * pointed at.
 *
 * `enabled` gates the whole editing surface (the committed overrides apply either way), and the
 * clicked label is held here rather than in the draft because which label is being edited is not
 * part of the saved document.
 *
 * ARRANGE (plan 1.5, Phase 3B) is a second switch and not a third mode. It turns the running
 * application into the canvas - handles over every placement, draggable region boundaries, a
 * settings menu per piece - and it is deliberately reported as `enabled && editMode` rather than as
 * its own raw flag: arrange chrome must be unreachable the moment dev mode goes away, and one AND
 * here is a guarantee, where the same AND repeated at each of eight call sites is a convention.
 * With it OFF nothing about the application changes by a single byte, which is the regression gate
 * `ComponentWorkspace.domParity.test.tsx` holds this phase to.
 *
 * It is NOT part of the override draft, for the same reason `inspect` and `showIds` are not: which
 * mode the editor is in is not part of the document being edited, so it is never snapshotted for
 * undo and never written back to source.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

export function useDevModeToggle() {
  const [enabled, setEnabled] = useState(false);
  const [editMode, setEditMode] = useState(false);
  const [selectedCopy, setSelectedCopy] = useState<{ id: string; def: string } | null>(null);

  // Ctrl/Cmd+Shift+D toggles the whole surface. It is the only way in, so dev mode is hidden.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === "D" || e.key === "d")) {
        e.preventDefault();
        setEnabled((v) => !v);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const toggle = useCallback(() => setEnabled((v) => !v), []);
  const setArrangeMode = useCallback((value: boolean) => setEditMode(value), []);
  const toggleEditMode = useCallback(() => setEditMode((v) => !v), []);

  const selectCopy = useCallback((id: string, defaultText: string) => {
    setSelectedCopy({ id, def: defaultText });
  }, []);
  const clearSelectedCopy = useCallback(() => setSelectedCopy(null), []);

  const api = useMemo(
    () => ({
      enabled,
      toggle,
      // The AND, in the one place it can be: arrange chrome cannot outlive dev mode.
      editMode: enabled && editMode,
      toggleEditMode,
      selectedCopyId: selectedCopy?.id ?? null,
      selectedCopyDefault: selectedCopy?.def ?? "",
      selectCopy,
      clearSelectedCopy,
    }),
    [enabled, toggle, editMode, toggleEditMode, selectedCopy, selectCopy, clearSelectedCopy],
  );

  return { api, enabled, clearSelectedCopy, setArrangeMode };
}
