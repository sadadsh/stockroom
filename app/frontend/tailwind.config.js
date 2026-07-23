/**
 * Design tokens ported from docs/mockups/library-v2.html (the Components page)
 * and the design contract's 8/6 radii. Kept as the single source of truth so the
 * page matches the mockup by construction. No em dashes anywhere (owner rule).
 */
/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Every token resolves to a CSS variable defined in styles/index.css, so
        // the whole palette flips on [data-theme="light"] with no class changes.
        // The dark values (the mockup palette) are the :root defaults.
        canvas: "var(--c-canvas)",
        rail: "var(--c-rail)",
        surface: "var(--c-surface)",
        raise: "var(--c-raise)",
        raise2: "var(--c-raise2)",
        // the recessed chamber an asset render sits in (Part Canvas hero)
        stage: "var(--c-stage)",
        field: "var(--c-field)",
        line: "var(--c-line)",
        line2: "var(--c-line2)",
        // an opaque popover surface (menus/pops must not let content bleed through)
        popover: "var(--c-popover)",
        // text tiers
        t1: "var(--c-t1)",
        t2: "var(--c-t2)",
        t3: "var(--c-t3)",
        // status
        ok: "var(--c-ok)",
        warn: "var(--c-warn)",
        err: "var(--c-err)",
        // the neutral accent (primary actions, focus, active state, section ticks, links)
        acc: "var(--c-acc)",
        "acc-on": "var(--c-acc-on)",
        // the loud neutral (near-white/near-black) and its low-alpha active-surface wash
        "acc-strong": "var(--c-acc-strong)",
        "acc-soft": "var(--c-acc-soft)",
      },
      borderRadius: {
        // North-star direction (owner decision 2026-07-17): the rounder card + control.
        // Supersedes the earlier 8/6 lock; see docs/design/design-rules.md. Routed through CSS
        // variables (defaults in styles/index.css) so dev mode can nudge them live.
        card: "var(--r-card)",
        control: "var(--r-control)",
      },
      fontFamily: {
        // Work Sans (bundled offline via @fontsource-variable) is the interface
        // face; Segoe UI / system-ui only cover a load failure.
        sans: ['"Work Sans Variable"', '"Segoe UI"', "system-ui", "sans-serif"],
        // The machine-data readout face: MPN, spec values, stock, prices, pins.
        // Bundled offline; Cascadia/Consolas cover a load failure so columns still
        // align. Reserved strictly for real machine values so mono re-acquires
        // meaning (and gives tabular-figure alignment down a data grid).
        mono: [
          '"JetBrains Mono Variable"',
          '"Cascadia Mono"',
          "Consolas",
          "ui-monospace",
          "monospace",
        ],
      },
      fontSize: {
        // The mockup's compact desktop scale, routed through CSS variables (defaults in
        // styles/index.css) so dev mode can nudge each size live. The line-heights stay bundled
        // here (the type scale bundles them); only the px size is a token.
        "2xs": ["var(--fs-2xs)", { lineHeight: "1.4" }],
        xs: ["var(--fs-xs)", { lineHeight: "1.45" }],
        sm: ["var(--fs-sm)", { lineHeight: "1.45" }],
        base: ["var(--fs-base)", { lineHeight: "1.45" }],
        lg: ["var(--fs-lg)", { lineHeight: "1.35" }],
        xl: ["var(--fs-xl)", { lineHeight: "1.3" }],
        title: ["var(--fs-title)", { lineHeight: "1.12", letterSpacing: "-0.02em" }],
      },
      letterSpacing: {
        tightui: "-0.008em",
      },
      boxShadow: {
        // Monochrome elevation scale (resting card, lifted/hover, pop layer).
        card: "var(--shadow-card)",
        raise: "var(--shadow-raise)",
        pop: "var(--shadow-pop)",
        file: "var(--shadow-file)",
      },
      transitionTimingFunction: {
        // a slight overshoot so presses + hovers feel springy, not linear
        spring: "var(--ease-spring)",
      },
    },
  },
  plugins: [],
};
