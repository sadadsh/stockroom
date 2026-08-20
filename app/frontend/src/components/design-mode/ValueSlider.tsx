import { useCallback, useEffect, useRef, useState } from "react";
import {
  DEV_MODE_HISTORY_GESTURE_END_EVENT,
  DEV_MODE_HISTORY_GESTURE_START_EVENT,
} from "../../lib/devModeHistory";

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
  disabled?: boolean;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function shown(value: number, step: number): string {
  const decimals = Math.max(0, (String(step).split(".")[1] ?? "").length);
  return decimals > 0 ? value.toFixed(decimals).replace(/\.0+$/, "") : String(value);
}

function beginHistoryGesture(): void {
  window.dispatchEvent(new Event(DEV_MODE_HISTORY_GESTURE_START_EVENT));
}

function endHistoryGesture(): void {
  window.dispatchEvent(new Event(DEV_MODE_HISTORY_GESTURE_END_EVENT));
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
  disabled = false,
}: ValueSliderProps) {
  const bounded = clamp(Number.isFinite(value) ? value : min, min, max);
  const [draft, setDraft] = useState(() => shown(bounded, step));
  const gestureRef = useRef<{ kind: "pointer" | "keyboard" | "exact"; pointerId?: number } | null>(null);

  const beginGesture = useCallback((kind: "pointer" | "keyboard" | "exact", pointerId?: number) => {
    if (gestureRef.current) return;
    gestureRef.current = { kind, pointerId };
    beginHistoryGesture();
  }, []);
  const endGesture = useCallback((kind?: "pointer" | "keyboard" | "exact", pointerId?: number) => {
    const active = gestureRef.current;
    if (!active || (kind && active.kind !== kind)) return;
    if (pointerId !== undefined && active.pointerId !== undefined && pointerId !== active.pointerId) return;
    gestureRef.current = null;
    endHistoryGesture();
  }, []);

  useEffect(() => {
    const endPointer = (event: PointerEvent) => endGesture("pointer", event.pointerId);
    const endAny = () => endGesture();
    window.addEventListener("pointerup", endPointer);
    window.addEventListener("pointercancel", endPointer);
    window.addEventListener("blur", endAny);
    return () => {
      window.removeEventListener("pointerup", endPointer);
      window.removeEventListener("pointercancel", endPointer);
      window.removeEventListener("blur", endAny);
      endGesture();
    };
  }, [endGesture]);

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
        disabled={disabled}
        onPointerDown={(event) => {
          beginGesture("pointer", event.pointerId);
          try {
            event.currentTarget.setPointerCapture?.(event.pointerId);
          } catch {
            // Window listeners remain the release fence when native capture is unavailable.
          }
        }}
        onPointerUp={(event) => endGesture("pointer", event.pointerId)}
        onPointerCancel={(event) => endGesture("pointer", event.pointerId)}
        onLostPointerCapture={(event) => endGesture("pointer", event.pointerId)}
        onKeyDown={(event) => {
          if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End"].includes(event.key)) {
            beginGesture("keyboard");
          }
        }}
        onKeyUp={(event) => {
          if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End"].includes(event.key)) {
            endGesture("keyboard");
          }
        }}
        onBlur={() => endGesture("keyboard")}
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
        disabled={disabled}
        onFocus={() => beginGesture("exact")}
        onChange={(event) => {
          const raw = event.currentTarget.value;
          setDraft(raw);
          const parsed = Number.parseFloat(raw);
          if (Number.isFinite(parsed)) onChange(clamp(parsed, min, max));
        }}
        onBlur={(event) => {
          commit(event.currentTarget.value);
          endGesture("exact");
        }}
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
