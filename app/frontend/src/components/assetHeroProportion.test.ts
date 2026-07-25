/**
 * The 3D hero must not be the largest thing on the sheet when it has nothing to show.
 *
 * MEASURED in the real window (2026-07-25): with no model attached, the "No 3D Model" placeholder
 * rendered ~420px tall directly above 142px Symbol and Footprint tiles, because its sizing was the
 * unconditional `min-h-[300px] flex-1`. A featureless placeholder was therefore the most prominent
 * element in the specimen column, which is the owner's "grotesquely out of proportion" complaint.
 *
 * RE-BASELINED 2026-07-25 for the composition slice, deliberately, keeping the same invariant on
 * the axis that now carries it. The specimen column became a horizontal EMBODIMENT STRIP, so all
 * three tiles share one height and the axis that makes a tile prominent is WIDTH: the hero takes
 * `flex-[1.9]` against its siblings' `flex-1`. The rule is unchanged in substance - an empty hero
 * must be a PEER, not the loudest element - so this now asserts the flex branch rather than a
 * pixel height.
 *
 * This is a source-contract gate rather than a render test because the sizing is a Tailwind class
 * chain: jsdom applies no CSS, so a rendered size assertion here would pass no matter what.
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
    expect(emptyBranch).not.toMatch(/min-h-\[300px\]/);
    // never a growth factor above 1: that is what "larger than its peers" means in the strip
    expect(emptyBranch).not.toMatch(/flex-\[[2-9]/);
    expect(emptyBranch).not.toMatch(/flex-\[1\.\d/);
  });

  it("sizes the empty hero as a PEER of the sibling tiles, not larger", () => {
    // Symbol and Footprint are `flex-1` peers in the strip; an empty hero claiming a larger share
    // would be back to making the placeholder the loudest element on the sheet.
    const sibling = /devId="detail.asset-symbol"[\s\S]*?className="([^"]*)"/.exec(source);
    expect(sibling, "could not find the symbol tile's className").toBeTruthy();
    expect(sibling![1], "the sibling tiles should be equal-share peers").toMatch(/flex-1/);

    const hero = /devId="detail.asset-hero"[\s\S]*?className=\{([\s\S]*?)\}\n/.exec(source);
    const emptyBranch = hero![1].split(":")[1] ?? "";
    expect(emptyBranch, "the empty hero has no sizing").toMatch(/flex-1/);

    // ... and the PRESENT branch really does still get the hero share, or this gate would pass by
    // making the hero small in both states, which is not the fix.
    const presentBranch = hero![1].split(":")[0] ?? "";
    expect(presentBranch).toMatch(/flex-\[1\.9\]/);
  });
});
