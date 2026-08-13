import { useEffect, useState } from "react";

interface VisualCssControlProps {
  property: string;
  ariaLabel: string;
  value: string;
  onCommit: (value: string) => void;
}

interface RangeConfig {
  min: number;
  max: number;
  step: number;
  unit: "" | "px";
  fallback: number;
}

const RANGE_CONFIG: Record<string, RangeConfig> = {
  inset: { min: -512, max: 1024, step: 1, unit: "px", fallback: 0 },
  top: { min: -512, max: 1024, step: 1, unit: "px", fallback: 0 },
  right: { min: -512, max: 1024, step: 1, unit: "px", fallback: 0 },
  bottom: { min: -512, max: 1024, step: 1, unit: "px", fallback: 0 },
  left: { min: -512, max: 1024, step: 1, unit: "px", fallback: 0 },
  width: { min: 0, max: 1920, step: 1, unit: "px", fallback: 320 },
  height: { min: 0, max: 1200, step: 1, unit: "px", fallback: 120 },
  "min-width": { min: 0, max: 1920, step: 1, unit: "px", fallback: 0 },
  "min-height": { min: 0, max: 1200, step: 1, unit: "px", fallback: 0 },
  "max-width": { min: 0, max: 1920, step: 1, unit: "px", fallback: 1920 },
  "max-height": { min: 0, max: 1200, step: 1, unit: "px", fallback: 1200 },
  margin: { min: -256, max: 512, step: 1, unit: "px", fallback: 0 },
  "margin-top": { min: -256, max: 512, step: 1, unit: "px", fallback: 0 },
  "margin-right": { min: -256, max: 512, step: 1, unit: "px", fallback: 0 },
  "margin-bottom": { min: -256, max: 512, step: 1, unit: "px", fallback: 0 },
  "margin-left": { min: -256, max: 512, step: 1, unit: "px", fallback: 0 },
  padding: { min: 0, max: 512, step: 1, unit: "px", fallback: 0 },
  "padding-top": { min: 0, max: 512, step: 1, unit: "px", fallback: 0 },
  "padding-right": { min: 0, max: 512, step: 1, unit: "px", fallback: 0 },
  "padding-bottom": { min: 0, max: 512, step: 1, unit: "px", fallback: 0 },
  "padding-left": { min: 0, max: 512, step: 1, unit: "px", fallback: 0 },
  gap: { min: 0, max: 256, step: 1, unit: "px", fallback: 0 },
  "row-gap": { min: 0, max: 256, step: 1, unit: "px", fallback: 0 },
  "column-gap": { min: 0, max: 256, step: 1, unit: "px", fallback: 0 },
  opacity: { min: 0, max: 1, step: 0.05, unit: "", fallback: 1 },
  "border-radius": { min: 0, max: 128, step: 1, unit: "px", fallback: 0 },
  "border-width": { min: 0, max: 32, step: 1, unit: "px", fallback: 0 },
  "z-index": { min: -10, max: 200, step: 1, unit: "", fallback: 0 },
  "font-size": { min: 8, max: 96, step: 1, unit: "px", fallback: 14 },
  "line-height": { min: 0.8, max: 3, step: 0.05, unit: "", fallback: 1.5 },
  "letter-spacing": { min: -4, max: 24, step: 0.25, unit: "px", fallback: 0 },
};

const OPTIONS: Record<string, readonly string[]> = {
  display: ["block", "inline", "inline-block", "flex", "inline-flex", "grid", "none"],
  visibility: ["visible", "hidden"],
  position: ["static", "relative", "absolute", "fixed", "sticky"],
  overflow: ["visible", "hidden", "clip", "auto", "scroll"],
  "flex-direction": ["row", "row-reverse", "column", "column-reverse"],
  "flex-wrap": ["nowrap", "wrap", "wrap-reverse"],
  "justify-content": ["start", "end", "center", "space-between", "space-around", "space-evenly"],
  "align-items": ["stretch", "start", "end", "flex-start", "flex-end", "center", "baseline"],
  "align-content": ["stretch", "start", "end", "center", "space-between", "space-around"],
  "grid-template-columns": ["none", "1fr", "repeat(2, minmax(0, 1fr))", "repeat(3, minmax(0, 1fr))", "repeat(4, minmax(0, 1fr))"],
  "grid-template-rows": ["none", "1fr", "repeat(2, minmax(0, 1fr))", "repeat(3, minmax(0, 1fr))", "repeat(4, minmax(0, 1fr))"],
  "grid-auto-flow": ["row", "column", "dense", "row dense", "column dense"],
  "background-image": ["none", "linear-gradient(to right, var(--c-surface), var(--c-raise))", "linear-gradient(to bottom, var(--c-surface), var(--c-raise))"],
  "border-style": ["none", "solid", "dashed", "dotted"],
  "box-shadow": ["none", "0 2px 8px var(--c-line)", "0 8px 24px var(--c-line)"],
  transform: ["none", "rotate(-15deg)", "rotate(15deg)", "scale(0.9)", "scale(1.1)", "translateX(-8px)", "translateX(8px)", "translateY(-8px)", "translateY(8px)"],
  filter: ["none", "blur(2px)", "brightness(80%)", "brightness(120%)", "contrast(120%)", "grayscale(100%)", "saturate(150%)"],
  "font-family": ["system-ui", "sans-serif", "serif", "monospace", "ui-sans-serif", "ui-serif", "ui-monospace"],
  "font-weight": ["normal", "100", "200", "300", "400", "500", "600", "700", "800", "900", "bold"],
  "text-align": ["left", "center", "right", "start", "end"],
  "text-transform": ["none", "uppercase", "lowercase", "capitalize"],
  "white-space": ["normal", "nowrap", "pre-wrap"],
  "text-overflow": ["clip", "ellipsis"],
  "overflow-wrap": ["normal", "anywhere", "break-word"],
};

const COLOR_PROPERTIES = new Set(["color", "background-color", "border-color"]);

function finiteRangeValue(value: string, config: RangeConfig): number {
  const parsed = Number.parseFloat(value);
  if (!Number.isFinite(parsed)) return config.fallback;
  return Math.min(config.max, Math.max(config.min, parsed));
}

function colorHex(value: string): string {
  const hex = value.trim().match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i)?.[1];
  if (hex?.length === 3) return `#${[...hex].map((part) => part + part).join("")}`.toLowerCase();
  if (hex?.length === 6) return `#${hex}`.toLowerCase();
  const rgb = value.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/i);
  if (!rgb) return "#000000";
  return `#${rgb.slice(1, 4).map((part) => Math.min(255, Number(part)).toString(16).padStart(2, "0")).join("")}`;
}

function visualOptionLabel(value: string): string {
  return value.replaceAll("-", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function VisualCssControl({ property, ariaLabel, value, onCommit }: VisualCssControlProps) {
  const range = RANGE_CONFIG[property];
  const options = OPTIONS[property];
  const [rangeValue, setRangeValue] = useState(() => range ? finiteRangeValue(value, range) : 0);
  useEffect(() => {
    if (range) setRangeValue(finiteRangeValue(value, range));
  }, [range, value]);

  if (COLOR_PROPERTIES.has(property)) {
    return (
      <input
        type="color"
        aria-label={ariaLabel}
        value={colorHex(value)}
        onChange={(event) => onCommit(event.currentTarget.value)}
        className="h-7 w-full cursor-pointer rounded-control border border-line bg-field p-0.5"
      />
    );
  }
  if (options) {
    const selected = options.includes(value.trim()) ? value.trim() : options[0];
    return (
      <select
        aria-label={ariaLabel}
        value={selected}
        onChange={(event) => onCommit(event.currentTarget.value)}
        className="w-full rounded-control border border-line bg-field px-1.5 py-1 text-2xs text-t1 outline-none focus:border-acc"
      >
        {options.map((option) => <option key={option} value={option}>{visualOptionLabel(option)}</option>)}
      </select>
    );
  }
  if (!range) return null;
  const formatted = `${rangeValue}${range.unit}`;
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_42px] items-center gap-1">
      <input
        type="range"
        aria-label={ariaLabel}
        min={range.min}
        max={range.max}
        step={range.step}
        value={rangeValue}
        onChange={(event) => {
          const next = event.currentTarget.valueAsNumber;
          if (!Number.isFinite(next)) return;
          setRangeValue(next);
          onCommit(`${next}${range.unit}`);
        }}
        className="min-w-0 accent-[var(--c-acc)]"
      />
      <output className="truncate text-right font-mono text-2xs text-t2">{formatted}</output>
    </div>
  );
}
