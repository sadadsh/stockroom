/**
 * Apply Pinout, restored beside the pinout it writes.
 *
 * The pre-workspace detail sheet could persist an enrichment-sourced pinout onto the record
 * (`handleApplyPinout` -> `useSetSpecs`), and Slice 2 left that unreachable. It comes back HERE,
 * in the specification sheet, because that is where the pinout table is: an action that fills a
 * table belongs beside the table, not on a tab a person has to remember to visit first.
 *
 * The write goes through the specs seam, not `editField`, so the record keeps WHICH source
 * supplied the pinout and at what confidence. A pinout applied with no attribution would be
 * indistinguishable from one somebody typed.
 */
import { useEnrichLookup, useSetSpecs } from "../../api/queries";
import type { SourcedField } from "../../api/types";
import { useText } from "../../lib/copy";
import { Button } from "../primitives";

/** The enriched pinout as a sourced field with a non-empty pin list, or null. */
export function pinoutOf(specs: Record<string, SourcedField | null>): SourcedField | null {
  const entry = specs.pinout;
  if (entry && Array.isArray(entry.value) && entry.value.length > 0) return entry;
  return null;
}

export function PinoutApply({
  componentId,
  mpn,
  category,
  onSaved,
  onFailed,
}: {
  componentId: string;
  mpn: string;
  category: string;
  onSaved: (pins: number) => void;
  onFailed: (error: unknown) => void;
}) {
  const enrich = useEnrichLookup();
  const setSpecs = useSetSpecs();
  const lookUp = useText("component-browser.pinout-lookup", "Look Up Pinout");
  const lookingUp = useText("component-browser.pinout-looking-up", "Looking Up...");
  const applyLabel = useText("component-browser.pinout-apply", "Apply Pinout");
  const applying = useText("component-browser.pinout-applying", "Applying...");
  const notFound = useText("component-browser.pinout-not-found", "No pinout found.");
  const failed = useText("component-browser.pinout-lookup-failed", "Lookup failed.");

  // Without a part number there is nothing to look a pinout up BY, so the control is not offered
  // at all rather than offered and guaranteed to fail.
  if (!mpn.trim()) return null;

  const running = enrich.status === "running";
  const found = enrich.result ? pinoutOf(enrich.result.specs) : null;

  if (found) {
    const pins = Array.isArray(found.value) ? found.value.length : 0;
    return (
      <span className="flex items-center gap-2">
        <span className="text-2xs text-t3">{`${found.source} ${pins}`}</span>
        <Button
          data-dev-id="component-browser.pinout-apply"
          small
          variant="accent"
          disabled={setSpecs.isPending}
          onClick={() =>
            setSpecs.mutate(
              {
                id: componentId,
                specs: {
                  pinout: {
                    value: found.value,
                    source: found.source,
                    confidence: found.confidence,
                  },
                },
              },
              { onSuccess: () => onSaved(pins), onError: onFailed },
            )
          }
        >
          {setSpecs.isPending ? applying : applyLabel}
        </Button>
      </span>
    );
  }

  return (
    <span className="flex items-center gap-2">
      {enrich.status === "error" ? <span className="text-2xs text-err">{failed}</span> : null}
      {enrich.status === "done" && !found ? (
        <span className="text-2xs text-t3">{notFound}</span>
      ) : null}
      <Button
        data-dev-id="component-browser.pinout-lookup"
        small
        disabled={running}
        onClick={() => enrich.runPart(mpn, category)}
      >
        {running ? lookingUp : lookUp}
      </Button>
    </span>
  );
}
