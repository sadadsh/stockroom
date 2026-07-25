/**
 * The 3D hero must not be the largest thing on the sheet when it has nothing to show.
 *
 * MEASURED in the real window (2026-07-25): with no model attached, the "No 3D Model" placeholder
 * rendered ~420px tall directly above 142px Symbol and Footprint tiles, because its sizing was the
 * unconditional `min-h-[300px] flex-1`. A featureless placeholder was therefore the most prominent
 * element in the specimen column, which is the owner's "grotesquely out of proportion" complaint.
 *
 * This is a source-contract gate rather than a render test because the sizing is a Tailwind class
 * chain: jsdom applies no CSS, so a rendered height assertion here would pass no matter what.
 */
import { describe, expect, it } from "vitest";

const RAW = import.meta.glob("./DetailPanel.tsx", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

const source = Object.values(RAW)[0];

describe("3D hero proportion", () => {
  it("takes the hero treatment only when a model is actually present", () => {
    const hero = /devId="detail.asset-hero"[\s\S]*?className=\{([\s\S]*?)\}\n/.exec(source);
    expect(hero, "could not find the hero tile's className").toBeTruthy();
    const cls = hero![1];
    // it must BRANCH on hasModel rather than always claiming the space
    expect(cls).toMatch(/hasModel\s*\?/);
    // and the empty branch must not keep the growth classes
    const emptyBranch = cls.split(":")[1] ?? "";
    expect(emptyBranch).not.toMatch(/flex-1/);
    expect(emptyBranch).not.toMatch(/min-h-\[300px\]/);
  });

  it("sizes the empty hero as a PEER of the sibling tiles, not larger", () => {
    // Symbol and Footprint are a fixed h-[142px]; an empty hero claiming more would be back to
    // making the placeholder the loudest element.
    const sibling = /devId="detail.asset-symbol"[\s\S]*?className="([^"]*)"/.exec(source);
    expect(sibling, "could not find the symbol tile's className").toBeTruthy();
    const siblingHeight = /h-\[(\d+)px\]/.exec(sibling![1])?.[1];
    expect(siblingHeight).toBeTruthy();

    const hero = /devId="detail.asset-hero"[\s\S]*?className=\{([\s\S]*?)\}\n/.exec(source);
    const emptyBranch = (hero![1].split(":")[1] ?? "");
    const heroEmptyHeight = /h-\[(\d+)px\]/.exec(emptyBranch)?.[1];
    expect(heroEmptyHeight, "the empty hero has no explicit height").toBeTruthy();
    expect(Number(heroEmptyHeight)).toBeLessThanOrEqual(Number(siblingHeight));
  });
});
