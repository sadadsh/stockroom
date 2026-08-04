/**
 * Editing who this component IS.
 *
 * Slice 2 replaced the detail sheet on the Components route and took inline identity editing and
 * the category move with it - which made a blocking attention item ("Manufacturer Is Missing")
 * name a repair the product could no longer perform. This is that capability back, in the one
 * place the workspace is allowed to be taller than its band.
 *
 * The fields are the canonical record attributes `editField` can actually write, and the category
 * goes through `moveCategory` rather than `editField` because a move relocates the part's symbol
 * and footprint libraries too - writing `category` as a plain field would rename the label and
 * leave the files where they were.
 */
import type { ComponentIdentityView, ComponentSummaryView } from "../../api/workspaceTypes";
import { Text, useText } from "../../lib/copy";
import { EditableText } from "../EditableText";
import { SheetSection } from "./SheetParts";

/** The canonical record attributes this sheet edits, in the order a person reads a part. */
export const IDENTITY_FIELDS: ReadonlyArray<{
  field: "display_name" | "mpn" | "manufacturer" | "value" | "description";
  label: string;
  copyId: string;
  multiline?: boolean;
  mono?: boolean;
}> = [
  {
    field: "display_name",
    label: "Display Name",
    copyId: "component-browser.identity-display-name",
  },
  { field: "mpn", label: "Manufacturer Part Number", copyId: "component-browser.identity-mpn", mono: true },
  { field: "manufacturer", label: "Manufacturer", copyId: "component-browser.identity-manufacturer" },
  { field: "value", label: "Value", copyId: "component-browser.identity-value", mono: true },
  {
    field: "description",
    label: "Description",
    copyId: "component-browser.identity-description",
    multiline: true,
  },
];

export function IdentitySheet({
  identity,
  summary,
  categories,
  onEditField,
  onMoveCategory,
  busy,
}: {
  identity: ComponentIdentityView;
  summary: ComponentSummaryView;
  /** Every category the library already has, so a move never invents a new filing by typo. */
  categories: string[];
  onEditField: (field: string, value: string) => void;
  onMoveCategory: (category: string) => void;
  busy: boolean;
}) {
  const categoryLabel = useText("component-browser.identity-category", "Category");
  const values: Record<string, string> = {
    display_name: identity.displayName,
    mpn: identity.mpn,
    manufacturer: identity.manufacturer,
    value: identity.value,
    description: summary.description.formattedValue,
  };
  // A move can only offer filings that exist. The current one is included even when the facet
  // query has not answered, so the select never renders with nothing selected.
  const options = categories.includes(identity.category)
    ? categories
    : [identity.category, ...categories].filter(Boolean);

  return (
    <div data-dev-id="component-browser.identity-sheet" className="flex flex-col gap-4">
      <SheetSection
        title="Identity"
        copyId="component-browser.identity-title"
        note={
          <Text id="component-browser.identity-note">
            These fields are mirrored into the symbol a design tool places, so a change here changes
            what a schematic says about this component.
          </Text>
        }
      >
        <dl className="rounded-card border border-line bg-raise px-3 py-1">
          {IDENTITY_FIELDS.map((entry) => (
            <div
              key={entry.field}
              data-dev-id="component-browser.identity-field"
              className="flex items-baseline gap-3 border-b border-line/60 py-1.5 last:border-b-0"
            >
              <dt className="w-[168px] flex-none text-2xs text-t2">
                <Text id={entry.copyId}>{entry.label}</Text>
              </dt>
              <dd className="min-w-0 flex-1">
                <EditableText
                  value={values[entry.field] ?? ""}
                  label={entry.label}
                  multiline={entry.multiline}
                  mono={entry.mono}
                  disabled={busy}
                  displayClassName="text-xs"
                  onSave={(next) => onEditField(entry.field, next)}
                />
              </dd>
            </div>
          ))}
        </dl>
      </SheetSection>

      <SheetSection
        title="Filing"
        copyId="component-browser.identity-filing-title"
        note={
          <Text id="component-browser.identity-filing-note">
            Moving a component relocates its symbol and footprint libraries as well as its label.
          </Text>
        }
      >
        <div className="flex items-center gap-3 rounded-card border border-line bg-raise px-3 py-2">
          <span className="flex-none text-2xs text-t2">
            <Text id="component-browser.identity-category">Category</Text>
          </span>
          <select
            data-dev-id="component-browser.identity-category"
            aria-label={categoryLabel}
            value={identity.category}
            disabled={busy}
            onChange={(event) => {
              if (event.target.value !== identity.category) onMoveCategory(event.target.value);
            }}
            className="h-7 rounded-control border border-line bg-field px-1.5 text-xs text-t1 disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc"
          >
            {options.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </div>
      </SheetSection>
    </div>
  );
}
