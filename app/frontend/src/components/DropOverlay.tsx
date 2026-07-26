/**
 * The whole window is a drop target (design spec section 7 Feel). This overlay
 * listens for a file drag anywhere in the window, shows a "drop to add" scrim, and
 * on drop hands the native file paths to onDrop. pywebview exposes the real
 * filesystem path on each File as `pywebviewFullPath`; a plain browser drag has no
 * path, so a browser-only drop is a no-op (real ingestion happens in the WebView2
 * host). A drag depth counter keeps the overlay stable across child elements.
 */
import { useEffect, useRef, useState } from "react";
import { UploadIcon } from "./icons";

function dragHasFiles(e: DragEvent): boolean {
  const types = e.dataTransfer?.types;
  if (!types) return false;
  return Array.from(types as ArrayLike<string>).includes("Files");
}

export function DropOverlay({ onDrop }: { onDrop: (paths: string[]) => void }) {
  const [active, setActive] = useState(false);
  const depth = useRef(0);

  useEffect(() => {
    function onEnter(e: DragEvent) {
      if (!dragHasFiles(e)) return;
      depth.current += 1;
      setActive(true);
    }
    function onOver(e: DragEvent) {
      // Preventing default marks the window a valid drop zone so `drop` fires.
      if (dragHasFiles(e)) e.preventDefault();
    }
    function onLeave() {
      depth.current = Math.max(0, depth.current - 1);
      if (depth.current === 0) setActive(false);
    }
    function onDropEvt(e: DragEvent) {
      e.preventDefault();
      depth.current = 0;
      setActive(false);
      const files = Array.from(e.dataTransfer?.files ?? []);
      const paths = files
        .map(
          (f) => (f as unknown as { pywebviewFullPath?: string }).pywebviewFullPath,
        )
        .filter((p): p is string => !!p);
      if (paths.length > 0) onDrop(paths);
    }
    window.addEventListener("dragenter", onEnter);
    window.addEventListener("dragover", onOver);
    window.addEventListener("dragleave", onLeave);
    window.addEventListener("drop", onDropEvt);
    return () => {
      window.removeEventListener("dragenter", onEnter);
      window.removeEventListener("dragover", onOver);
      window.removeEventListener("dragleave", onLeave);
      window.removeEventListener("drop", onDropEvt);
    };
  }, [onDrop]);

  if (!active) return null;
  return (
    <div data-dev-id="shell.drop-overlay" className="fixed inset-0 z-[200] flex items-center justify-center bg-[rgba(0,0,0,0.55)]">
      {/* the scrim is dark in both themes, so this card is fixed light-on-dark
          rather than theme-tokened (a light-theme accent would vanish here). */}
      <div className="rounded-card border-2 border-dashed border-white/70 bg-white/5 px-10 py-8 text-center">
        <div className="flex justify-center text-white/70">
          <UploadIcon />
        </div>
        <div className="mt-2 text-sm font-medium text-white">Drop to Add Parts</div>
        <div className="mt-1 text-xs text-white/60">Release a vendor ZIP to inspect it.</div>
      </div>
    </div>
  );
}
