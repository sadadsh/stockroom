/**
 * `Preferred Source: Ultra Librarian v` - the CAD column's one column-level decision.
 *
 * This fact was on the screen from the beginning and was the only fact nobody could set: it was
 * INFERRED from the three attached files and said "Mixed" when they disagreed. A description of
 * the past is not a decision, and a person looking at a mixed set had nothing to do about it.
 *
 * Two rules shape the control:
 *
 *   ONE PROVIDER FOR THE SET. Stockroom never combines files from two providers, so this chooses
 *   a provider for all three assets. A provider that cannot supply all three is still LISTED,
 *   disabled, carrying the reason - because "why is SnapMagic missing from this list" is exactly
 *   the question a person opened it to answer, and silence is not an answer.
 *
 *   SAY WHAT WILL CHANGE, FIRST. Choosing a source replaces the source of up to three assets.
 *   The confirmation names each one and what would supply it instead, and it is built from the
 *   plan the BACKEND computed with the same function that refuses the write - so it cannot
 *   describe an outcome different from the one that happens. A choice that replaces nothing
 *   skips the dialog entirely; a dialog that says "this changes nothing" only teaches a person
 *   to dismiss the one that matters.
 */
import { useState } from "react";
import type { CadPreferenceOption, CadPreferenceView } from "../../api/dossierTypes";
import { Text, useCopyFormatter, useText } from "../../lib/copy";
import { ConfirmDialog } from "../ConfirmDialog";
import { PropertyLabel } from "../typography";
import { chosenOption, needsConfirmation, orderedChanges, preferenceOptions } from "./cadPreference";

/** The value the select carries for "no provider is preferred", distinct from every provider id. */
const NONE = "";

/**
 * This control addresses the WHOLE set, and only the whole set.
 *
 * A per-asset choice is a real thing to want and it lives in the comparison table, beside the
 * coverage that decides whether it is legitimate. Offering it here as well would put the
 * exception on the same line as the rule, which is how a person ends up pinning one artifact
 * while believing they chose a source for three.
 */
export function PreferredSourceControl({
  preference,
  busy,
  onChoose,
  onClear,
}: {
  preference: CadPreferenceView;
  busy: boolean;
  onChoose: (provider: string) => void;
  onClear: () => void;
}) {
  const [pending, setPending] = useState<CadPreferenceOption | null>(null);
  const options = preferenceOptions(preference);
  const chosen = chosenOption(preference);

  const label = useText("component-browser.preferred-source", "Preferred Source");
  const noneLabel = useText("component-browser.cad-source-none", "None recorded");
  const mixedLabel = useText("component-browser.cad-source-mixed", "Mixed");
  const useAttached = useText("component-browser.cad-source-clear", "Use The Attached Files");
  const confirmTitle = useText("component-browser.cad-source-confirm-title", "Change Preferred Source");
  const confirmAction = useText("component-browser.cad-source-confirm-action", "Change Source");
  const replaceLead = useCopyFormatter(
    "component-browser.cad-source-confirm-lead",
    "Preferring {provider} replaces the source of {count} assets:",
  );
  const changeLine = useCopyFormatter(
    "component-browser.cad-source-confirm-change",
    "{asset}: {from} becomes {to}",
  );
  const changeFromNone = useCopyFormatter(
    "component-browser.cad-source-confirm-new",
    "{asset}: {to}, which nothing supplied before",
  );

  function pick(value: string) {
    if (value === NONE) {
      onClear();
      return;
    }
    const option = options.find((entry) => entry.provider === value);
    if (!option) return;
    if (!option.set.allowed) return;
    // The change is SHOWN before it happens, never performed and then reported.
    if (needsConfirmation(option.set)) {
      setPending(option);
      return;
    }
    onChoose(option.provider);
  }

  const scope = pending ? pending.set : null;

  return (
    <span className="flex min-w-0 items-center gap-1.5">
      <PropertyLabel className="flex-none">{label}</PropertyLabel>
      <select
        data-dev-id="component-browser.preferred-source-control"
        aria-label={label}
        // A mixed set has no single answer to show, so the control shows the word rather than
        // silently displaying one of the two providers as though it governed all three.
        value={chosen?.provider ?? NONE}
        disabled={busy}
        onChange={(event) => pick(event.target.value)}
        title={
          preference.mixed && !chosen
            ? mixedLabel
            : (chosen?.label ?? noneLabel)
        }
        className={
          "ui-control-label h-[22px] min-w-0 max-w-[11rem] flex-1 truncate rounded-control " +
          "border border-line bg-field px-1.5 text-t2 outline-none " +
          "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 " +
          "focus-visible:outline-focus disabled:opacity-60"
        }
      >
        {/* The first entry is the state the column is in when nothing is DECIDED, and it says
            which of the three that is: the three assets disagree, a decision is in force and can
            be withdrawn, the files that happen to be attached agree on a provider, or nothing
            names a source at all. Showing "None recorded" over an attached set would deny a fact
            the column can see. */}
        <option value={NONE}>
          {preference.mixed && !chosen
            ? mixedLabel
            : preference.pinned
              ? useAttached
              : preference.label || noneLabel}
        </option>
        {options.map((option) => {
          const entry = option.set;
          return (
            <option
              key={option.provider}
              value={option.provider}
              disabled={!entry.allowed}
              // A disabled option must SAY why. The reason is the fact the control exists to
              // surface, and hiding the row would answer the question with an absence.
              title={entry.allowed ? undefined : entry.reason}
            >
              {entry.allowed ? option.label : `${option.label} - ${entry.reason}`}
            </option>
          );
        })}
      </select>

      <ConfirmDialog
        open={pending !== null && scope !== null}
        title={confirmTitle}
        confirmLabel={confirmAction}
        busy={busy}
        onCancel={() => setPending(null)}
        onConfirm={() => {
          const provider = pending?.provider ?? "";
          setPending(null);
          if (provider) onChoose(provider);
        }}
        body={
          scope === null || pending === null ? null : (
            <div data-dev-id="component-browser.cad-source-confirm" className="flex flex-col gap-2">
              <p>{replaceLead({ provider: pending.label, count: scope.changes.length })}</p>
              <ul className="flex flex-col gap-1">
                {orderedChanges(scope).map((change) => (
                  <li key={change.asset} className="ui-row-secondary" data-asset={change.asset}>
                    {change.fromLabel
                      ? changeLine({
                          asset: change.assetLabel,
                          from: change.fromLabel,
                          to: change.toLabel,
                        })
                      : changeFromNone({ asset: change.assetLabel, to: change.toLabel })}
                  </li>
                ))}
              </ul>
              <p className="ui-row-metadata">
                <Text id="component-browser.cad-source-confirm-note">
                  The files attached now are not deleted. This records which provider the set
                  should come from, and what is still to be downloaded from it.
                </Text>
              </p>
            </div>
          )
        }
      />
    </span>
  );
}
