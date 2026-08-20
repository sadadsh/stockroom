/**
 * The Add A Part window. A single in-window modal (the ConfirmDialog / CommandPalette
 * scrim idiom, so it feels like the rest of the app) that hosts the whole Add A Part
 * flow. Opened from the Components toolbar or Ctrl+K palette through useAddPart().
 * It springs in over a blurred
 * scrim; Escape or a scrim click closes it and returns focus where it was.
 */
import { useEffect } from "react";
import { useAddPart } from "../lib/addPart";
import { IngestPage } from "../pages/IngestPage";
import { Text, useText } from "../lib/copy";
import { useScenarioUiState } from "../design-studio/scenarioState";
import { useModalDismiss } from "../lib/useModalDismiss";
import { ModalHeader } from "./primitives";

export function AddPartModal() {
  const { isOpen, close } = useAddPart();
  const scenarioState = useScenarioUiState().addParts?.state;
  const effectiveOpen = isOpen || scenarioState !== undefined;
  // Copy layer: the dialog and Close accessible names live in attributes, so they resolve through
  // useText; the visible title is a <Text> below. Resolved unconditionally (before the early return)
  // to keep hook order stable.
  const dialogLabel = useText("modal.addPart.aria", "Add a Part");
  const { ref, zIndex } = useModalDismiss(effectiveOpen, close);

  useEffect(() => {
    if (!effectiveOpen) return;
    // Land the caret in the hero input so a pasted link is one keystroke away.
    const focusTimer = window.setTimeout(() => {
      document.querySelector<HTMLInputElement>('[data-dev-id="ingest.input"]')?.focus();
    }, 60);
    return () => window.clearTimeout(focusTimer);
  }, [effectiveOpen]);

  if (!effectiveOpen) return null;

  return (
    <div
      data-dev-id="addpart.scrim"
      style={{ zIndex }}
      className="fixed inset-0 flex items-start justify-center bg-scrim p-4 pt-[8vh]"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) close();
      }}
    >
      <div
        ref={ref}
        data-dev-id="addpart.root"
        className="flex max-h-[84vh] w-full max-w-[1120px] flex-col overflow-hidden rounded-card border border-line2 bg-popover shadow-pop outline-none"
        role="dialog"
        aria-modal="true"
        aria-label={dialogLabel}
        tabIndex={-1}
        data-scenario-state={scenarioState}
      >
        <ModalHeader
          title={<Text id="modal.addPart.title">Add a Part</Text>}
          onClose={close}
          devId="addpart.header"
          closeDevId="addpart.close"
        />
        <div data-dev-id="addpart.body" className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          <p className="mb-4 text-xs leading-relaxed text-t3">
            <Text id="modal.addPart.subtitle">
              Resolve exact identification and source evidence, then let Stockroom complete one shared
              CAD package.
            </Text>
          </p>
          <IngestPage />
        </div>
      </div>
    </div>
  );
}
