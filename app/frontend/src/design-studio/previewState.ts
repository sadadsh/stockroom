export type DesignPreviewState = "default" | "hover" | "focus" | "active" | "selected" | "disabled";

type DisableableElement = HTMLElement & { disabled: boolean };

function isDisableable(target: Element): target is DisableableElement {
  return target.matches("button, input, select, textarea, fieldset, optgroup, option");
}

/**
 * Apply a reversible, preview-only interaction state to a production target.
 * Disabled uses the native control contract when available and a capture guard for composite
 * controls, so the visual preview cannot accidentally activate product behavior.
 */
export function applyDesignPreviewState(
  target: Element,
  state: DesignPreviewState,
): () => void {
  const previousState = target.getAttribute("data-design-preview-state");
  const previousAriaDisabled = target.getAttribute("aria-disabled");
  const previousAriaSelected = target.getAttribute("aria-selected");
  const hadDisabledClass = target.classList.contains("design-preview-disabled");
  const previousDisabled = isDisableable(target) ? target.disabled : null;
  const suppressActivation = (event: Event) => {
    event.preventDefault();
    event.stopImmediatePropagation();
  };

  if (state === "default") target.removeAttribute("data-design-preview-state");
  else target.setAttribute("data-design-preview-state", state);

  if (state === "disabled") {
    target.setAttribute("aria-disabled", "true");
    target.classList.add("design-preview-disabled");
    if (isDisableable(target)) target.disabled = true;
    target.addEventListener("click", suppressActivation, true);
    target.addEventListener("keydown", suppressActivation, true);
  }
  if (state === "selected") target.setAttribute("aria-selected", "true");
  if (state === "focus" && target instanceof HTMLElement) target.focus();

  return () => {
    target.removeEventListener("click", suppressActivation, true);
    target.removeEventListener("keydown", suppressActivation, true);
    if (previousState === null) target.removeAttribute("data-design-preview-state");
    else target.setAttribute("data-design-preview-state", previousState);
    if (previousAriaDisabled === null) target.removeAttribute("aria-disabled");
    else target.setAttribute("aria-disabled", previousAriaDisabled);
    if (previousAriaSelected === null) target.removeAttribute("aria-selected");
    else target.setAttribute("aria-selected", previousAriaSelected);
    target.classList.toggle("design-preview-disabled", hadDisabledClass);
    if (previousDisabled !== null && isDisableable(target)) target.disabled = previousDisabled;
  };
}
