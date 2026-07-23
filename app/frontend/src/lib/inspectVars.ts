/**
 * The one shared resolver for "which design tokens does this element use?", consumed by both the
 * DevInspector (on hover / inspect-click) and the DevPanel (catalogue click). It composes the
 * class-only map in lib/classTokens.ts with the icon-by-element-type rule (locked decision 5):
 * --icon-stroke has NO Tailwind class (it is an SVG stroke-width via the `.ico` class), so an
 * element that IS or CONTAINS an <svg class="ico"> reports --icon-stroke on top of its
 * className-derived tokens. Keeping this in one place means classTokens stays class-only (decision 4)
 * and the Inspector and panel never fork the resolution.
 *
 * Reads class via getAttribute('class') rather than `.className` so SVG elements (whose className is
 * an SVGAnimatedString, not a plain string) resolve correctly.
 */
import { varsForClassName } from "./classTokens";

export function usedVarsForElement(el: Element): string[] {
  const vars = varsForClassName(el.getAttribute("class") ?? "");
  const usesIcon = el.matches("svg.ico") || el.querySelector("svg.ico") != null;
  if (usesIcon && !vars.includes("--icon-stroke")) vars.push("--icon-stroke");
  return vars;
}
