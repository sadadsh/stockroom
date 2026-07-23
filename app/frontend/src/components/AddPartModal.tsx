/**
 * The Add A Part window. A single in-window modal (the ConfirmDialog / CommandPalette
 * scrim idiom, so it feels like the rest of the app) that hosts the whole Add A Part
 * flow. Opened from three places through useAddPart(): the Components toolbar button,
 * the Ctrl+K palette, and a vendor ZIP dropped anywhere. It springs in over a blurred
 * scrim; Escape or a scrim click closes it and returns focus where it was.
 */
import { useEffect, useRef } from "react";
import { motion } from "motion/react";
import { useAddPart } from "../lib/addPart";
import { IngestPage } from "../pages/IngestPage";
import { Text, useText } from "../lib/copy";
import { Icon } from "./Icon";

export function AddPartModal() {
  const { isOpen, close } = useAddPart();
  // Copy layer: the dialog and Close accessible names live in attributes, so they resolve through
  // useText; the visible title is a <Text> below. Resolved unconditionally (before the early return)
  // to keep hook order stable.
  const dialogLabel = useText("modal.addPart.aria", "Add a Part");
  const closeLabel = useText("modal.addPart.close", "Close");
  // Where focus was when we opened, so closing never strands focus on the scrim.
  const restoreRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    restoreRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") close();
    }
    window.addEventListener("keydown", onKey);
    // Land the caret in the hero input so a pasted link is one keystroke away.
    const focusTimer = window.setTimeout(() => {
      document
        .querySelector<HTMLInputElement>('[aria-label="Product link or part number"]')
        ?.focus();
    }, 60);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.clearTimeout(focusTimer);
      restoreRef.current?.focus();
    };
  }, [isOpen, close]);

  if (!isOpen) return null;

  return (
    <div
      data-dev-id="addpart.scrim"
      className="fixed inset-0 z-[95] flex items-start justify-center bg-black/60 p-4 pt-[8vh] backdrop-blur-sm"
      role="presentation"
      onClick={close}
    >
      <motion.div
        data-dev-id="addpart.root"
        initial={{ opacity: 0, scale: 0.965, y: 10 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        transition={{ type: "spring", stiffness: 420, damping: 32 }}
        className="flex max-h-[84vh] w-full max-w-[640px] flex-col overflow-hidden rounded-card border border-line bg-popover shadow-pop"
        role="dialog"
        aria-modal="true"
        aria-label={dialogLabel}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          data-dev-id="addpart.header"
          className="flex h-14 flex-none items-center justify-between border-b border-line px-5"
        >
          <div className="text-base font-semibold text-t1">
            <Text id="modal.addPart.title">Add a Part</Text>
          </div>
          <button
            type="button"
            data-dev-id="addpart.close"
            aria-label={closeLabel}
            onClick={close}
            className="flex h-8 w-8 items-center justify-center rounded-control text-t3 transition-colors hover:bg-raise2 hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc"
          >
            <Icon id="action.close" />
          </button>
        </div>
        <div data-dev-id="addpart.body" className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
          <IngestPage />
        </div>
      </motion.div>
    </div>
  );
}
