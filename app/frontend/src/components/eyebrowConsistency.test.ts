/**
 * punch 14: "remove the box behind spec group headers". The root cause was never the box - it was
 * that every eyebrow was its own class string, so no two matched. Measured before the fix: ten
 * one-off strings carrying FOUR different letter-spacings (0.04 / 0.05 / 0.07 / 0.08em).
 *
 * The DetailPanel-scoped gates that lived here went with the panel itself. What remains is the one
 * gate that guards a live component: the shared dense metadata role in primitives.tsx, which is the
 * single visual authority the deleted one-off strings were replaced by.
 *
 * The source is read through Vite's `?raw` glob rather than node's `fs`, because the production
 * build type-checks this file too and the app carries no @types/node - reaching for `node:fs` here
 * kept the test suite green while turning the BUILD red.
 */
import { describe, expect, it } from "vitest";

const RAW = import.meta.glob("./primitives.tsx", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

function source(name: string): string {
  const hit = Object.entries(RAW).find(([path]) => path.endsWith(`/${name}`));
  if (!hit) throw new Error(`could not read ${name}; globbed: ${Object.keys(RAW).join(", ")}`);
  return hit[1];
}

describe("eyebrow consistency", () => {
  it("keeps the canonical dense metadata role free of decorative letter spacing", () => {
    // Dense property metadata uses the semantic type and helper-colour roles.
    // Reintroducing arbitrary tracking here would create a second visual authority.
    const spacings = new Set(
      [...source("primitives.tsx").matchAll(/tracking-\[([0-9.]+em)\]/g)].map((m) => m[1]),
    );
    expect([...spacings]).toEqual([]);
  });
});
