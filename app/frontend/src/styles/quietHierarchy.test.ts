// @ts-expect-error Vitest executes this contract in Node; browser bundles exclude Node types.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const read = (path: string) => readFileSync(path, "utf8");

describe("quiet dense-screen hierarchy", () => {
  it("keeps compact specification rows without boxing labels into cells", () => {
    const source = read("src/components/component-workspace/SpecificationRow.tsx");
    expect(source).not.toContain("border-r border-line/50 pr-2");
    expect(source).not.toContain('className="border-b border-line/60 last:border-b-0 even:bg-row-alt"');
  });

  it("keeps offer comparison columns aligned without a vertical grid", () => {
    const source = read("src/components/component-workspace/OffersSection.tsx");
    expect(source).not.toContain("[&>td]:border-r");
    expect(source).not.toContain("whitespace-nowrap border-r border-line/50");
  });

  it("uses spacing instead of a separator after every settings and sourcing value", () => {
    const settings = read("src/pages/SettingsPage.tsx");
    const sourcing = read("src/components/component-workspace/SourcingParts.tsx");
    expect(settings).not.toContain(
      'className="flex items-center justify-between gap-4 border-b border-line py-2 last:border-b-0"',
    );
    expect(sourcing).not.toContain(
      'className="flex min-h-[24px] items-baseline gap-2 border-b border-line/60 px-2 py-1 last:border-b-0"',
    );
  });

  it("does not box every Design Studio subsection", () => {
    const sources = [
      read("src/components/design-mode/ScenarioCatalog.tsx"),
      read("src/components/design-mode/InspectorPanel.tsx"),
      read("src/components/design-mode/LayersHierarchyPanel.tsx"),
      read("src/components/design-mode/inspectors/BoxInspector.tsx"),
      read("src/components/design-mode/inspectors/CadPresentationInspector.tsx"),
      read("src/components/design-mode/inspectors/StatesInspector.tsx"),
    ].join("\n");
    expect(sources).not.toContain('className="border-b border-line"');
    expect(sources).not.toContain('className="border-t border-line');
  });
});
