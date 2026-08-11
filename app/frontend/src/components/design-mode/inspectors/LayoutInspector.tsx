import { useDevMode } from "../../../lib/devMode";
import { useText } from "../../../lib/copy";
import type { DomainInspectorProps } from "./types";

export function LayoutInspector(props: DomainInspectorProps) {
  const dev = useDevMode();
  const visibilityLabel = useText("design-studio.inspector.layout.visibility", "Show");
  const visibilityAria = useText("design-studio.inspector.layout.visibility-aria", "Arrangement Show Mode");
  const visibleLabel = useText("design-studio.inspector.layout.visible", "Visible");
  const hiddenLabel = useText("design-studio.inspector.layout.hidden", "Hidden");
  const restoreLabel = useText("design-studio.inspector.layout.restore", "Restore To Arrangement");
  const removeLabel = useText("design-studio.inspector.layout.remove", "Remove From Arrangement");
  const removalHint = useText("design-studio.inspector.layout.removal-hint", "Removal writes reversible presentation state into the current design undo timeline. Production JSX and product data are unchanged.");
  const removed = props.affectedTargetIds.every(
    (id) => dev.elementOverridesFor(id)?.display === "none",
  );
  return (
    <div className="px-3.5 py-3">
      <label className="flex items-center justify-between gap-3 text-xs text-t2">
        {visibilityLabel}
        <select
          aria-label={visibilityAria}
          value={dev.elementOverridesFor(props.affectedTargetIds[0] ?? props.inspection.id)?.visibility ?? "visible"}
          onChange={(event) => event.target.value === "visible" ? props.resetDomainProperty("box", "visibility") : props.setDomainProperty("box", "visibility", event.target.value)}
          className="rounded-control border border-line bg-field px-2 py-1 text-2xs text-t1"
        >
          <option value="visible">{visibleLabel}</option>
          <option value="hidden">{hiddenLabel}</option>
        </select>
      </label>
      <button
        type="button"
        onClick={() => removed ? props.resetDomainProperty("box", "display") : props.setDomainProperty("box", "display", "none")}
        className="mt-3 w-full rounded-control border border-line bg-field px-2 py-2 text-xs font-semibold text-t2 hover:text-t1"
      >
        {removed ? restoreLabel : removeLabel}
      </button>
      <p className="mt-2 text-2xs leading-relaxed text-t3">{removalHint}</p>
    </div>
  );
}
