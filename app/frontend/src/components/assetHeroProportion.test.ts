/**
 * The physical model is the hero only when it exists. Symbol and Footprint remain
 * simultaneously visible as separate supporting representations.
 *
 * This remains a source-contract gate because jsdom does not apply Tailwind
 * layout, so this protects the explicit bounded-height contract in the component.
 */
import { describe, expect, it } from "vitest";

const RAW = import.meta.glob("./DetailPanel.tsx", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

const source = Object.values(RAW)[0];

describe("representation gallery proportion", () => {
  it("makes a present model the bounded hero and an absent model a peer", () => {
    expect(source).toContain('className={hasModel ? "h-[340px]" : "h-[142px]"}');
    expect(source).not.toContain("min-h-[300px] flex-1");
  });

  it("keeps Symbol and Footprint as separate, equally sized supporting viewers", () => {
    expect(source).toContain('devId="detail.asset-symbol"');
    expect(source).toContain('devId="detail.asset-footprint"');
    expect(source.match(/className="h-\[142px\]"/g)).toHaveLength(2);
    expect(source).not.toContain("<ComponentInspectionStage");
  });
});
