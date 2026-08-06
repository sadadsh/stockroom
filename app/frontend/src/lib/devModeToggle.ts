/**
 * The dev mode on/off switch and the label the copy editor is pointed at.
 *
 * `enabled` gates the whole editing surface (the committed overrides apply either way), and the
 * clicked label is held here rather than in the draft because which label is being edited is not
 * part of the saved document.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

export function useDevModeToggle() {
  const [enabled, setEnabled] = useState(false);
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

  const selectCopy = useCallback((id: string, defaultText: string) => {
    setSelectedCopy({ id, def: defaultText });
  }, []);
  const clearSelectedCopy = useCallback(() => setSelectedCopy(null), []);

  const api = useMemo(
    () => ({
      enabled,
      toggle,
      selectedCopyId: selectedCopy?.id ?? null,
      selectedCopyDefault: selectedCopy?.def ?? "",
      selectCopy,
      clearSelectedCopy,
    }),
    [enabled, toggle, selectedCopy, selectCopy, clearSelectedCopy],
  );

  return { api, enabled, clearSelectedCopy };
}
