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
        // surfaces (the mockup layers translucent whites over a near-black canvas)
        canvas: "#0b0b0b",
        rail: "rgba(255,255,255,0.022)",
        surface: "rgba(23,23,24,0.5)",
        raise: "rgba(255,255,255,0.055)",
        raise2: "rgba(255,255,255,0.1)",
        field: "rgba(0,0,0,0.2)",
        line: "rgba(255,255,255,0.08)",
        line2: "rgba(255,255,255,0.14)",
        // text tiers
        t1: "#f4f4f4",
        t2: "rgba(244,244,244,0.66)",
        t3: "rgba(244,244,244,0.4)",
        // status
        ok: "#6cc08a",
        warn: "#e0b354",
        err: "#e8756c",
        // accent (light-on-dark pill)
        acc: "#f3f3f3",
        "acc-on": "#161616",
      },
      borderRadius: {
        // design contract: 8/6 radii (the 8px card, the 6px control)
        card: "8px",
        control: "6px",
      },
      fontFamily: {
        // DM Sans is the mockup's primary; falls back to Segoe UI (Windows) then
        // system-ui. If DM Sans is not installed the page still reads correctly.
        sans: ['"DM Sans"', '"Segoe UI"', "system-ui", "sans-serif"],
      },
      fontSize: {
        // the mockup's compact desktop scale
        "2xs": ["10.5px", { lineHeight: "1.5" }],
        xs: ["11.5px", { lineHeight: "1.5" }],
        sm: ["12.5px", { lineHeight: "1.5" }],
        base: ["13px", { lineHeight: "1.5" }],
        lg: ["15px", { lineHeight: "1.4" }],
        xl: ["16px", { lineHeight: "1.3" }],
        title: ["22px", { lineHeight: "1.12", letterSpacing: "-0.02em" }],
      },
      letterSpacing: {
        tightui: "-0.008em",
      },
      boxShadow: {
        pop: "0 18px 44px rgba(0,0,0,0.5)",
        file: "0 6px 20px rgba(0,0,0,0.16)",
      },
    },
  },
  plugins: [],
};
