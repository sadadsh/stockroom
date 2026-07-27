/**
 * Design primitives ported from the mockup so the page matches by construction.
 * Interactive labels are Title Case, and there are no em dashes in any copy
 * (owner rules). Radii use the 8/6 tokens (rounded-card / rounded-control).
 */
import { useState } from "react";
import type { ButtonHTMLAttributes, HTMLAttributes, KeyboardEvent, ReactNode } from "react";

function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

// A flat, hairline-bordered surface (Altium reads through borders, not shadow): the mockup's
// .file / .ss / .srcbar card, restyled flat.
export function Card({
  className,
  children,
  ...rest
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cx(
        "rounded-card border border-line bg-raise",
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  );
}

type ButtonVariant = "default" | "accent" | "danger" | "ghost-danger" | "soft";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  small?: boolean;
  icon?: ReactNode;
}

// Flat, bordered controls (Altium): hover is a colour shift, not a lift + shadow. The press
// scale in the base string keeps them tactile; separation comes from the border, not elevation.
//
// Module scope, not local to Button, because IconButton's compact mode reads the SAME table. It
// used to hardcode its own neutral treatment and ignore `variant` entirely, so a compact
// destructive action could not read as destructive and the two controls' tones could drift apart.
const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  default:
    "border-line bg-raise text-t2 hover:bg-raise2 hover:text-t1",
  accent:
    "border-transparent bg-acc text-acc-on hover:brightness-110 font-semibold",
  danger:
    "border-transparent bg-err text-white hover:brightness-110 font-semibold",
  // A quiet destructive TRIGGER (north-star restraint): a danger-tinted outline, not a solid
  // fill, so a page-level Remove/Delete/Clear reads as available without shouting. The loud
  // solid `danger` is reserved for the final in-modal confirm (the committed action). The err
  // token is mixed against transparent so the tint adapts to both themes; text stays full err
  // (>=3:1 both themes). Hover is a colour shift only (flat idiom); 6px radius from `base`.
  "ghost-danger":
    "border-[color-mix(in_srgb,var(--c-err)_42%,transparent)] " +
    "bg-[color-mix(in_srgb,var(--c-err)_7%,transparent)] text-err font-semibold " +
    "hover:border-[color-mix(in_srgb,var(--c-err)_60%,transparent)] " +
    "hover:bg-[color-mix(in_srgb,var(--c-err)_15%,transparent)]",
  // A neutral action tile (north-star .addbtn), flat: a bordered fill that brightens on hover.
  soft:
    "border-line2 bg-raise2 text-t1 font-semibold hover:brightness-125",
};

export function Button({
  variant = "default",
  small = false,
  icon,
  className,
  children,
  ...rest
}: ButtonProps) {
  const base =
    "inline-flex items-center gap-1.5 whitespace-nowrap rounded-control border font-medium " +
    "transition-[color,background-color,border-color,box-shadow,transform] duration-150 ease-spring " +
    "will-change-transform active:scale-[0.96] disabled:active:scale-100 " +
    "focus-visible:outline focus-visible:outline-2 " +
    "focus-visible:outline-offset-2 focus-visible:outline-acc disabled:opacity-50 " +
    "disabled:cursor-not-allowed disabled:hover:translate-y-0 disabled:hover:shadow-none";
  const size = small ? "h-[27px] px-2.5 text-xs" : "h-[31px] px-3 text-sm";
  return (
    <button
      className={cx(base, size, BUTTON_VARIANTS[variant], className)}
      {...rest}
    >
      {icon}
      {children}
    </button>
  );
}

// An action button carrying an icon. `compact` renders it icon-only and reveals the label on
// hover / keyboard focus (a space-saving toolbar affordance); the label is always in the DOM
// via aria-label + title so it stays accessible when collapsed and the expand respects
// reduced-motion. Non-compact is the ordinary icon+label Button.
export function IconButton({
  icon,
  label,
  compact = false,
  variant = "default",
  small = false,
  pending = false,
  pendingLabel,
  disabled = false,
  className,
  ...rest
}: {
  icon: ReactNode;
  label: string;
  compact?: boolean;
  variant?: ButtonVariant;
  small?: boolean;
  // An action that is RUNNING says so in the control itself: the glyph becomes a spinner, the label
  // becomes `pendingLabel`, and the control is pinned open and refuses further clicks. Putting the
  // state here rather than in a modal or a toast is the point - it is the thing the user pressed.
  pending?: boolean;
  // The same verb as `label`, in the present progressive ("Deleting"), and the same verb the
  // resulting toast should use ("Deleted"). One vocabulary through the whole flow.
  pendingLabel?: string;
} & ButtonHTMLAttributes<HTMLButtonElement>) {
  const active = pending && !!pendingLabel;
  const shown = active ? pendingLabel! : label;
  if (!compact) {
    return (
      <Button
        {...rest}
        variant={variant}
        small={small}
        icon={active ? <ButtonSpinner /> : icon}
        className={className}
        aria-busy={active || undefined}
        // computed props sit AFTER the spread: with the spread last, a caller's `disabled={false}`
        // silently overwrote the pending lock and a running action stayed clickable.
        disabled={active || disabled}
      >
        {shown}
      </Button>
    );
  }
  return (
    <CompactIconButton
      {...rest}
      icon={active ? <ButtonSpinner /> : icon}
      shown={shown}
      variant={variant}
      small={small}
      active={active}
      disabled={active || disabled}
      className={className}
    />
  );
}

/**
 * The compact form: a glyph at rest that states its consequence when approached.
 *
 * Hover/focus is tracked in state rather than with `group-hover:` utilities because the TONE has to
 * arrive WITH the label. At rest the control wears no border and no tint - a permanently bordered
 * red box in the corner is louder than the dim text it replaced, and contradicts the repo's own rule
 * that a ghost-danger trigger "reads as available without shouting" (caught in a screenshot, not by
 * a test). Prefixing a whole variant string with `hover:` would have meant a second copy of every
 * tone decision, which is the duplication hoisting BUTTON_VARIANTS just removed.
 */
function CompactIconButton({
  icon,
  shown,
  variant,
  small,
  active,
  className,
  ...rest
}: {
  icon: ReactNode;
  shown: string;
  variant: ButtonVariant;
  small: boolean;
  active: boolean;
} & ButtonHTMLAttributes<HTMLButtonElement>) {
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  // Focus counts as approaching, so a keyboard user is told the consequence too instead of being
  // asked to press an unlabelled glyph. `active` pins it open: a control that collapsed halfway
  // through its own action would leave the user watching an unlabelled spinner.
  const revealed = hovered || focused || active;
  const size = small ? "h-[27px] px-2" : "h-[31px] px-2.5";
  return (
    <button
      {...rest}
      type="button"
      aria-label={shown}
      title={shown}
      aria-busy={active || undefined}
      data-revealed={revealed ? "true" : "false"}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      className={cx(
        "group inline-flex items-center gap-1.5 rounded-control border " +
          "font-medium transition-[color,background-color,border-color,box-shadow,transform] " +
          "duration-150 ease-spring will-change-transform active:scale-[0.96] " +
          "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 " +
          "focus-visible:outline-acc disabled:cursor-not-allowed disabled:opacity-50",
        revealed
          ? BUTTON_VARIANTS[variant]
          // At rest: the glyph alone. Muted for a neutral action, tinted for a destructive one, so
          // a delete still reads as a delete before you touch it - just without a box around it.
          : cx(
              "border-transparent bg-transparent",
              variant === "ghost-danger" || variant === "danger"
                ? "text-[color-mix(in_srgb,var(--c-err)_70%,transparent)]"
                : "text-t3",
            ),
        size,
        className,
      )}
    >
      {icon}
      {/*
        The reveal animates to the label's OWN width, via a one-column grid going 0fr -> 1fr.

        It used to animate `max-width` from 0 to 10rem. That is why the owner reported "delete part
        animation doesnt exist" while the reveal demonstrably worked: 10rem is 160px and the label
        is about 72px, so the growing max-width passed the text's real width at roughly 45% of the
        transition and the remaining 55% animated a box the text had already stopped filling. The
        visible motion was over in ~70ms of a 150ms transition and read as a snap, not a reveal.

        `0fr -> 1fr` is the standard way to transition to content-derived width: the whole duration
        maps onto the distance actually travelled, so the label wipes open over its own width and
        the button grows with it. No JS measurement, no magic number to drift.
      */}
      <span
        className={cx(
          "grid transition-[grid-template-columns,opacity,margin] duration-200 ease-spring " +
            "motion-reduce:transition-none",
          revealed ? "ml-0.5 grid-cols-[1fr] opacity-100" : "grid-cols-[0fr] opacity-0",
        )}
      >
        <span className="overflow-hidden whitespace-nowrap text-xs">{shown}</span>
      </span>
    </button>
  );
}

// The one in-control running indicator. Reduced motion is handled globally by the app's
// <MotionConfig reducedMotion="user"> plus this class, so a user who asked for stillness gets a
// static ring rather than a spin.
function ButtonSpinner() {
  return (
    <svg
      aria-hidden
      viewBox="0 0 16 16"
      className="h-3.5 w-3.5 flex-none animate-spin motion-reduce:animate-none"
    >
      <circle
        cx="8"
        cy="8"
        r="6"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeDasharray="28"
        strokeDashoffset="10"
      />
    </svg>
  );
}

// An Altium-style panel title strip: the thin uppercase bar that sits atop a docked pane
// (the parts list, a detail region) and, with the pane's border, gives the "docked panel"
// read. Sits on the chrome band with a bottom hairline. `right` is an optional trailing slot
// (a count, a small action). Callers pass their own `data-dev-id` via `...rest`, matching the
// convention that reusable surfaces (Card, Panel) never hardcode an id.
export function PanelTitle({
  right,
  className,
  children,
  ...rest
}: { right?: ReactNode } & HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cx(
        // NOT `justify-between`. Every call site passes a COUNT here (a number, "N of M",
        // "N active") and never a control, so flushing it to the panel's far edge only separated
        // a number from the noun it counts - measured at ~290px on the owner's 320px Components
        // panel, while the "Diodes 1" group header a hundred pixels below it reads adjacent. One
        // screen, two treatments. If this slot ever holds a real control, that control can carry
        // its own `ml-auto` rather than the header assuming every occupant wants the edge.
        "flex h-[34px] flex-none items-center gap-2 border-b border-line bg-band px-3.5",
        className,
      )}
      {...rest}
    >
      {/* min-w-0 so `truncate` still has something to shrink against now that the span sizes to
          its content instead of being stretched by justify-between. */}
      <span className="min-w-0 truncate text-xs font-semibold text-t2">{children}</span>
      {right != null ? (
        <span className="flex-none text-2xs tabular-nums text-t3">{right}</span>
      ) : null}
    </div>
  );
}

// A small uppercase section eyebrow: the mockup's .sec / .srcsub label.
/**
 * The DENSE eyebrow: the small uppercase group label used inside a property grid or a packed
 * column (SPECIFICATIONS, VOLUME PRICING, TRADE AND COMPLIANCE, CAD).
 *
 * Exported as a class string, not only as a component, because these labels land on a `span`, a
 * `div` and a `dt` depending on where they sit, and a polymorphic component would buy nothing but
 * type gymnastics. The point is that the DECISION lives in one place: DetailPanel previously carried
 * ten hand-written variants of this string with FOUR different letter-spacings, so no two eyebrows
 * in the app matched (punch 14). 0.07em is the canonical tracking - the plurality of the old
 * strings, and the right amount of air for 10px uppercase.
 *
 * Deliberately TYPE ONLY: no background, no border, no sticky. The spec group header used to carry
 * a filled sticky bar while its siblings were bare, which is exactly the "box behind the header"
 * the owner asked to remove. Separation comes from spacing.
 */
// SMALL-CAPS, not `uppercase` (owner's decision, 2026-07-26, from previews). `text-transform:
// uppercase` rewrites the characters, and UNITS ARE CASE-BEARING: a spec label reading
// "Peak Pulse Current (10/1000ms)" was rendered "(10/1000Ms)", and the same transform turns mA
// into MA and mV into MV. That is a label stating something false, not a styling preference.
//
// `font-variant: small-caps` gives the same dense capital register while leaving the actual
// characters alone, so lowercase units survive with no per-label exception list to maintain.
export const EYEBROW_DENSE =
  "text-2xs font-semibold [font-variant:small-caps] tracking-[0.07em] text-t3";

export function Eyebrow({
  dense = false,
  className,
  children,
  ...rest
}: { dense?: boolean } & HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cx(
        dense ? EYEBROW_DENSE : "text-xs font-semibold text-t3",
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  );
}

export type BadgeTone = "warn" | "err" | "ok" | "neutral";
type BadgeSize = "default" | "sm";

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone;
  size?: BadgeSize;
}

// A status pill: the mockup's .chip / .mpill / .complete. `size="sm"` is the tighter
// tag used inline in dense rows (the Files footer's tool pill), keeping the same 6px
// control radius.
export function Badge({
  tone = "warn",
  size = "default",
  className,
  children,
  ...rest
}: BadgeProps) {
  const tones: Record<BadgeTone, string> = {
    warn: "text-warn bg-[rgba(211,162,76,0.11)]",
    err: "text-err bg-[rgba(215,108,98,0.12)]",
    ok: "text-ok bg-[rgba(129,171,144,0.14)]",
    neutral: "text-t2 bg-raise2",
  };
  const sizes: Record<BadgeSize, string> = {
    default: "px-2.5 py-1 text-xs",
    sm: "px-1.5 py-0.5 text-2xs",
  };
  return (
    <span
      className={cx(
        "inline-flex items-center rounded-control font-medium",
        sizes[size],
        tones[tone],
        className,
      )}
      {...rest}
    >
      {children}
    </span>
  );
}

// The small colored status dot.
export function Dot({ tone }: { tone: BadgeTone }) {
  const tones: Record<BadgeTone, string> = {
    ok: "bg-ok",
    warn: "bg-warn",
    err: "bg-err",
    neutral: "bg-t3",
  };
  return (
    <span
      className={cx("inline-block h-[7px] w-[7px] flex-none rounded-full", tones[tone])}
    />
  );
}

// A small token-driven swatch for a color-is-data legend: a tiny rounded tile filled from a single
// CSS-variable token reference passed in (e.g. "var(--stm-power)" or "var(--stm-classify-shared)").
// It emits no color value of its own, so every hue stays in the token layer and flips on data-theme.
// `variant` optionally overlays the pinout map's non-color channels on the same swatch: "dot" marks
// a 5V-tolerant pin, "ring" marks the neutral selection accent. Shared by PinoutLegend and any
// future encoded surface (CONTEXT decision 3) instead of a swatch inlined once in components/stm.
export function LegendSwatch({
  token,
  variant = "fill",
  className,
}: {
  token: string;
  variant?: "fill" | "dot" | "ring";
  className?: string;
}) {
  return (
    <span
      className={cx(
        "relative inline-block h-3 w-3 flex-none rounded-control",
        variant === "ring" && "outline outline-2 outline-offset-1 outline-acc-strong",
        className,
      )}
      style={{ backgroundColor: token }}
    >
      {variant === "dot" ? (
        <span className="absolute left-1/2 top-1/2 h-1 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-t1" />
      ) : null}
    </span>
  );
}

export interface TabItem<T extends string> {
  id: T;
  label: string;
}

// The stable ids that tie a tab to the panel it reveals, so the two halves of the
// ARIA tabs pattern (the tab in TabStrip, the panel in TabPanel) agree without the
// caller hand-wiring them.
export const tabButtonId = (idBase: string, id: string) => `${idBase}-tab-${id}`;
export const tabPanelId = (idBase: string, id: string) => `${idBase}-panel-${id}`;

// The one guided tab control for the whole app: a segmented pill row, not a set
// of loose buttons. The Library flagship and the per-project Projects surface both
// render through this, so a tab reads and behaves identically everywhere. It is a
// full WAI-ARIA tablist: each option is a real `role="tab"` with `aria-selected`
// and `aria-controls` pointing at its `TabPanel`; a roving tabindex plus arrow /
// Home / End keys move between tabs the way a screen reader announces the tablist
// implies. The active pill is the raised `bg-raise2` fill.
export function TabStrip<T extends string>({
  tabs,
  active,
  onSelect,
  idBase,
  devIdBase,
  className,
  "aria-label": ariaLabel,
}: {
  tabs: readonly TabItem<T>[];
  active: T;
  onSelect: (id: T) => void;
  idBase: string;
  // When set, the tablist and each tab carry a derived `data-dev-id`
  // (`<devIdBase>.tabs` on the container, `<devIdBase>.tab-<id>` per tab) so
  // templated tab strips get one stable dev-mode id per tab. Omit it and no
  // `data-dev-id` is emitted (zero change for other callers).
  devIdBase?: string;
  className?: string;
  "aria-label"?: string;
}) {
  function onKeyDown(e: KeyboardEvent<HTMLButtonElement>, index: number) {
    const last = tabs.length - 1;
    let next = -1;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") next = index === last ? 0 : index + 1;
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp") next = index === 0 ? last : index - 1;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = last;
    if (next < 0) return;
    e.preventDefault();
    onSelect(tabs[next].id);
    // Move focus to follow the selection, so keyboard and pointer land in the same place.
    const buttons = e.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>(
      '[role="tab"]',
    );
    buttons?.[next]?.focus();
  }

  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      data-dev-id={devIdBase ? `${devIdBase}.tabs` : undefined}
      className={cx("inline-flex rounded-card border border-line2 p-0.5", className)}
    >
      {tabs.map((t, i) => (
        <button
          key={t.id}
          type="button"
          role="tab"
          id={tabButtonId(idBase, t.id)}
          data-dev-id={devIdBase ? `${devIdBase}.tab-${t.id}` : undefined}
          aria-selected={active === t.id}
          aria-controls={tabPanelId(idBase, t.id)}
          tabIndex={active === t.id ? 0 : -1}
          onClick={() => onSelect(t.id)}
          onKeyDown={(e) => onKeyDown(e, i)}
          className={cx(
            "rounded-control px-3 py-1 text-sm transition-colors",
            // An UNSELECTED tab is available; only a disabled one should look unavailable. At t3
            // (40% alpha dark / 46% light - the dimmest tier, the one carrying genuinely secondary
            // text) `Handoff`, `Enrich` and `Timeline` read as greyed out beside the active chip,
            // so the sheet looked like it had one tab and three dead labels. t2 states "not
            // selected" without stating "not available", and selection loses nothing: the active
            // tab still carries a soft accent FILL, medium WEIGHT and the brightest tier, so three
            // independent signals separate it rather than one contrast step.
            active === t.id ? "bg-acc-soft font-medium text-t1" : "text-t2 hover:text-t1",
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export interface SegmentItem<T extends string> {
  id: T;
  label: string;
}

// A segmented single-choice control: the same pill row as TabStrip, but a
// choice, not a page-level tablist. It is a WAI-ARIA radiogroup (each option is
// a real `role="radio"` with `aria-checked`, a roving tabindex, and arrow / Home
// / End keys that both move focus and select, the way a radio group announces).
// Use it to switch a view or toggle a setting in place (the Library Health
// sub-switch, the density toggle); use TabStrip when each option reveals a
// whole `TabPanel`. The checked pill is the raised `bg-raise2` fill.
export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  size = "default",
  className,
  "aria-label": ariaLabel,
}: {
  options: readonly SegmentItem<T>[];
  value: T;
  onChange: (id: T) => void;
  size?: "default" | "small";
  className?: string;
  "aria-label": string;
}) {
  function onKeyDown(e: KeyboardEvent<HTMLButtonElement>, index: number) {
    const last = options.length - 1;
    let next = -1;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") next = index === last ? 0 : index + 1;
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp") next = index === 0 ? last : index - 1;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = last;
    if (next < 0) return;
    e.preventDefault();
    onChange(options[next].id);
    // Follow the selection with focus so keyboard and pointer land together.
    const buttons = e.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>(
      '[role="radio"]',
    );
    buttons?.[next]?.focus();
  }

  const pad = size === "small" ? "px-2.5 py-0.5 text-xs" : "px-3 py-1 text-sm";
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      className={cx("inline-flex rounded-card border border-line2 p-0.5", className)}
    >
      {options.map((opt, i) => (
        <button
          key={opt.id}
          type="button"
          role="radio"
          aria-checked={value === opt.id}
          tabIndex={value === opt.id ? 0 : -1}
          onClick={() => onChange(opt.id)}
          onKeyDown={(e) => onKeyDown(e, i)}
          className={cx(
            "rounded-control transition-colors",
            pad,
            value === opt.id ? "bg-acc-soft font-medium text-t1" : "text-t3 hover:text-t2",
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

// The content half of the ARIA tabs pattern: a `role="tabpanel"` region labelled by
// its tab, so activating a tab has a programmatic target instead of leaving the tab
// role dangling. `tab` is the active tab id; the ids are derived the same way as the
// TabStrip button's, so the two always line up.
export function TabPanel({
  idBase,
  tab,
  className,
  children,
}: {
  idBase: string;
  tab: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      role="tabpanel"
      id={tabPanelId(idBase, tab)}
      aria-labelledby={tabButtonId(idBase, tab)}
      className={className}
    >
      {children}
    </div>
  );
}

// The consistent heading atop a Panel or a content block: Title Case, quiet weight.
// (The uppercase micro-label is Eyebrow, for dense sub-headings inside a Panel.)
export function SectionHeading({
  className,
  children,
  ...rest
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cx("text-sm font-semibold text-t1", className)} {...rest}>
      {children}
    </div>
  );
}

// The one content surface for the whole app. Depth reads from a single background step
// plus a hairline, never a background AND a border AND a drop shadow at once (the design
// contract: elevation through background, not stacked outlines). Pass `title` for a
// headed card; `actions` sits opposite the title; `inset` uses the recessed field well
// (a value that sits IN the surface, like a spec box). Build a card by composing this,
// not by re-deriving the class string.
export function Panel({
  title,
  actions,
  inset = false,
  className,
  bodyClassName,
  children,
  ...rest
}: {
  title?: ReactNode;
  actions?: ReactNode;
  inset?: boolean;
  bodyClassName?: string;
  // `title` is intersected away by HTMLAttributes' own string `title` (the tooltip attribute),
  // which made the documented ReactNode heading unusable: the first caller to pass an element
  // got "Element is not assignable to ReactPortal & string". Omitted so the panel's heading prop
  // is the one that wins; a real tooltip belongs on the element inside, not on the section.
} & Omit<HTMLAttributes<HTMLElement>, "title">) {
  const hasHeader = title != null || actions != null;
  return (
    <section
      className={cx(
        "rounded-card border border-line",
        inset ? "bg-field" : "bg-surface",
        className,
      )}
      {...rest}
    >
      {hasHeader ? (
        <header className="flex items-center justify-between gap-3 px-4 pb-2.5 pt-3.5">
          {title != null ? <SectionHeading>{title}</SectionHeading> : <span />}
          {actions}
        </header>
      ) : null}
      <div className={cx(hasHeader ? "px-4 pb-3.5" : "p-4", bodyClassName)}>
        {children}
      </div>
    </section>
  );
}

// A labelled value: one row of a data card's definition list. Default lays label and
// value on a line (label left, value right); `stacked` puts the label above the value
// for the dense spec readout; `mono` sets the value in the machine-data face so numbers
// align. Pass `value` for a plain value or `children` for rich content.
export function Field({
  label,
  value,
  children,
  stacked = false,
  mono = false,
  className,
}: {
  label: ReactNode;
  value?: ReactNode;
  children?: ReactNode;
  stacked?: boolean;
  mono?: boolean;
  className?: string;
}) {
  const content = children ?? value;
  if (stacked) {
    return (
      <div className={cx("py-1.5", className)}>
        <div className="text-2xs text-t2">{label}</div>
        <div className={cx("mt-0.5 break-words text-sm text-t1", mono && "font-mono tnum")}>
          {content}
        </div>
      </div>
    );
  }
  return (
    <div className={cx("flex items-baseline justify-between gap-4 py-1.5", className)}>
      <span className="flex-none text-sm text-t2">{label}</span>
      <span className={cx("min-w-0 text-right text-sm text-t1", mono && "font-mono tnum")}>
        {content}
      </span>
    </div>
  );
}
