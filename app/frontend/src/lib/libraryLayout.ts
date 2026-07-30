/**
 * Content allocation shared by the Components picker and the Search facet rail.
 *
 * The CSS expressions are the runtime contract. `resolveLibraryLayout` mirrors those exact clamps
 * so the three supported workstation widths can be regression-tested without pretending jsdom
 * performs layout.
 */
export const COMPONENT_PICKER_WIDTH = "clamp(17rem, 23vw, 23rem)";
export const SEARCH_FACET_RAIL_WIDTH = "clamp(14rem, 21vw, 20rem)";

export interface LibraryLayoutAllocation {
  viewport: number;
  componentPicker: number;
  componentWorkbench: number;
  searchFacetRail: number;
  searchResults: number;
}

function clampWidth(
  viewport: number,
  minimumRem: number,
  preferredViewportRatio: number,
  maximumRem: number,
  rootFontPx: number,
): number {
  return Math.min(
    maximumRem * rootFontPx,
    Math.max(minimumRem * rootFontPx, viewport * preferredViewportRatio),
  );
}

export function resolveLibraryLayout(
  viewport: number,
  rootFontPx = 16,
): LibraryLayoutAllocation {
  const componentPicker = clampWidth(viewport, 17, 0.23, 23, rootFontPx);
  const searchFacetRail = clampWidth(viewport, 14, 0.21, 20, rootFontPx);
  return {
    viewport,
    componentPicker,
    componentWorkbench: viewport - componentPicker,
    searchFacetRail,
    searchResults: viewport - searchFacetRail,
  };
}
