import {
  COMPONENT_PICKER_WIDTH,
  resolveLibraryLayout,
  SEARCH_FACET_RAIL_WIDTH,
} from "./libraryLayout";

describe("Library responsive content allocation", () => {
  it.each([
    [1024, 272, 224],
    [1384, 318.32, 290.64],
    [1600, 368, 320],
  ])(
    "keeps identity/evidence work dominant at %i CSS pixels",
    (viewport, picker, facets) => {
      const layout = resolveLibraryLayout(viewport);
      expect(layout.componentPicker).toBeCloseTo(picker);
      expect(layout.searchFacetRail).toBeCloseTo(facets);
      expect(layout.componentWorkbench).toBeGreaterThan(layout.componentPicker);
      expect(layout.searchResults).toBeGreaterThan(layout.searchFacetRail);
    },
  );

  it("exports the same clamp expressions consumed by the live layouts", () => {
    expect(COMPONENT_PICKER_WIDTH).toBe("clamp(17rem, 23vw, 23rem)");
    expect(SEARCH_FACET_RAIL_WIDTH).toBe("clamp(14rem, 21vw, 20rem)");
  });
});
