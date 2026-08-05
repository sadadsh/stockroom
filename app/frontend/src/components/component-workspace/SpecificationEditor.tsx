/**
 * The compact editor attached to one specification. Not a wizard, not a card, not a page.
 *
 * A person correcting a supply voltage is doing one small thing, and the surface has to be the
 * size of the thing: the row above it does not move, its label stays on screen, and the controls
 * sit in the disclosure the row already opened. A "complete component" flow for one field is the
 * failure this replaces - it turned a two-character correction into a workflow.
 *
 * Seven decisions travel together because they are one decision. What the value is, what unit it
 * is in, what KIND of value it is, whose answer is in force, why, whether the reviewer stands
 * behind it, and whether it outranks the sources at all. Splitting them across two writes would
 * let half a decision land.
 *
 * Nothing is sent until the category's own rules pass. Every rule comes from the `constraint` the
 * dossier already sent - a floor, a ceiling, a unit, a list of allowed values - so a refusal
 * arrives instantly and, more to the point, says what the correction is.
 */
import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import type { SpecificationRecord, ValueType } from "../../api/dossierTypes";
import type { SpecificationWrite } from "../../api/queries";
import { Text, useCopyFormatter, useText } from "../../lib/copy";
import { Button } from "../primitives";
import {
  composeSpecificationValue,
  editableValueType,
  EDITABLE_VALUE_TYPES,
  validateSpecificationEdit,
  type SpecDraft,
  type SpecEditRefusal,
} from "./specificationEditing";

/** The source a value can be taken from. `manual` is the reviewer's own answer. */
const REVIEWED_SOURCE = "manual:reviewed";

/**
 * The names the value types read under.
 *
 * A `<select>` option cannot carry a `<Text>` wrapper - an option may only hold text - so these go
 * through `useText`, which resolves the same override and returns a string. Fixed order, one call
 * per type, so the hook order can never depend on what the record happens to be.
 */
function useValueTypeLabels(): Record<ValueType, string> {
  return {
    quantity: useText("component-browser.spec-type-quantity", "Quantity"),
    range: useText("component-browser.spec-type-range", "Range"),
    integer: useText("component-browser.spec-type-integer", "Whole Number"),
    boolean: useText("component-browser.spec-type-boolean", "Yes Or No"),
    enum: useText("component-browser.spec-type-enum", "One Of A List"),
    text: useText("component-browser.spec-type-text", "Text"),
    list: useText("component-browser.spec-type-list", "List"),
  };
}

export interface SpecificationEditorProps {
  record: SpecificationRecord;
  /** True while ANY write on this component is in flight. */
  busy: boolean;
  /**
   * Why the last write did not save, or "" when none failed.
   *
   * It is rendered HERE, in the editor, because that is where the person is looking and what they
   * were doing when it failed. A global toast tells somebody that something went wrong somewhere;
   * this tells them their edit is still unsaved and still in front of them.
   */
  failure?: string;
  onCancel: () => void;
  /** Run the composed write. The caller reverts and reports when it does not land. */
  onSubmit: (write: SpecificationWrite) => Promise<unknown>;
}

export function SpecificationEditor({
  record,
  busy,
  failure = "",
  onCancel,
  onSubmit,
}: SpecificationEditorProps) {
  const fieldId = useId();
  const [value, setValue] = useState(record.displayValue);
  const [unit, setUnit] = useState(record.unit || record.constraint?.unit || "");
  const [valueType, setValueType] = useState<ValueType>(() => editableValueType(record));
  const [sourceId, setSourceId] = useState(REVIEWED_SOURCE);
  const [reason, setReason] = useState(record.override?.note ?? "");
  const [verified, setVerified] = useState(record.override?.verified ?? true);
  // Whether the reviewed value outranks every source. Unchecking it does not throw the entry
  // away: it says "believe this source instead", which is the other decision this field can carry.
  const [preferOverride, setPreferOverride] = useState(true);
  const [refusal, setRefusal] = useState<SpecEditRefusal | null>(null);
  const valueRef = useRef<HTMLInputElement | HTMLSelectElement | null>(null);

  const valueLabel = useCopyFormatter("component-browser.spec-editor-value", "{label} value");
  const unitLabel = useText("component-browser.spec-editor-unit", "Unit");
  const typeLabel = useText("component-browser.spec-editor-type", "Value Type");
  const sourceLabel = useText("component-browser.spec-editor-source", "Source");
  const reasonLabel = useText("component-browser.spec-editor-reason", "Reason");
  const reasonHint = useText("component-browser.spec-editor-reason-hint", "Why this value");
  const verificationLabel = useText(
    "component-browser.spec-editor-verification",
    "Verification Status",
  );
  const reviewedSource = useText("component-browser.spec-editor-reviewed", "Reviewed Value");
  const verifiedWord = useText("component-browser.spec-verified", "Verified");
  const unverifiedWord = useText("component-browser.spec-unverified", "Unverified");
  const valueTypeLabels = useValueTypeLabels();

  useEffect(() => {
    const node = valueRef.current;
    node?.focus();
    // A select has no text to select; only the text box does.
    if (node instanceof HTMLInputElement) node.select();
  }, []);

  const allowed = record.constraint?.allowed ?? [];
  const pinnable = useMemo(
    () => record.sourceCandidates.filter((candidate) => candidate.sourceId !== ""),
    [record.sourceCandidates],
  );
  const reviewed = sourceId === REVIEWED_SOURCE;

  function submit(): void {
    if (!reviewed) {
      // Believing a source is not a value edit, so nothing about the typed entry is validated
      // against the category: the source's own answer is what lands.
      setRefusal(null);
      void onSubmit({ kind: "set-preferred-source", key: record.key, sourceId });
      return;
    }
    const draft: SpecDraft = { value, unit, valueType };
    const problem = validateSpecificationEdit(record, draft);
    setRefusal(problem);
    if (problem) {
      valueRef.current?.focus();
      return;
    }
    if (!preferOverride) {
      // The reviewer typed a value but does not want it to outrank the sources. There is no such
      // thing as a stored-but-ignored manual answer, so the honest write is to withdraw whatever
      // override is in force and leave the field to its ranked sources.
      void onSubmit({ kind: "clear-override", key: record.key });
      return;
    }
    void onSubmit({
      kind: "set-override",
      key: record.key,
      value: composeSpecificationValue(draft),
      note: reason.trim(),
      verified,
    });
  }

  return (
    <div
      data-dev-id="component-browser.spec-editor"
      // A bordered, coloured surface, so its text gets at least 8px of padding all round.
      className="flex flex-col gap-1.5 border border-line bg-surface p-2"
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          onCancel();
        }
      }}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <EditorField id={`${fieldId}-value`} label={valueLabel({ label: record.label })} grow>
          {valueType === "enum" && allowed.length > 0 ? (
            <select
              id={`${fieldId}-value`}
              ref={(node) => {
                valueRef.current = node;
              }}
              data-dev-id="component-browser.spec-override-input"
              value={value}
              disabled={busy || !reviewed}
              onChange={(event) => setValue(event.target.value)}
              className={FIELD_CLASS}
            >
              <option value="">{"—"}</option>
              {allowed.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          ) : (
            <input
              id={`${fieldId}-value`}
              ref={(node) => {
                valueRef.current = node;
              }}
              type="text"
              data-dev-id="component-browser.spec-override-input"
              value={value}
              disabled={busy || !reviewed}
              onChange={(event) => setValue(event.target.value)}
              onKeyDown={(event) => {
                if (event.key !== "Enter") return;
                event.preventDefault();
                submit();
              }}
              className={FIELD_CLASS}
            />
          )}
        </EditorField>

        <EditorField id={`${fieldId}-unit`} label={unitLabel}>
          <input
            id={`${fieldId}-unit`}
            type="text"
            data-dev-id="component-browser.spec-editor-unit"
            value={unit}
            disabled={busy || !reviewed}
            onChange={(event) => setUnit(event.target.value)}
            // Narrow on purpose: a unit selector that is wider than the value it qualifies makes
            // the qualifier look like the measurement.
            className={`${FIELD_CLASS} w-[4.5rem]`}
          />
        </EditorField>

        <EditorField id={`${fieldId}-type`} label={typeLabel}>
          <select
            id={`${fieldId}-type`}
            data-dev-id="component-browser.spec-editor-type"
            value={valueType}
            disabled={busy || !reviewed}
            onChange={(event) => setValueType(event.target.value as ValueType)}
            className={FIELD_CLASS}
          >
            {EDITABLE_VALUE_TYPES.map((candidate) => (
              <option key={candidate} value={candidate}>
                {valueTypeLabels[candidate]}
              </option>
            ))}
          </select>
        </EditorField>
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <EditorField id={`${fieldId}-source`} label={sourceLabel}>
          <select
            id={`${fieldId}-source`}
            data-dev-id="component-browser.spec-editor-source"
            value={sourceId}
            disabled={busy}
            onChange={(event) => setSourceId(event.target.value)}
            className={FIELD_CLASS}
          >
            <option value={REVIEWED_SOURCE}>{reviewedSource}</option>
            {pinnable.map((candidate) => (
              <option key={candidate.sourceId} value={candidate.sourceId}>
                {`${candidate.sourceLabel} · ${candidate.displayValue}`}
              </option>
            ))}
          </select>
        </EditorField>

        <EditorField id={`${fieldId}-verification`} label={verificationLabel}>
          <select
            id={`${fieldId}-verification`}
            data-dev-id="component-browser.spec-editor-verification"
            value={verified ? "verified" : "unverified"}
            disabled={busy || !reviewed}
            onChange={(event) => setVerified(event.target.value === "verified")}
            className={FIELD_CLASS}
          >
            <option value="verified">{verifiedWord}</option>
            <option value="unverified">{unverifiedWord}</option>
          </select>
        </EditorField>

        <EditorField id={`${fieldId}-reason`} label={reasonLabel} grow>
          <input
            id={`${fieldId}-reason`}
            type="text"
            data-dev-id="component-browser.spec-editor-reason"
            placeholder={reasonHint}
            value={reason}
            disabled={busy || !reviewed}
            onChange={(event) => setReason(event.target.value)}
            className={FIELD_CLASS}
          />
        </EditorField>
      </div>

      <label className="ui-control-label flex items-center gap-1.5">
        <input
          type="checkbox"
          data-dev-id="component-browser.spec-editor-prefer"
          checked={preferOverride}
          disabled={busy || !reviewed}
          onChange={(event) => setPreferOverride(event.target.checked)}
          className="h-3 w-3 accent-[var(--c-acc)]"
        />
        <Text id="component-browser.spec-editor-prefer">
          Prefer this value over every source
        </Text>
      </label>

      {refusal || failure ? (
        // Directly beneath the controls, at 10px, naming the rule that was broken or the write
        // that did not land. The row above still shows what the library actually holds.
        <p
          data-dev-id="component-browser.spec-editor-error"
          role="alert"
          className="ui-component-metadata text-err"
        >
          {refusal ? <RefusalText refusal={refusal} /> : failure}
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-1.5">
        <Button
          small
          data-dev-id="component-browser.spec-override-save"
          disabled={busy}
          onClick={submit}
        >
          <Text id="component-browser.spec-override-save">Save Value</Text>
        </Button>
        <Button small data-dev-id="component-browser.spec-override-cancel" onClick={onCancel}>
          <Text id="component-browser.spec-override-cancel">Cancel</Text>
        </Button>
      </div>
    </div>
  );
}

// 11px input text, the same size as the value it replaces, and a fixed 22px height so opening the
// editor cannot change the height of the row above it.
const FIELD_CLASS =
  "ui-property-value h-[22px] min-w-0 rounded-control border border-line bg-field px-1.5 " +
  "focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-1 " +
  "focus-visible:outline-focus disabled:text-t4";

/**
 * One labelled control.
 *
 * The label is a real `<label>` and stays visible while the field is being typed into. A
 * placeholder is never the only name a field has: it disappears at the first keystroke, which is
 * exactly when somebody is most likely to have forgotten which box they are in.
 */
function EditorField({
  id,
  label,
  grow = false,
  children,
}: {
  id: string;
  label: string;
  grow?: boolean;
  children: ReactNode;
}) {
  return (
    <span className={`flex min-w-0 flex-col gap-0.5 ${grow ? "flex-1" : "flex-none"}`}>
      <label htmlFor={id} className="ui-property-label">
        {label}
      </label>
      {children}
    </span>
  );
}

/**
 * What the correction is.
 *
 * Never "invalid" and never "something went wrong": each sentence names the rule the entry broke
 * and the value that would satisfy it, because a person who is told a number is wrong without
 * being told what right looks like has to guess twice.
 */
function RefusalText({ refusal }: { refusal: SpecEditRefusal }) {
  const { problem, values } = refusal;
  if (problem === "required") {
    return (
      <Text id="component-browser.spec-refusal-required">
        Enter a value, or cancel to leave the field as it is.
      </Text>
    );
  }
  if (problem === "not-applicable") {
    return (
      <Text id="component-browser.spec-refusal-not-applicable" values={values}>
        {"{label} does not apply to this kind of component."}
      </Text>
    );
  }
  if (problem === "not-a-number") {
    return (
      <Text id="component-browser.spec-refusal-number">
        Enter a number, such as 3.3.
      </Text>
    );
  }
  if (problem === "not-an-integer") {
    return (
      <Text id="component-browser.spec-refusal-integer">
        Enter a whole number, with no decimal part.
      </Text>
    );
  }
  if (problem === "not-a-range") {
    return (
      <Text id="component-browser.spec-refusal-range" values={values}>
        {"Enter two numbers separated by {dash}, such as 1.65–5.5."}
      </Text>
    );
  }
  if (problem === "not-a-boolean") {
    return <Text id="component-browser.spec-refusal-boolean">Enter Yes or No.</Text>;
  }
  if (problem === "not-allowed") {
    return (
      <Text id="component-browser.spec-refusal-allowed" values={values}>
        {"This field accepts only: {allowed}"}
      </Text>
    );
  }
  if (problem === "wrong-unit") {
    return (
      <Text id="component-browser.spec-refusal-unit" values={values}>
        {"This field is measured in {unit}. Use it, or a prefixed form of it."}
      </Text>
    );
  }
  if (problem === "below-minimum") {
    return (
      <Text id="component-browser.spec-refusal-minimum" values={values}>
        {"This field cannot be below {minimum} {unit}."}
      </Text>
    );
  }
  return (
    <Text id="component-browser.spec-refusal-maximum" values={values}>
      {"This field cannot be above {maximum} {unit}."}
    </Text>
  );
}
