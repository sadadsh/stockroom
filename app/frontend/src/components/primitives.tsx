/**
 * Design primitives ported from the mockup so the page matches by construction.
 * Interactive labels are Title Case, and there are no em dashes in any copy
 * (owner rules). Radii use the 8/6 tokens (rounded-card / rounded-control).
 */
import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";

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
        "rounded-card border border-line bg-raise",
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  );
}

type ButtonVariant = "default" | "accent" | "danger";

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
    "transition-colors focus-visible:outline focus-visible:outline-2 " +
    "focus-visible:outline-offset-2 focus-visible:outline-acc disabled:opacity-50 " +
    "disabled:cursor-not-allowed";
  const size = small ? "h-[27px] px-2.5 text-xs" : "h-[31px] px-3 text-sm";
  const variants: Record<ButtonVariant, string> = {
    default:
      "border-line bg-raise text-t2 hover:bg-raise2 hover:text-t1",
    accent:
      "border-transparent bg-acc text-acc-on hover:brightness-95 font-semibold",
    danger:
      "border-transparent bg-err text-white hover:brightness-95 font-semibold",
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

// A small uppercase section eyebrow: the mockup's .sec / .srcsub label.
export function Eyebrow({
  className,
  children,
  ...rest
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cx(
        "text-[11px] font-semibold text-t3",
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  );
}

type BadgeTone = "warn" | "err" | "ok" | "neutral";

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone;
}

// A status pill: the mockup's .chip / .mpill / .complete.
export function Badge({
  tone = "warn",
  className,
  children,
  ...rest
}: BadgeProps) {
  const tones: Record<BadgeTone, string> = {
    warn: "text-warn bg-[rgba(211,162,76,0.11)]",
    err: "text-err bg-[rgba(215,108,98,0.12)]",
    ok: "text-ok bg-[rgba(108,192,138,0.14)]",
    neutral: "text-t2 bg-raise2",
  };
  return (
    <span
      className={cx(
        "inline-flex items-center rounded-control px-2.5 py-1 text-xs font-medium",
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
