import { useEffect, useState } from "react";

interface ValueSliderProps {
  ariaLabel: string;
  exactAriaLabel?: string;
  value: number;
  min: number;
  max: number;
  step: number;
  unit?: string;
  onChange: (value: number) => void;
  className?: string;
  sliderClassName?: string;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function shown(value: number, step: number): string {
  const decimals = Math.max(0, (String(step).split(".")[1] ?? "").length);
  return decimals > 0 ? value.toFixed(decimals).replace(/\.0+$/, "") : String(value);
}

export function ValueSlider({
  ariaLabel,
  exactAriaLabel = `${ariaLabel} Exact`,
  value,
  min,
  max,
  step,
  unit = "",
  onChange,
  className = "",
  sliderClassName = "",
}: ValueSliderProps) {
  const bounded = clamp(Number.isFinite(value) ? value : min, min, max);
  const [draft, setDraft] = useState(() => shown(bounded, step));

  useEffect(() => setDraft(shown(bounded, step)), [bounded, step]);

  const commit = (raw: string) => {
    const parsed = Number.parseFloat(raw);
    if (!Number.isFinite(parsed)) {
      setDraft(shown(bounded, step));
      return;
    }
    const next = clamp(parsed, min, max);
    setDraft(shown(next, step));
    onChange(next);
  };

  return (
    <div className={`grid min-w-0 grid-cols-[minmax(3rem,1fr)_3.5rem_auto] items-center gap-1.5 ${className}`}>
      <input
        type="range"
        aria-label={ariaLabel}
        min={min}
        max={max}
        step={step}
        value={bounded}
        onChange={(event) => {
          const next = event.currentTarget.valueAsNumber;
          if (!Number.isFinite(next)) return;
          setDraft(shown(next, step));
          onChange(next);
        }}
        className={`min-w-0 accent-[var(--c-acc)] ${sliderClassName}`}
      />
      <input
        type="number"
        aria-label={exactAriaLabel}
        min={min}
        max={max}
        step={step}
        value={draft}
        onChange={(event) => setDraft(event.currentTarget.value)}
        onBlur={(event) => commit(event.currentTarget.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            commit(event.currentTarget.value);
            event.currentTarget.blur();
          }
          if (event.key === "Escape") {
            setDraft(shown(bounded, step));
            event.currentTarget.blur();
          }
        }}
        className="nospin tnum h-[22px] min-w-0 rounded-control border border-line2 bg-field px-1.5 text-right font-mono text-2xs text-t1 outline-none focus:border-focus"
      />
      <span className="min-w-3 text-2xs text-t3" aria-hidden={!unit}>{unit}</span>
    </div>
  );
}
