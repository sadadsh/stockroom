import { describe, expect, it } from "vitest";

// The workflow layer must never grow an EDA-specific fork. Tool differences belong
// in backend adapters; these files receive one normalized contract and render it.
const ALL_SOURCE = import.meta.glob("/src/**/*.{ts,tsx}", {
  query: "?raw",
  eager: true,
  import: "default",
}) as Record<string, string>;

const WORKFLOW_SOURCE = Object.fromEntries(
  Object.entries(ALL_SOURCE).filter(
    ([path]) =>
      (path.endsWith("/pages/ProjectsPage.tsx") ||
        (path.includes("/components/projects/") &&
          !path.endsWith("/ProjectPicker.tsx"))) &&
      !path.endsWith(".test.tsx") &&
      !path.endsWith(".test.ts"),
  ),
);

describe("Projects cross-EDA frontend contract", () => {
  it("does not branch a workflow on KiCad or Altium", () => {
    // ProjectPicker is intentionally outside this scan: showing the selected
    // project's native EDA is identity, not a workflow fork. Every workbench
    // remains under this contract and receives the same normalized API model.
    const offenders = Object.entries(WORKFLOW_SOURCE)
      .filter(([, source]) =>
        [
          /===\s*["']kicad["']/,
          /===\s*["']altium["']/,
          /switch\s*\([^)]*\.eda[^)]*\)/,
          /\?\s*["']KiCad["']\s*:/,
          /\?\s*["']Altium(?: Designer)?["']\s*:/,
        ].some((pattern) => pattern.test(source)),
      )
      .map(([path]) => path);
    expect(offenders).toEqual([]);
  });

  it("routes every daily view through one selected-project shell", () => {
    const source = Object.values(WORKFLOW_SOURCE).join("\n");
    expect(source).toContain('"overview"');
    expect(source).toContain('"bom"');
    expect(source).toContain('"build"');
    expect(source).toContain('"activity"');
    expect(source).not.toContain('tab="releases"');
    expect(source).toContain('devIdBase="projects"');
  });

  it("uses one placement stage in overview, BOM, and build", () => {
    const users = Object.entries(WORKFLOW_SOURCE)
      .filter(([, source]) => source.includes("<ProjectPlacementStage"))
      .map(([path]) => path.split("/").pop())
      .sort();
    expect(users).toEqual([
      "ProjectAssemblyWorkbench.tsx",
      "ProjectBomWorkbench.tsx",
      "ProjectDesignWorkbench.tsx",
    ]);
  });
});
