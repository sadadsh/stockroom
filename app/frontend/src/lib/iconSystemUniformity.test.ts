import { describe, expect, it } from "vitest";

// Interface glyphs in this migration must remain on the canonical Icon/iconRegistry path. Technical
// diagrams, CAD drawings, maps, and the shared loading spinner are deliberately outside this list.
const MIGRATED_INTERFACE_FILES = [
  "/src/components/CaptureStatusPill.tsx",
  "/src/components/ProductPhoto.tsx",
  "/src/components/Finder.tsx",
  "/src/components/HandoffBand.tsx",
  "/src/components/RescanSection.tsx",
  "/src/components/component-workspace/AssetOptions.tsx",
  "/src/components/component-workspace/ProviderBrowserFrame.tsx",
  "/src/components/component-workspace/DatasheetViewer.tsx",
  "/src/components/component-workspace/SpecificationRow.tsx",
  "/src/components/component-workspace/ProviderList.tsx",
  "/src/components/stm/FamilyPicker.tsx",
  "/src/components/stm/BenchStepper.tsx",
  "/src/components/stm/CompatibilityWorkbench.tsx",
  "/src/lib/toast.tsx",
] as const;

const RAW = import.meta.glob("/src/**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

describe("canonical product icon adoption", () => {
  for (const file of MIGRATED_INTERFACE_FILES) {
    it(`${file} does not reintroduce raw interface SVG or font control glyphs`, () => {
      const contents = RAW[file];
      expect(contents, `${file} was not included by the source glob`).toBeTypeOf("string");
      expect(contents, `${file} contains a raw svg`).not.toContain("<svg");
      expect(contents, `${file} contains a font-dependent control glyph`).not.toMatch(
        /[←↻×✓]/u,
      );
    });
  }
});
