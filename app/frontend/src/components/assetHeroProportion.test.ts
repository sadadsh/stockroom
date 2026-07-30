/**
 * The unified inspection stage must keep empty or unavailable projections from
 * becoming larger than real geometry.
 *
 * This remains a source-contract gate because jsdom does not apply Tailwind
 * layout. The current architecture gives Symbol, Footprint, 3D, and the empty
 * state one bounded stage instead of differently sized asset cards.
 */
import { describe, expect, it } from "vitest";

const RAW = import.meta.glob("./ComponentInspectionStage.tsx", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

const source = Object.values(RAW)[0];

describe("inspection stage proportion", () => {
  it("uses one bounded stage for every projection and the empty state", () => {
    expect(source).toContain("h-[clamp(340px,54vh,560px)]");
    expect(source).toContain('data-testid="inspection-stage"');
    expect(source).toContain("<Centered>No visual representations are linked.</Centered>");
    expect(source).not.toContain("min-h-[300px] flex-1");
  });

  it("expands the same mounted instrument instead of creating a second hero", () => {
    expect(source).toContain("Keep the same stage element and projection children mounted");
    expect(source).toContain('? "fixed inset-3 z-[110] border-line2 shadow-pop"');
    expect(source).toContain(': "h-full w-full border-line"');
    expect(source).not.toContain("AssetTile");
  });
});
