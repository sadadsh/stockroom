/**
 * The visibility panel: one icon button per preview, and every "what is drawn" switch behind it.
 *
 * WHAT THIS REPLACED. The CAD column carried its layer switches as always-visible outlined pills,
 * three under the symbol and ten under the land pattern, wrapped across three or four rows in a
 * ~290px column. Counted on the running application that was fourteen bordered controls above the
 * first piece of evidence, and the owner read the column as noise rather than as three assets. The
 * switches were not the problem - each one is a real property of a real file - the problem is that
 * a switch a person sets once per session was drawn at the same weight as the drawing it acts on.
 *
 * So they move behind ONE 20px button per preview, and the panel is a plain checkbox list. Three
 * consequences are deliberate:
 *
 *   * a checkbox states its own state. `aria-pressed` on a pill has to be decoded from a fill; a
 *     checkbox is checked or it is not, and a screen reader says which without being taught.
 *   * a disabled layer keeps its REASON. "This footprint draws nothing on that layer" was already
 *     the rule and stays it - a layer that can turn nothing on is listed, disabled and explained,
 *     rather than hidden (which answers "why is silkscreen missing" with an absence).
 *   * the panel owns no scroll. The workspace has exactly three scroll owners, one per column, and
 *     a fourth inside a popover would swallow the column's wheel. The list is short enough to
 *     stand at its natural height; it overlays what is beneath it, the way a popover does.
 *
 * Escape closes and returns focus to the button; a pointer press anywhere else closes without
 * stealing focus. Both are this component's contract rather than the caller's, so no preview can
 * ship with one of the two missing.
 */
import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { Text } from "../../lib/copy";

/** One switch in the panel: a real property of the file, named, with its state and its reason. */
export interface AssetOption {
  /** Stable key within one panel. */
  id: string;
  /** The catalogued dev id this row emits, so an override can name this one switch. */
  devId: string;
  copyId: string;
  label: string;
  on: boolean;
  toggle: () => void;
  /** Non-empty when the switch cannot operate. Stated in words, never left silent. */
  disabledReason?: string;
}

/**
 * The button, and the panel it opens.
 *
 * `groupLabel` names the set for a screen reader ("Symbol visibility"), which is what makes a bare
 * list of checkboxes legible without the button that opened it being read again.
 */
export function AssetOptionsButton({
  devId,
  buttonLabel,
  groupLabel,
  options,
  emptyReason = "",
}: {
  devId: string;
  /** The complete action name. An icon-only control has to carry one. */
  buttonLabel: string;
  groupLabel: string;
  options: readonly AssetOption[];
  /** Why there is nothing to switch, when the file could not be read at all. */
  emptyReason?: string;
}) {
  const [open, setOpen] = useState(false);
  const anchorRef = useRef<HTMLSpanElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const panelId = useId();

  const close = useCallback((restoreFocus: boolean) => {
    setOpen(false);
    if (restoreFocus) {
      anchorRef.current?.querySelector<HTMLButtonElement>("button[aria-expanded]")?.focus();
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      // Stopped here so one press closes one surface: the workspace modal above this listens for
      // Escape too, and a panel that let the press through would close the whole component.
      event.stopPropagation();
      close(true);
    };
    const onPointer = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (!target) return;
      if (panelRef.current?.contains(target) || anchorRef.current?.contains(target)) return;
      close(false);
    };
    document.addEventListener("keydown", onKey, true);
    document.addEventListener("pointerdown", onPointer, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      document.removeEventListener("pointerdown", onPointer, true);
    };
  }, [close, open]);

  // Focus lands on the first switch that can operate, so the panel is usable from the keyboard
  // without tabbing past the ones that are disabled and explained.
  useEffect(() => {
    if (!open) return;
    panelRef.current?.querySelector<HTMLInputElement>("input:not([disabled])")?.focus();
  }, [open]);

  return (
    <span ref={anchorRef} className="relative inline-flex">
      <button
        type="button"
        data-dev-id={devId}
        aria-label={buttonLabel}
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        title={buttonLabel}
        onClick={() => setOpen((current) => !current)}
        className={
          "flex h-[20px] w-[20px] items-center justify-center rounded-control " +
          "hover:bg-control-hover hover:text-t1 focus-visible:outline focus-visible:outline-2 " +
          "focus-visible:outline-offset-1 focus-visible:outline-focus " +
          (open ? "bg-selected text-t1" : "text-t3")
        }
      >
        <VisibilityGlyph />
      </button>
      {open ? (
        <div
          ref={panelRef}
          id={panelId}
          role="group"
          aria-label={groupLabel}
          data-dev-id="component-browser.asset-options-panel"
          // A floating surface, so it is one of the few places a small shadow is allowed. Opaque,
          // square-ish, and NO overflow of its own: see the scroll-owner note in the header.
          className={
            "absolute left-0 top-full z-30 mt-1 min-w-[11rem] rounded-card border " +
            "border-line-dark bg-raise py-1 shadow-card"
          }
        >
          {options.length === 0 ? (
            <p className="ui-component-metadata px-2 py-1">{emptyReason}</p>
          ) : (
            options.map((option) => <OptionRow key={option.id} option={option} />)
          )}
        </div>
      ) : null}
    </span>
  );
}

/**
 * One checkbox row.
 *
 * The reason a disabled row cannot operate is BOTH its tooltip and a line under its label, because
 * a tooltip is not reachable from the keyboard and a reason nobody can read is not a reason.
 */
function OptionRow({ option }: { option: AssetOption }) {
  const disabled = (option.disabledReason ?? "") !== "";
  return (
    <label
      data-dev-id={option.devId}
      data-asset-option={option.id}
      title={option.disabledReason || undefined}
      className={
        "flex min-h-[22px] items-baseline gap-2 px-2 py-0.5 " +
        (disabled ? "cursor-not-allowed" : "cursor-pointer hover:bg-control-hover")
      }
    >
      <input
        type="checkbox"
        checked={option.on}
        disabled={disabled}
        onChange={option.toggle}
        className={
          // The selection accent, which is what a checked box IS. The focus ring stays the neutral
          // high-contrast outline: an amber ring and an amber tick would be one signal, not two.
          "mt-0.5 h-3 w-3 flex-none accent-[var(--c-selected-edge)] focus-visible:outline " +
          "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-focus"
        }
      />
      <span className="min-w-0 flex-1">
        <span className={"ui-menu-label block " + (disabled ? "ui-disabled" : "")}>
          <Text id={option.copyId}>{option.label}</Text>
        </span>
        {disabled ? (
          <span className="ui-component-metadata block break-words">{option.disabledReason}</span>
        ) : null}
      </span>
    </label>
  );
}

/** An eye: what is drawn and what is not. Inline, at the 14px this strip is drawn at. */
function VisibilityGlyph() {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden
      className="h-3.5 w-3.5"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7Z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

/**
 * The measuring tool, as an icon on the drawing's own strip rather than a switch in the panel.
 *
 * It is not a visibility option: it changes what a CLICK on the canvas does, and a person turns it
 * on for one measurement and off again. Fit needs no control at all - a double-click and the `0` /
 * `F` keys already frame the drawing, and the canvas says so in its accessible name.
 */
export function MeasureButton({
  label,
  pressed,
  onToggle,
  disabledReason = "",
}: {
  label: string;
  pressed: boolean;
  onToggle: () => void;
  disabledReason?: string;
}) {
  return (
    <button
      type="button"
      data-dev-id="component-browser.asset-measure"
      aria-label={label}
      aria-pressed={pressed}
      disabled={disabledReason !== ""}
      title={disabledReason || label}
      onClick={onToggle}
      className={
        "flex h-[20px] w-[20px] items-center justify-center rounded-control " +
        "hover:bg-control-hover hover:text-t1 disabled:opacity-50 disabled:hover:bg-transparent " +
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 " +
        "focus-visible:outline-focus " +
        (pressed ? "bg-selected text-t1" : "text-t3")
      }
    >
      {/* A ruler, laid diagonally with its graduations, so it reads at 14px. */}
      <svg
        viewBox="0 0 24 24"
        aria-hidden
        className="h-3.5 w-3.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M3 15l12-12 6 6-12 12z" />
        <path d="M7 11l2 2M11 7l2 2M9 17l2-2" />
      </svg>
    </button>
  );
}

/** The one control that opens the full preview: a small maximize glyph, never a text button. */
export function MaximizeButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      data-dev-id="component-browser.asset-maximize"
      aria-label={label}
      title={label}
      onClick={onClick}
      className={
        "flex h-[20px] w-[20px] items-center justify-center rounded-control text-t3 " +
        "hover:bg-control-hover hover:text-t1 focus-visible:outline focus-visible:outline-2 " +
        "focus-visible:outline-offset-1 focus-visible:outline-focus"
      }
    >
      <svg
        viewBox="0 0 16 16"
        aria-hidden
        className="h-3.5 w-3.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
      >
        <path d="M6 2H2v4M10 14h4v-4M14 6V2h-4M2 10v4h4" />
      </svg>
    </button>
  );
}

/** The strip a preview's controls sit on: one 24px line, transparent, no borders, no wrap. */
export function AssetControlStrip({ children }: { children: ReactNode }) {
  return (
    <div
      data-dev-id="component-browser.asset-control-strip"
      className="flex min-h-[24px] flex-none items-center gap-1 px-2 py-0.5"
    >
      {children}
    </div>
  );
}
