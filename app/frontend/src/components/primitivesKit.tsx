/**
 * Design primitives for a Windows engineering tool: flat, square, opaque, bordered.
 * Interactive labels are Title Case, and there are no em dashes in any copy
 * (owner rules). Radii use the 2px tokens (rounded-card / rounded-control).
 *
 * The controls and surfaces of the kit are declared HERE. The kit's single import surface is the
 * sibling barrel `primitives.ts`, which names this module alongside the product-state vocabulary
 * (`productState.tsx`), the modal frame (`modalParts.tsx`) and the semantic text roles
 * (`typography.ts`), so no route has to know which sibling a primitive happens to be declared in
 * and there is never a second parallel kit to drift against. Keep importing `./primitives`.
 *
 * The re-exports used to sit at the top of this file, which meant the module both declared
 * components and forwarded a mixed bag of values - not a Fast Refresh boundary, so editing any
 * control here reloaded the whole page. They moved to the barrel; this module declares components
 * only.
 */
import { useState } from "react";
import type { ButtonHTMLAttributes, HTMLAttributes, KeyboardEvent, ReactNode } from "react";
import { Text } from "../lib/copy";
import {
  UI_CONTROL_LABEL,
  UI_PANEL_TITLE,
  UI_PROPERTY_LABEL,
  UI_PROPERTY_VALUE,
  UI_SECTION_TITLE,
  UI_STATUS_TEXT,
  WarnMark,
} from "./typography";

/**
 * The one focus treatment for the whole kit: a 2px neutral outline, offset by 1px.
 *
 * It is a token (`--c-focus`, a near-white on dark / near-black on light) and deliberately NOT
 * blue. A blue ring is the single most recognisable "this is a web page" signal there is, and in
 * an application whose chrome is otherwise pure grayscale it would also be the only hue on screen
 * that did not encode a state.
 */
const FOCUS_RING =
  "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 " +
  "focus-visible:outline-focus";

function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

// A quiet grouped surface. Ordinary cards separate with tone and spacing; major regions use Panel.
export function Card({
  className,
  children,
  ...rest
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cx(
        "rounded-card bg-raise",
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

// Flat, bordered controls: a 1px border over an opaque two-stop fill, hover is a colour shift, and
// a press darkens rather than shrinking. There is no transform anywhere in this table. A button
// that scales on press and lifts on hover is a web affordance; a Win32 push button stays exactly
// where it is and changes value.
//
// Module scope, not local to Button, because IconButton's compact mode reads the SAME table. It
// used to hardcode its own neutral treatment and ignore `variant` entirely, so a compact
// destructive action could not read as destructive and the two controls' tones could drift apart.
const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  default:
    "bg-control-bottom text-t1 hover:bg-control-hover active:bg-control-pressed",
  accent:
    "bg-acc text-acc-on hover:brightness-110 active:brightness-95 font-semibold",
  danger:
    "bg-err text-danger-on hover:brightness-110 active:brightness-95 font-semibold",
  // A quiet destructive TRIGGER (north-star restraint): a danger-tinted outline, not a solid
  // fill, so a page-level Remove/Delete/Clear reads as available without shouting. The loud
  // solid `danger` is reserved for the final in-modal confirm (the committed action). The err
  // token is mixed against transparent so the tint adapts to both themes; the LABEL is a word and
  // so wears the text strength `--c-err-text`, which clears 4.5:1 in both themes where the mark
  // strength `--c-err` reached only 3.98 dark. Hover is a colour shift only (flat idiom).
  "ghost-danger":
    "border border-[color-mix(in_srgb,var(--c-err)_42%,transparent)] " +
    "bg-[color-mix(in_srgb,var(--c-err)_7%,transparent)] text-err-text font-semibold " +
    "hover:border-[color-mix(in_srgb,var(--c-err)_60%,transparent)] " +
    "hover:bg-[color-mix(in_srgb,var(--c-err)_15%,transparent)]",
  // A neutral action tile, flat: a bordered fill that lightens one step on hover.
  soft: "bg-raise2 text-t1 font-semibold hover:bg-control-hover",
};

export function Button({
  variant = "default",
  small = false,
  icon,
  className,
  children,
  ...rest
}: ButtonProps) {
  // No transform, no shadow, no spring: colour is the only thing that moves. A disabled control
  // states its unavailability with the disabled TEXT TIER rather than by fading the whole button,
  // because a 50% opacity control also fades its border and stops reading as a control at all.
  const base =
    "inline-flex items-center gap-1.5 whitespace-nowrap rounded-control " +
    "transition-[color,background-color,border-color] duration-100 ease-out " +
    UI_CONTROL_LABEL +
    " disabled:cursor-not-allowed disabled:bg-control-pressed " +
    "disabled:text-t5 disabled:hover:brightness-100 " +
    FOCUS_RING;
  // The two control heights, both on the 11px control label. `small` is the toolbar step.
  const size = small ? "h-[22px] px-2 text-xs" : "h-[26px] px-2.5 text-sm";
  return (
    <button
      className={cx(base, size, BUTTON_VARIANTS[variant], className)}
      {...rest}
    >
      {icon ? <span className="flex h-3.5 w-3.5 flex-none items-center justify-center [&>svg]:h-full [&>svg]:w-full">{icon}</span> : null}
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
 * The compact form: a fixed-size glyph that states its consequence when approached.
 *
 * It is FIXED SIZE. The label used to wipe open on hover, animating a one-column grid from 0fr to
 * 1fr so the button grew to the label width. That is a lovely web interaction and it is wrong in a
 * toolbar: a control that changes width when the pointer crosses it reflows the row under the
 * pointer, so the next button moves before you reach it. The label now lives where a Windows
 * toolbar puts it, in aria-label and title, which costs no layout at all.
 *
 * Hover/focus is still tracked in state rather than with `group-hover:` utilities, because the TONE
 * has to arrive WITH the approach and prefixing a whole variant string with `hover:` would mean a
 * second copy of every tone decision. At rest the control wears no border and no fill: a
 * permanently bordered red box in the corner is louder than the dim text it replaced, and against
 * the repo own rule that a ghost-danger trigger "reads as available without shouting".
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
  // asked to press an unlabelled glyph. `active` pins the tone on: a running action should not
  // depend on a pointer still being there.
  const revealed = hovered || focused || active;
  const size = small ? "h-[22px] w-[22px]" : "h-[26px] w-[26px]";
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
        "inline-flex items-center justify-center rounded-control border " +
          "transition-[color,background-color,border-color] duration-100 ease-out " +
          "disabled:cursor-not-allowed disabled:text-t5 " +
          FOCUS_RING,
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
      <span className="flex h-3.5 w-3.5 flex-none items-center justify-center [&>svg]:h-full [&>svg]:w-full">{icon}</span>
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

/*
 * The docked panel title strip moved to `productState.tsx` as `RouteHeader`, so the 34px chrome
 * band, the route header and the product states are one kit rather than one primitive here and a
 * parallel set inside `component-workspace/`. It is re-exported from this module (see the bottom
 * of the file), so `primitives` remains the single import surface for the whole kit.
 */

/**
 * The dense metadata label used inside a property grid or a packed column.
 *
 * Now simply the `ui-property-label` role: 10px / 500 / label tier, no caps and no tracking. It
 * kept its own class string for a while because these labels land on a `span`, a `div` and a `dt`
 * depending on where they sit; the typography kit solves that generally, so this is an alias
 * pointing at the shared role rather than a second authority beside it.
 *
 * Deliberately TYPE ONLY: no background, no border, no sticky. The spec group header used to carry
 * a filled sticky bar while its siblings were bare, which is exactly the "box behind the header"
 * the owner asked to remove. Separation comes from spacing.
 */
export const EYEBROW_DENSE = UI_PROPERTY_LABEL;

export function Eyebrow({
  dense = false,
  className,
  children,
  ...rest
}: { dense?: boolean } & HTMLAttributes<HTMLDivElement>) {
  // Both steps are label roles now. The non-dense step is the section title (11px / 600), which is
  // what an eyebrow above a block of rows actually is; the dense step is the property label.
  return (
    <div
      className={cx(dense ? UI_PROPERTY_LABEL : UI_SECTION_TITLE, className)}
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

/**
 * A status. NOT a button, and no longer shaped like one.
 *
 * It used to be a filled pill at 11-12px with 10px of horizontal padding and a rounded box, which
 * is the exact shape of the Complete Part button three inches away - so the screen offered the
 * reader half a dozen equally button-shaped things, only some of which could be pressed. A status
 * is a fact about the row it sits in: it carries the `ui-status-text` role (which pins
 * `cursor: default` and strips border, fill and box-shadow so no ancestor can lend it an
 * affordance), the tone colour, and a whisper of tint for the two tones that need to be findable
 * by eye in a long list. There is no hover, no press, no focus ring and no pointer cursor,
 * because there is nothing here to activate.
 *
 * `size="sm"` remains as the inline step for dense rows; both sizes are the 10px status role, so
 * the difference is padding only.
 */
// Module scope: neither table reads anything local, so one allocation serves every Badge and the
// reference a memoised child sees stays the same one across renders.
const BADGE_TONES: Record<BadgeTone, string> = {
  // No tint on `warn`: `--c-warn` is a neutral now, so a 12% wash of it is a meaningless lighter
  // rectangle behind the word rather than a findable colour. The triangle below is what marks it.
  warn: "text-warn bg-transparent",
  err: "text-err-text bg-[color-mix(in_srgb,var(--c-err)_14%,transparent)]",
  ok: "text-ok-text bg-[color-mix(in_srgb,var(--c-ok)_12%,transparent)]",
  neutral: "text-t3 bg-transparent",
};

const BADGE_SIZES: Record<BadgeSize, string> = {
  default: "px-1.5 py-px",
  sm: "px-1 py-px",
};

export function Badge({
  tone = "warn",
  size = "default",
  className,
  children,
  ...rest
}: BadgeProps) {
  return (
    <span
      className={cx(
        "inline-flex items-center rounded-control",
        UI_STATUS_TEXT,
        BADGE_SIZES[size],
        BADGE_TONES[tone],
        className,
      )}
      {...rest}
    >
      {tone === "warn" ? <WarnMark /> : null}
      {children}
    </span>
  );
}

const DOT_TONES: Record<BadgeTone, string> = {
  ok: "bg-ok",
  warn: "bg-warn",
  err: "bg-err",
  neutral: "bg-t3",
};

// The small status mark. Warning stays a triangle because its token is deliberately neutral.
export function Dot({ tone }: { tone: BadgeTone }) {
  if (tone === "warn") {
    return (
      <span className="inline-flex h-[7px] w-[7px] flex-none items-center justify-center text-warn">
        <WarnMark className="!m-0 !h-[7px] !w-[7px]" />
      </span>
    );
  }
  return (
    <span
      className={cx("inline-block h-[7px] w-[7px] flex-none rounded-full", DOT_TONES[tone])}
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
  /**
   * The copy id for the label, when the label is COPY rather than DATA.
   *
   * Every tab strip in the app passed a bare string, so tab labels were the one class of
   * user-visible text that never reached the copy layer at all - not overridable, not
   * click-to-edit. A strip whose tabs are DATA (one tab per open component) passes none, for the
   * same reason a projected group heading does not: an override there would rename one library's
   * component in every strip that ever shows it.
   */
  copyId?: string;
}

// The stable ids that tie a tab to the panel it reveals, so the two halves of the
// ARIA tabs pattern (the tab in TabStrip, the panel in TabPanel) agree without the
// caller hand-wiring them. Module-local: both halves are declared here, so nothing outside ever
// needed to derive one of these ids itself, and an exported id builder would only invite a caller
// to hand-wire the pairing this module exists to guarantee.
const tabButtonId = (idBase: string, id: string) => `${idBase}-tab-${id}`;
const tabPanelId = (idBase: string, id: string) => `${idBase}-panel-${id}`;

// The one guided tab control for the whole app: a segmented pill row, not a set
// of loose buttons. Every tabbed workspace renders through this, so a tab reads
// and behaves identically everywhere. `compact`
// changes only the padding/type step when the strip must share a 34px dock title band.
// It is a
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
  devIdForTab,
  density = "default",
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
  // A strip whose tab ids are RUNTIME ids (one tab per open component) cannot use the
  // `<devIdBase>.tab-<id>` spelling: those ids have their own bracketed grammar and their own
  // escaping, which lives in lib/componentDevIds.ts. Supplying this replaces the per-tab id only;
  // the tablist still takes `<devIdBase>.tabs`.
  devIdForTab?: (id: T) => string;
  density?: "default" | "compact";
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
      // An ATTACHED tab row, not a floating pill group: the tabs sit directly on the border they
      // share with the panel below, which is how a desktop tab control tells you which body it
      // controls. The old form was a rounded, inset-padded capsule floating free of its content.
      className={cx("inline-flex items-end gap-px border-b border-line-dark", className)}
    >
      {tabs.map((t, i) => (
        <button
          key={t.id}
          type="button"
          role="tab"
          id={tabButtonId(idBase, t.id)}
          data-dev-id={
            devIdForTab ? devIdForTab(t.id) : devIdBase ? `${devIdBase}.tab-${t.id}` : undefined
          }
          aria-selected={active === t.id}
          aria-controls={tabPanelId(idBase, t.id)}
          tabIndex={active === t.id ? 0 : -1}
          onClick={() => onSelect(t.id)}
          onKeyDown={(e) => onKeyDown(e, i)}
          className={cx(
            "-mb-px border border-b-0 transition-colors " + FOCUS_RING,
            density === "compact" ? "px-2.5 py-0.5 text-xs" : "px-3 py-1 text-sm",
            // An UNSELECTED tab is available; only a disabled one should look unavailable. t2
            // states "not selected" without stating "not available", and selection loses nothing:
            // the active tab carries the panel's own surface, a light top bevel, medium WEIGHT and
            // the brightest tier, so four independent signals separate it rather than one contrast
            // step. The selected tab is the one whose bottom edge is OPEN into the panel below.
            // FIVE signals now, and the fifth is the one a desktop tab control actually leads with:
            // a 2px accent along the tab's top edge. `shadow-[inset]` rather than a border, so the
            // marker cannot change the tab's height and shift the strip by a pixel when selection
            // moves.
            active === t.id
              ? "border-line-dark border-t-line2 bg-surface font-medium text-t1 " +
                "shadow-[inset_0_2px_0_var(--c-selected-edge)]"
              : "border-transparent bg-control-bottom text-t2 hover:bg-control-hover hover:text-t1",
          )}
        >
          {t.copyId ? <Text id={t.copyId}>{t.label}</Text> : t.label}
        </button>
      ))}
    </div>
  );
}

export interface SegmentItem<T extends string> {
  id: T;
  label: string;
  /** The copy id for the label, when the label is COPY. See `TabItem.copyId`. */
  copyId?: string;
}

// A segmented single-choice control: the same pill row as TabStrip, but a
// choice, not a page-level tablist. It is a WAI-ARIA radiogroup (each option is
// a real `role="radio"` with `aria-checked`, a roving tabindex, and arrow / Home
// / End keys that both move focus and select, the way a radio group announces).
// Use it to switch a view or toggle a setting in place (the Library Health
// sub-switch, the density toggle); use TabStrip when each option reveals a
// whole `TabPanel`. Shaped as a Win32 button group: attached segments sharing
// one border, the checked one pressed IN rather than lit up.
export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  size = "default",
  className,
  devIdBase,
  "aria-label": ariaLabel,
}: {
  options: readonly SegmentItem<T>[];
  value: T;
  onChange: (id: T) => void;
  size?: "default" | "small";
  className?: string;
  devIdBase?: string;
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
      className={cx(
        "inline-flex divide-x divide-line-dark overflow-hidden rounded-control border border-line-dark",
        className,
      )}
    >
      {options.map((opt, i) => (
        <button
          key={opt.id}
          type="button"
          data-dev-id={devIdBase ? `${devIdBase}.${opt.id}` : undefined}
          role="radio"
          aria-checked={value === opt.id}
          tabIndex={value === opt.id ? 0 : -1}
          onClick={() => onChange(opt.id)}
          onKeyDown={(e) => onKeyDown(e, i)}
          className={cx(
            "transition-colors " + FOCUS_RING,
            pad,
            // Pressed in, not lit up: the checked segment takes the pressed control fill and the
            // primary tier, its siblings the raised fill and the secondary tier. Two signals, both
            // of them things a physical button does.
            value === opt.id
              ? "bg-control-pressed font-medium text-t1"
              : "bg-control-bottom text-t2 hover:bg-control-hover hover:text-t1",
          )}
        >
          {opt.copyId ? <Text id={opt.copyId}>{opt.label}</Text> : opt.label}
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

/**
 * The consistent heading atop a Panel or a content block: Title Case, quiet weight.
 * (The dense micro-label is Eyebrow, for sub-headings inside a Panel.)
 *
 * Two steps, and only two, and since the type collapse both are 11px / 600: the default is the
 * PANEL title (16px leading, for a title strip filling a 34px band) and `dense` is the SECTION
 * title (15px leading, for a heading sitting directly on its rows). A packed sheet and a page no
 * longer differ in SIZE, they differ in leading and in the space around them, which is what stops
 * six things on the opened-component screen from all claiming to be the most important.
 * `SectionHeader` (the heading + count + action ROW) composes this, so the type decision lives
 * once and the row decision lives once.
 */
export function SectionHeading({
  dense = false,
  as: Element = "div",
  className,
  children,
  ...rest
}: { dense?: boolean; as?: "div" | "h2" | "h3" } & HTMLAttributes<HTMLElement>) {
  return (
    <Element
      className={cx(dense ? UI_SECTION_TITLE : UI_PANEL_TITLE, className)}
      {...rest}
    >
      {children}
    </Element>
  );
}

// The one content surface for the whole app: an OPAQUE panel, a 1px border, a 2px radius, and no
// drop shadow at rest. Depth reads from the background step plus the hairline, never from a shadow
// as well. Padding is the desktop step (8-10px, not 14-16px): a docked panel packs rows, it does
// not present a card. Pass `title` for a headed panel; `actions` sits opposite the title; `inset`
// uses the recessed field well (a value that sits IN the surface, like a spec box). Build a panel
// by composing this, not by re-deriving the class string.
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
        // An attached title strip on the chrome band with a hairline under it: the panel header of
        // every Windows tool window. It used to be bare padding on the panel fill, which read as a
        // card caption rather than as chrome.
        <header className="flex items-center justify-between gap-3 border-b border-line bg-band px-2.5 py-1.5">
          {title != null ? <SectionHeading>{title}</SectionHeading> : <span />}
          {actions}
        </header>
      ) : null}
      <div className={cx(hasHeader ? "px-2.5 py-2" : "p-2.5", bodyClassName)}>
        {children}
      </div>
    </section>
  );
}

// A labelled value: one row of a property grid. The label takes the 10px label role and the value
// the 11px value role, so the two can never be mistaken for one another. Default lays them on a
// line; `stacked` puts the label above the value for the dense spec readout.
//
// `mono` sets the value in the machine-data face, and is for MACHINE text only: a file path, a raw
// identifier, a hash, a net name, a provider key. NOT for an MPN, a manufacturer name, a
// description or an ordinary spec value - setting those in mono is part of why every value on the
// opened component read as equally machine-generated. A numeric value wants `numeric`, which is
// tabular figures and right alignment without changing the face.
export function Field({
  label,
  value,
  children,
  stacked = false,
  mono = false,
  numeric = false,
  className,
}: {
  label: ReactNode;
  value?: ReactNode;
  children?: ReactNode;
  stacked?: boolean;
  mono?: boolean;
  /** Stock, prices, quantities, price breaks: tabular figures, right-aligned. */
  numeric?: boolean;
  className?: string;
}) {
  const content = children ?? value;
  const valueClass = cx(
    UI_PROPERTY_VALUE,
    mono && "font-mono",
    // Right-aligned tabular figures for the values that are COMPARED down a column: stock, prices,
    // quantities, price breaks. An ordinary property value stays left-aligned against its label,
    // because a ragged-right column of words is easier to scan than a ragged-left one.
    numeric && "ui-numeric",
  );
  if (stacked) {
    return (
      <div className={cx("py-1", className)}>
        <div className={UI_PROPERTY_LABEL}>{label}</div>
        <div className={cx("mt-px break-words", valueClass)}>{content}</div>
      </div>
    );
  }
  return (
    <div className={cx("flex items-baseline justify-between gap-4 py-1", className)}>
      <span className={cx("flex-none", UI_PROPERTY_LABEL)}>{label}</span>
      <span className={cx("min-w-0 text-right", valueClass)}>{content}</span>
    </div>
  );
}
