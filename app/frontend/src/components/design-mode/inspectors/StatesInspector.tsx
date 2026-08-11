import { useEffect, useState } from "react";
import { useText } from "../../../lib/copy";
import type { DomainInspectorProps } from "./types";

type PreviewState = "default" | "focus" | "disabled";

export function StatesInspector({ inspection }: DomainInspectorProps) {
  const [state, setState] = useState<PreviewState>("default");
  const defaultLabel = useText("design-studio.inspector.states.default", "Default");
  const focusLabel = useText("design-studio.inspector.states.focus", "Focus");
  const disabledLabel = useText("design-studio.inspector.states.disabled", "Disabled");
  const emptyLabel = useText("design-studio.inspector.states.empty", "No product state is declared on this target.");
  const states: readonly { value: PreviewState; label: string }[] = [
    { value: "default", label: defaultLabel },
    { value: "focus", label: focusLabel },
    { value: "disabled", label: disabledLabel },
  ];
  useEffect(() => {
    const target = inspection.target;
    const previous = target.getAttribute("data-design-preview-state");
    if (state === "default") target.removeAttribute("data-design-preview-state");
    else target.setAttribute("data-design-preview-state", state);
    if (state === "focus" && target instanceof HTMLElement) target.focus();
    return () => {
      if (previous === null) target.removeAttribute("data-design-preview-state");
      else target.setAttribute("data-design-preview-state", previous);
    };
  }, [inspection, state]);
  return (
    <div className="px-3.5 py-3">
      <div className="flex flex-wrap gap-1">
        {states.map(({ value, label }) => (
          <button key={value} type="button" aria-pressed={state === value} onClick={() => setState(value)} className="rounded-control border border-line bg-field px-2 py-1 text-2xs font-semibold capitalize text-t2 hover:text-t1">{label}</button>
        ))}
      </div>
      {inspection.states.length > 0 ? (
        <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-2 gap-y-1 text-2xs">
          {inspection.states.map((item, index) => <span key={`${item.name}-${index}`} className="contents"><dt className="font-mono text-t3">{item.name}</dt><dd className="text-t2">{item.value}</dd></span>)}
        </dl>
      ) : <p className="mt-3 text-2xs text-t3">{emptyLabel}</p>}
    </div>
  );
}
