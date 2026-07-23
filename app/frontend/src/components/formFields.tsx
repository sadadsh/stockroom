/**
 * Small labelled form controls shared by the Add-A-Part flow (a combobox backed by a
 * datalist, a plain select, and a text field with an optional hint). One home so the
 * passive add section and the candidate editor render identical controls. An optional
 * copyId renders the label through the copy layer, so it is dev-mode editable.
 */
import { Text } from "../lib/copy";

function FieldLabel({ label, copyId }: { label: string; copyId?: string }) {
  return (
    <span className="text-xs text-t3">
      {copyId ? <Text id={copyId}>{label}</Text> : label}
    </span>
  );
}

export function ComboField({
  label,
  copyId,
  value,
  onChange,
  options,
  listId,
}: {
  label: string;
  copyId?: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
  listId: string;
}) {
  return (
    <label className="flex flex-col gap-1">
      <FieldLabel label={label} copyId={copyId} />
      <input
        list={listId}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-control border border-line2 bg-field px-3 py-2 text-base text-t1 outline-none focus:border-acc"
      />
      <datalist id={listId}>
        {options.map((o) => (
          <option key={o} value={o} />
        ))}
      </datalist>
    </label>
  );
}

export function SelectField({
  label,
  copyId,
  value,
  onChange,
  placeholder,
  options,
}: {
  label: string;
  copyId?: string;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  options: [string, string][];
}) {
  return (
    <label className="flex flex-col gap-1">
      <FieldLabel label={label} copyId={copyId} />
      <select
        aria-label={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-control border border-line2 bg-field px-3 py-2 text-base text-t1 outline-none focus:border-acc"
      >
        <option value="">{placeholder}</option>
        {options.map(([v, text]) => (
          <option key={v} value={v}>
            {text}
          </option>
        ))}
      </select>
    </label>
  );
}

export function TextField({
  label,
  copyId,
  value,
  onChange,
  placeholder,
  hint,
}: {
  label: string;
  copyId?: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  hint?: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="flex flex-col gap-1">
        <FieldLabel label={label} copyId={copyId} />
        <input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className="rounded-control border border-line2 bg-field px-3 py-2 text-base text-t1 outline-none focus:border-acc"
        />
      </label>
      {hint ? <span className="text-xs text-t3">{hint}</span> : null}
    </div>
  );
}
