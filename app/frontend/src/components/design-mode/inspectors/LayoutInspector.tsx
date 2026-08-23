import { useDevMode } from "../../../lib/devMode";
import { useText } from "../../../lib/copy";
import type { DomainInspectorProps } from "./types";
import { isProtectedDesignRoot } from "../../../lib/designIdentity";

export function LayoutInspector(props: DomainInspectorProps) {
  const dev = useDevMode();
  const restoreLabel = useText("design-studio.inspector.layout.restore", "Restore Element");
  const removeLabel = useText("design-studio.inspector.layout.remove", "Remove From Arrangement");
  const removalHint = useText("design-studio.inspector.layout.removal-hint", "Removed elements remain available in Layers and Undo.");
  const protectedRoot = isProtectedDesignRoot(props.inspection.target);
  const removed = props.affectedTargetIds.every(
    (id) => dev.elementOverridesFor(id)?.display === "none",
  );
  return (
    <div className="px-3.5 py-3">
      <button
        type="button"
        disabled={protectedRoot}
        onClick={() => removed ? props.resetDomainProperty("box", "display") : props.setDomainProperty("box", "display", "none")}
        className="w-full rounded-control bg-field px-2 py-2 text-xs font-semibold text-t2 hover:bg-raise2 hover:text-t1"
      >
        {removed ? restoreLabel : removeLabel}
      </button>
      <p className="mt-2 text-2xs leading-relaxed text-t3">{removalHint}</p>
    </div>
  );
}
