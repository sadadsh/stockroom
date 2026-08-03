/** One semantic single-choice control with a Dev Mode-selectable presentation. */
import { useId, useState, type KeyboardEvent } from "react";
import { useDevMode } from "../lib/devMode";
import type { ChoicePreset } from "../lib/behavior.overrides";

export interface ChoiceOption {
  value: string;
  label: string;
  disabled?: boolean;
}

export function AdaptiveChoice({
  devId,
  label,
  value,
  options,
  onChange,
  disabled = false,
  defaultPreset = "dropdown",
  className = "",
}: {
  devId: string;
  label: string;
  value: string;
  options: readonly ChoiceOption[];
  onChange: (value: string) => void;
  disabled?: boolean;
  defaultPreset?: ChoicePreset;
  className?: string;
}) {
  const dev = useDevMode();
  const override = dev.behaviorOverrideFor(devId);
  const preset = override?.preset ?? defaultPreset;
  const blocked = disabled || override?.disabled === true;
  const listId = `choice-${useId().replace(/:/g, "")}`;
  const [search, setSearch] = useState("");
  const [searching, setSearching] = useState(false);

  function stepSegment(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    if (options.length === 0) return;
    let next = index;
    const direction = event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : -1;
    if (event.key === "Home") next = options.findIndex((option) => !option.disabled);
    else if (event.key === "End") {
      next = options.length - 1;
      while (next >= 0 && options[next].disabled) next -= 1;
    } else if (["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp"].includes(event.key)) {
      for (let offset = 1; offset <= options.length; offset += 1) {
        const candidate = (index + direction * offset + options.length) % options.length;
        if (!options[candidate].disabled) {
          next = candidate;
          break;
        }
      }
    } else return;
    event.preventDefault();
    const option = options[next];
    if (!option) return;
    if (!blocked && !option.disabled) onChange(option.value);
    event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="radio"]')[next]?.focus();
  }

  if (preset === "segmented") {
    return (
      <div
        data-dev-id={devId}
        data-dev-control="choice"
        role="radiogroup"
        aria-label={label}
        className={`inline-flex max-w-full flex-wrap rounded-card border border-line2 p-0.5 ${className}`}
      >
        {options.map((option, index) => (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={value === option.value}
            tabIndex={value === option.value ? 0 : -1}
            disabled={blocked || option.disabled}
            onClick={() => onChange(option.value)}
            onKeyDown={(event) => stepSegment(event, index)}
            className={
              "rounded-control px-2.5 py-1 text-xs transition-colors disabled:cursor-not-allowed disabled:opacity-50 " +
              (value === option.value ? "bg-acc-soft font-medium text-t1" : "text-t2 hover:bg-raise2")
            }
          >
            {option.label}
          </button>
        ))}
      </div>
    );
  }

  if (preset === "radio") {
    return (
      <fieldset data-dev-id={devId} data-dev-control="choice" className={`flex min-w-0 flex-wrap gap-x-3 gap-y-1 ${className}`}>
        <legend className="sr-only">{label}</legend>
        {options.map((option) => (
          <label key={option.value} className="flex items-center gap-1.5 text-xs text-t2">
            <input
              type="radio"
              name={listId}
              checked={value === option.value}
              disabled={blocked || option.disabled}
              onChange={() => onChange(option.value)}
              className="accent-[var(--c-acc)]"
            />
            {option.label}
          </label>
        ))}
      </fieldset>
    );
  }

  if (preset === "searchable") {
    const selected = options.find((option) => option.value === value);
    return (
      <div data-dev-id={devId} data-dev-control="choice" className={`min-w-0 ${className}`}>
        <input
          aria-label={label}
          list={listId}
          value={searching ? search : selected?.label || ""}
          disabled={blocked}
          onFocus={() => {
            setSearching(true);
            setSearch("");
          }}
          onBlur={() => {
            setSearching(false);
            setSearch("");
          }}
          onChange={(event) => {
            const next = event.target.value;
            setSearch(next);
            const match = options.find(
              (option) => option.label.toLocaleLowerCase() === next.toLocaleLowerCase(),
            );
            if (match && !match.disabled) {
              onChange(match.value);
              setSearching(false);
              setSearch("");
            }
          }}
          placeholder={`Search ${label}`}
          className="h-8 w-full rounded-control border border-line bg-field px-2 text-xs text-t1 outline-none focus:border-acc disabled:opacity-50"
        />
        <datalist id={listId}>
          {options.filter((option) => !option.disabled).map((option) => (
            <option key={option.value} value={option.label} />
          ))}
        </datalist>
      </div>
    );
  }

  return (
    <select
      data-dev-id={devId}
      data-dev-control="choice"
      aria-label={label}
      value={value}
      disabled={blocked}
      onChange={(event) => onChange(event.target.value)}
      className={
        `min-w-0 rounded-control border border-line bg-field px-2 text-xs text-t1 outline-none ` +
        `focus:border-acc disabled:opacity-50 ${className}`
      }
    >
      {options.map((option) => (
        <option key={option.value} value={option.value} disabled={option.disabled}>
          {option.label}
        </option>
      ))}
    </select>
  );
}
