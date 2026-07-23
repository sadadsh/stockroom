/**
 * Design primitives ported from the mockup so the page matches by construction.
 * Interactive labels are Title Case, and there are no em dashes in any copy
 * (owner rules). Radii use the 8/6 tokens (rounded-card / rounded-control).
 */
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
  // Flat, bordered controls (Altium): hover is a colour shift, not a lift + shadow. The press
  // scale in `base` keeps them tactile; separation comes from the border, not elevation.
  const variants: Record<ButtonVariant, string> = {
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
  return (
    <button
      className={cx(base, size, variants[variant], className)}
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
  className,
  ...rest
}: {
  icon: ReactNode;
  label: string;
  compact?: boolean;
  variant?: ButtonVariant;
  small?: boolean;
} & ButtonHTMLAttributes<HTMLButtonElement>) {
  if (!compact) {
    return (
      <Button variant={variant} small={small} icon={icon} className={className} {...rest}>
        {label}
      </Button>
    );
  }
  const size = small ? "h-[27px] px-2" : "h-[31px] px-2.5";
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={cx(
        "group inline-flex items-center gap-1.5 rounded-control border border-line bg-raise " +
          "font-medium text-t2 transition-[color,background-color,box-shadow,transform] duration-150 " +
          "ease-spring will-change-transform active:scale-[0.96] hover:bg-raise2 hover:text-t1 hover:shadow-card " +
          "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 " +
          "focus-visible:outline-acc disabled:cursor-not-allowed disabled:opacity-50",
        size,
        className,
      )}
      {...rest}
    >
      {icon}
      <span
        className={
          "max-w-0 overflow-hidden whitespace-nowrap text-xs opacity-0 transition-all duration-150 " +
          "group-hover:ml-0.5 group-hover:max-w-[10rem] group-hover:opacity-100 " +
          "group-focus-visible:ml-0.5 group-focus-visible:max-w-[10rem] group-focus-visible:opacity-100 " +
          "motion-reduce:transition-none"
        }
      >
        {label}
      </span>
    </button>
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
        "flex h-[34px] flex-none items-center justify-between gap-2 border-b border-line bg-band px-3.5",
        className,
      )}
      {...rest}
    >
      <span className="truncate text-xs font-semibold text-t2">{children}</span>
      {right != null ? (
        <span className="flex-none text-2xs tabular-nums text-t3">{right}</span>
      ) : null}
    </div>
  );
}

// A small uppercase section eyebrow: the mockup's .sec / .srcsub label.
export function Eyebrow({
  className,
  children,
  ...rest
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cx(
        "text-xs font-semibold text-t3",
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  );
}

type BadgeTone = "warn" | "err" | "ok" | "neutral";
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
            active === t.id ? "bg-acc-soft font-medium text-t1" : "text-t3 hover:text-t2",
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
} & HTMLAttributes<HTMLElement>) {
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
