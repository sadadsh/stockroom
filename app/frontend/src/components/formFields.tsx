/**
 * Small labelled form controls shared by the Add-A-Part flow (a combobox backed by a
 * datalist, a plain select, and a text field with an optional hint). One home so the
 * passive add section and the candidate editor render identical controls.
 */

export function ComboField({
  label,
  value,
  onChange,
  options,
  listId,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
  listId: string;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-t3">{label}</span>
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
  value,
  onChange,
  placeholder,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  options: [string, string][];
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-t3">{label}</span>
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
  value,
  onChange,
  placeholder,
  hint,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  hint?: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="flex flex-col gap-1">
        <span className="text-xs text-t3">{label}</span>
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
