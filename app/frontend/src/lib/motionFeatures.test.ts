/**
 * The animation runtime is code-split: every animating surface renders `m.*` from "motion/react-m",
 * which carries no runtime at all, and the one <LazyMotion> in main.tsx fetches the feature bundle
 * as a separate chunk. Measured on the production build, that moved 84 kB (27 kB gzipped) out of the
 * boot chunk.
 *
 * That arrangement has one silent failure mode, and it is the reason this file exists. `m.*` renders
 * perfectly happily when the bundle it is given does not implement a prop it was passed - the prop
 * is simply inert, with no warning, no error, and no visible difference except a missing animation.
 * The toast stack sets `layout` so the remaining toasts slide up when one is dismissed from the
 * middle of the stack, and `layout` ships ONLY in domMax. Swapping the bundle down to domAnimation
 * for the smaller chunk would look like a clean win and would quietly delete that animation.
 *
 * So the gate reads the props the app actually passes to `m.*` out of the source, maps each to the
 * Motion feature that implements it, and requires the shipped bundle to carry all of them. Adding a
 * `drag` or `whileHover` to any m.* element re-checks the bundle automatically.
 *
 * Sources are read through Vite's `?raw` glob rather than node's `fs`, because the production build
 * type-checks this file too and the app carries no @types/node.
 */
import { describe, expect, it } from "vitest";
import { domAnimation } from "motion/react";
import shippedFeatures from "./motionFeatures";

const RAW = import.meta.glob("../**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

/** Prop -> the Motion feature package that implements it (motion's own featureProps table). */
const FEATURE_FOR_PROP: Record<string, string> = {
  animate: "animation",
  variants: "animation",
  exit: "exit",
  drag: "drag",
  dragControls: "drag",
  whileFocus: "focus",
  whileHover: "hover",
  onHoverStart: "hover",
  onHoverEnd: "hover",
  whileTap: "tap",
  onTap: "tap",
  onTapStart: "tap",
  onTapCancel: "tap",
  onPan: "pan",
  onPanStart: "pan",
  onPanSessionStart: "pan",
  onPanEnd: "pan",
  whileInView: "inView",
  onViewportEnter: "inView",
  onViewportLeave: "inView",
  layout: "layout",
  layoutId: "layout",
};

/**
 * Every attribute name on every `<m.something ...>` opening tag in `src`. The tag is walked
 * character by character rather than matched with a regex because attribute values legitimately
 * contain `>` (arrow functions, Tailwind child selectors), and a regex that stopped at the first
 * `>` would silently under-report - which for this gate means a false pass.
 */
function motionPropsUsed(): Map<string, string[]> {
  const found = new Map<string, string[]>();
  for (const [path, text] of Object.entries(RAW)) {
    if (path.endsWith(".test.ts") || path.endsWith(".test.tsx")) continue;
    if (!text.includes('from "motion/react-m"')) continue;
    for (const tag of openingTags(text)) {
      for (const prop of Object.keys(FEATURE_FOR_PROP)) {
        if (!new RegExp(`(^|\\s)${prop}(\\s|=|$)`).test(tag)) continue;
        const at = found.get(prop) ?? [];
        if (!at.includes(path)) at.push(path);
        found.set(prop, at);
      }
    }
  }
  return found;
}

function openingTags(text: string): string[] {
  const tags: string[] = [];
  const opener = /<m\.[A-Za-z][A-Za-z0-9]*/g;
  let match: RegExpExecArray | null;
  while ((match = opener.exec(text))) {
    let depth = 0;
    let quote = "";
    let i = match.index + match[0].length;
    for (; i < text.length; i += 1) {
      const ch = text[i];
      if (quote) {
        if (ch === quote) quote = "";
        continue;
      }
      if (ch === '"' || ch === "'" || ch === "`") quote = ch;
      else if (ch === "{") depth += 1;
      else if (ch === "}") depth -= 1;
      else if (ch === ">" && depth === 0) break;
    }
    tags.push(text.slice(match.index + match[0].length, i));
  }
  return tags;
}

describe("motion feature bundle", () => {
  it("carries every feature the app's m.* props need", () => {
    const used = motionPropsUsed();
    expect(used.size).toBeGreaterThan(0);

    const shipped = new Set(Object.keys(shippedFeatures));
    const missing = [...used.entries()]
      .filter(([prop]) => !shipped.has(FEATURE_FOR_PROP[prop]))
      .map(([prop, at]) => `${prop} (${FEATURE_FOR_PROP[prop]}) used in ${at.join(", ")}`);
    expect(missing).toEqual([]);
  });

  it("needs domMax rather than domAnimation, because the toast stack animates layout", () => {
    // Tied together deliberately: drop `layout` from the toast and the first assertion fails;
    // shrink the bundle to domAnimation and the second does. Neither can be "fixed" alone.
    const used = motionPropsUsed();
    expect(used.get("layout")).toEqual(["./toast.tsx"]);
    expect(Object.keys(shippedFeatures)).toContain("layout");
    expect(Object.keys(domAnimation)).not.toContain("layout");
  });

  it("keeps the full motion component out of the app, so the split is real", () => {
    const offenders = Object.entries(RAW)
      .filter(([path]) => !path.endsWith(".test.ts") && !path.endsWith(".test.tsx"))
      .filter(([, text]) => /import\s*\{[^}]*\bmotion\b[^}]*\}\s*from\s*"motion\/react"/.test(text))
      .map(([path]) => path);
    expect(offenders).toEqual([]);
  });

  it("loads the bundle through a dynamic import, which is what shrinks the boot chunk", () => {
    const main = Object.entries(RAW).find(([path]) => path.endsWith("/main.tsx"))?.[1] ?? "";
    expect(main).toMatch(/import\("\.\/lib\/motionFeatures"\)/);
    expect(main).toMatch(/<LazyMotion features=\{loadMotionFeatures\}>/);
  });
});
