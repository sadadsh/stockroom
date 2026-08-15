/**
 * The utility layer over the design tokens declared in styles/index.css. Every value
 * here is a var() reference, so the whole palette flips on [data-theme="light"] with
 * no class changes, and `scripts/check-tokens.mjs` (run by `npm run build`) fails if a
 * token referenced here is missing from either theme. No em dashes anywhere (owner rule).
 */
import containerQueries from "@tailwindcss/container-queries";

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // --- Surfaces: the Windows tool-window ladder ---------------------
        app: "var(--c-app)",
        canvas: "var(--c-canvas)",
        rail: "var(--c-rail)",
        surface: "var(--c-surface)",
        raise: "var(--c-raise)",
        raise2: "var(--c-raise2)",
        section: "var(--c-section)",
        active: "var(--c-active)",
        // the recessed well an asset render sits in (Part Canvas hero)
        stage: "var(--c-stage)",
        field: "var(--c-field)",
        // an opaque popover surface (menus must not let content bleed through)
        popover: "var(--c-popover)",
        // the chrome band: panel title strips + the bottom status bar
        band: "var(--c-band)",
        // --- The technical drawing sheet, and the ink on it ----------------
        // Theme-aware: a light sheet on a light desktop, a dark one on a dark
        // desktop, so a 184px preview tile can never be the brightest region of
        // the workspace and outshout the component's own part number.
        technical: "var(--c-technical)",
        "technical-wash": "var(--c-technical-wash)",
        "technical-ink": "var(--c-technical-ink)",
        "technical-note": "var(--c-technical-note)",

        // The land pattern's layers, as fill-/stroke- utilities. A third
        // color-is-data family beside the two below: which layer a shape sits on
        // is the datum, so these carry hue in both themes and are tuned per theme
        // to stay >=3:1 on their own sheet and apart from one another.
        "layer-copper": "var(--c-layer-copper)",
        "layer-mask": "var(--c-layer-mask)",
        "layer-paste": "var(--c-layer-paste)",
        "layer-silk": "var(--c-layer-silk)",
        "layer-fab": "var(--c-layer-fab)",
        "layer-courtyard": "var(--c-layer-courtyard)",

        // --- Controls: a push button is a bevel over a two-stop fill ------
        "control-top": "var(--c-control-top)",
        "control-bottom": "var(--c-control-bottom)",
        "control-hover": "var(--c-control-hover)",
        "control-pressed": "var(--c-control-pressed)",
        // Selection and active state: a muted amber, the one hue in chrome that is
        // not a status. `selected-edge` is the bright 2px marker on a selected row or
        // the current tab; the fill alone is deliberately quiet.
        selected: "var(--c-selected)",
        "selected-hover": "var(--c-selected-hover)",
        "selected-edge": "var(--c-selected-edge)",
        // Every other row of a data grid. Structure, not stripes.
        "row-alt": "var(--c-row-alt)",

        // --- Borders: dark groove / hairline / light bevel ----------------
        "line-dark": "var(--c-line-dark)",
        line: "var(--c-line)",
        line2: "var(--c-line2)",
        edge: "var(--c-edge)",

        // --- The five text tiers, and their semantic aliases --------------
        // t1..t5 are the raw ladder; ink/copy/label/muted/dim name the ROLE.
        // `helper` is retained because it predates the vocabulary and means label.
        t1: "var(--c-t1)",
        t2: "var(--c-t2)",
        t3: "var(--c-t3)",
        t4: "var(--c-t4)",
        t5: "var(--c-t5)",
        ink: "var(--c-text-primary)",
        copy: "var(--c-text-secondary)",
        label: "var(--c-text-label)",
        muted: "var(--c-text-muted)",
        dim: "var(--c-text-disabled)",
        helper: "var(--c-text-helper)",

        // --- Status: the only hues in chrome, because state IS the datum --
        //
        // TWO STRENGTHS PER STATE, and which one to reach for is decided by WCAG, not by taste.
        // The plain token is the MARK strength: a fill, a border, a tint, a glyph, all of which
        // are non-text and are held to 3:1. The `-text` token is the same state one step louder,
        // for a WORD, which is normal text and is held to 4.5:1 - and the plain tokens do not
        // reach it. Measured against the workspace canvas and the chrome band: --c-ok is 3.78 /
        // 3.93 light and --c-err is 3.98 / 3.60 dark, all four under the bar, while --c-ok-text
        // is 4.83 / 5.01 light and 7.54 / 6.84 dark and --c-err-text is 5.06 / 5.26 light and
        // 7.48 / 6.78 dark. So a status WORD wears `text-ok-text` / `text-err-text` and a status
        // MARK keeps `bg-ok` / `border-err` / an `ok`-toned glyph.
        ok: "var(--c-ok)",
        warn: "var(--c-warn)",
        err: "var(--c-err)",
        "ok-text": "var(--c-ok-text)",
        "warn-text": "var(--c-warn-text)",
        "err-text": "var(--c-err-text)",
        "danger-on": "var(--c-danger-on)",
        scrim: "var(--c-scrim)",

        // --- Neutral accent + focus --------------------------------------
        // There is no brand hue and no blue: `acc` is the loud neutral used on a
        // primary action and a selected row, `focus` is the high-contrast neutral
        // outline, kept separate so a focus ring never reads as a selection.
        acc: "var(--c-acc)",
        "acc-on": "var(--c-acc-on)",
        "acc-strong": "var(--c-acc-strong)",
        "acc-soft": "var(--c-acc-soft)",
        focus: "var(--c-focus)",

        // --- Color-is-data families (NOT chrome) --------------------------
        // The pinout map's electrical-class hues, on the pad fill only.
        "stm-io": "var(--stm-io)",
        "stm-gpio": "var(--stm-gpio)",
        "stm-analog": "var(--stm-analog)",
        "stm-debug": "var(--stm-debug)",
        "stm-oscillator": "var(--stm-oscillator)",
        "stm-power": "var(--stm-power)",
        "stm-ground": "var(--stm-ground)",
        "stm-reset": "var(--stm-reset)",
        "stm-boot": "var(--stm-boot)",
        "stm-vcap": "var(--stm-vcap)",
        "stm-nc": "var(--stm-nc)",
        // Socket-union classification: a distinct three-value set from the pin hues.
        "stm-classify-shared": "var(--stm-classify-shared)",
        "stm-classify-divergent": "var(--stm-classify-divergent)",
        "stm-classify-partial": "var(--stm-classify-partial)",
      },
      borderRadius: {
        // Windows engineering chrome is SQUARE: 0 for a panel, band or row, 1px for a control.
        card: "var(--r-card)",
        control: "var(--r-control)",
      },
      fontFamily: {
        // The Windows 11 system UI face, then the Windows 10 face, then two faces
        // every Windows install has. Deliberately NO bundled webfont: a branded
        // interface face is the single loudest tell that a desktop tool is really
        // a web page, and it rasterises unlike every other window on the machine.
        sans: ['"Segoe UI Variable"', '"Segoe UI"', "Tahoma", "Arial", "sans-serif"],
        // Reserved for genuinely machine-oriented text: file paths, raw identifiers,
        // hashes, net names, provider keys, diagnostic payloads. NOT MPNs, vendor
        // names, descriptions, spec labels or ordinary values -- monospace only keeps
        // its meaning while it stays the mark of text a machine wrote.
        //
        // Consolas leads to match Altium, which is where this app's user works; it
        // ships with Windows, so the machine-data readout is the same face next door.
        // Geist Mono is bundled offline for a peer with no Consolas (the host serves
        // from an ephemeral local port, so a CDN font would fail outright).
        mono: [
          "Consolas",
          '"Cascadia Mono"',
          '"Geist Mono Variable"',
          "ui-monospace",
          "monospace",
        ],
      },
      fontSize: {
        // FOUR sizes, fixed, with fixed px leading. Nothing responds to the viewport:
        // a desktop application's text does not resize with its window, the window
        // resizes and shows more rows. See the scale note in styles/index.css.
        //
        // The role names below collapse onto those four steps. They are kept (rather
        // than renamed) so every existing surface inherits the collapse instead of
        // needing to be rewritten, and so `lib/classTokens.ts` keeps resolving.
        "ui-mpn": ["var(--fs-ui-mpn)", { lineHeight: "var(--lh-ui-mpn)" }],
        "ui-title": ["var(--fs-ui-title)", { lineHeight: "var(--lh-ui-title)" }],
        "ui-subtitle": ["var(--fs-ui-subtitle)", { lineHeight: "var(--lh-ui-title)" }],
        "ui-heading": ["var(--fs-ui-heading)", { lineHeight: "var(--lh-ui-title)" }],
        "ui-label": ["var(--fs-ui-label)", { lineHeight: "var(--lh-ui-body)" }],
        "ui-body": ["var(--fs-ui-body)", { lineHeight: "var(--lh-ui-body)" }],
        "ui-caption": ["var(--fs-ui-caption)", { lineHeight: "var(--lh-ui-body)" }],
        "ui-meta": ["var(--fs-ui-meta)", { lineHeight: "var(--lh-ui-meta)" }],
        // Numeric aliases, resolving to the same authority.
        "2xs": ["var(--fs-2xs)", { lineHeight: "var(--lh-ui-meta)" }],
        xs: ["var(--fs-xs)", { lineHeight: "var(--lh-ui-body)" }],
        sm: ["var(--fs-sm)", { lineHeight: "var(--lh-ui-body)" }],
        base: ["var(--fs-base)", { lineHeight: "var(--lh-ui-body)" }],
        lg: ["var(--fs-lg)", { lineHeight: "var(--lh-ui-title)" }],
        xl: ["var(--fs-xl)", { lineHeight: "var(--lh-ui-title)" }],
        title: ["var(--fs-title)", { lineHeight: "var(--lh-ui-title)" }],
      },
      fontWeight: {
        // THREE weights. 400 states, 500 marks a control, 600 identifies. There is no
        // 700 or 800 in this chrome: at 10-11px on a gray field a 700 reads as a
        // smudge, not as emphasis, and a screen where six things are bold has no
        // hierarchy at all. `bold` and heavier are deliberately REMAPPED rather than
        // removed, so the ~200 existing `font-bold` / `font-semibold` sites land
        // inside the budget without 112 files having to be edited.
        thin: "400",
        extralight: "400",
        light: "400",
        normal: "400",
        medium: "500",
        semibold: "600",
        bold: "600",
        extrabold: "600",
        black: "600",
      },
      boxShadow: {
        // A resting panel is flat (border + 1px bevel). Only a genuinely floating
        // surface casts a shadow, and it is small and tight, like a Win32 popup.
        card: "var(--shadow-card)",
        raise: "var(--shadow-raise)",
        pop: "var(--shadow-pop)",
        file: "var(--shadow-file)",
      },
      transitionDuration: {
        // MOTION IS CAPPED AT 160ms, and it is only ever spent on a STATE CHANGE - a hover colour,
        // a disclosure, a progress width - never on decoration. The scale is redefined rather than
        // extended so the longer Tailwind defaults (300 / 500 / 700 / 1000ms) are simply not
        // reachable from a class name: a 300ms fade on a control in a dense engineering panel reads
        // as lag, and the way that arrives is one call site at a time.
        0: "0ms",
        75: "75ms",
        100: "100ms",
        150: "150ms",
        160: "160ms",
        DEFAULT: "150ms",
      },
      transitionTimingFunction: {
        // Retained under its old name so existing `ease-spring` classes keep resolving,
        // but the overshoot is gone: a desktop control settles, it does not bounce.
        spring: "var(--ease-spring)",
      },
    },
  },
  // Container queries (the official Tailwind plugin, not a hand-rolled ResizeObserver): the
  // detail sheet must switch column count on the width of the PANE it is in, never the window's.
  // The rail collapses 190px -> 52px and the picker is a fixed 320px, so the same viewport can
  // leave the sheet 825px or 963px - and a media query cannot see the difference.
  plugins: [containerQueries],
};
