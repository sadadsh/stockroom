/**
 * Design primitives ported from the mockup so the page matches by construction.
 * Interactive labels are Title Case, and there are no em dashes in any copy
 * (owner rules). Radii use the 8/6 tokens (rounded-card / rounded-control).
 */
import type { ButtonHTMLAttributes, HTMLAttributes, KeyboardEvent, ReactNode } from "react";

function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

// A raised, hairline-bordered surface: the mockup's .file / .ss / .srcbar card.
export function Card({
  className,
  children,
  ...rest
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cx(
        "rounded-card border border-line bg-raise shadow-card",
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  );
}

type ButtonVariant = "default" | "accent" | "danger" | "soft";

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
  // Default controls sit flat and lift on hover; the primary + destructive actions
  // rest raised, so a page's main action reads as the one thing standing up.
  const variants: Record<ButtonVariant, string> = {
    default:
      "border-line bg-raise text-t2 hover:bg-raise2 hover:text-t1 hover:-translate-y-px hover:shadow-card",
    accent:
      "border-transparent bg-acc text-acc-on shadow-card hover:brightness-105 hover:-translate-y-px hover:shadow-raise font-semibold",
    danger:
      "border-transparent bg-err text-white shadow-card hover:brightness-105 hover:-translate-y-px hover:shadow-raise font-semibold",
    // A raised-but-neutral action (north-star .addbtn): a subtle lifted tile, not a heavy
    // solid accent bar. Reads clean on both themes (a light overlay on the panel).
    soft:
      "border-line2 bg-raise2 text-t1 font-semibold shadow-card hover:brightness-110 hover:-translate-y-px hover:shadow-raise",
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
  className,
  "aria-label": ariaLabel,
}: {
  tabs: readonly TabItem<T>[];
  active: T;
  onSelect: (id: T) => void;
  idBase: string;
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
      className={cx("inline-flex rounded-card border border-line2 p-0.5", className)}
    >
      {tabs.map((t, i) => (
        <button
          key={t.id}
          type="button"
          role="tab"
          id={tabButtonId(idBase, t.id)}
          aria-selected={active === t.id}
          aria-controls={tabPanelId(idBase, t.id)}
          tabIndex={active === t.id ? 0 : -1}
          onClick={() => onSelect(t.id)}
          onKeyDown={(e) => onKeyDown(e, i)}
          className={cx(
            "rounded-control px-3 py-1 text-sm transition-colors",
            active === t.id ? "bg-raise2 text-t1" : "text-t3 hover:text-t2",
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
            value === opt.id ? "bg-raise2 text-t1" : "text-t3 hover:text-t2",
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
