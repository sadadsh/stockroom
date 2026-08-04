/**
 * Editing who this component IS, and what a design tool will therefore receive.
 *
 * Two sections, because there are two kinds of field here and only one of them is ours to name.
 *
 *   Identity  - the two attributes Stockroom owns: the display name it is listed under, and the
 *               `value` a passive is described by. Neither is in the EDA registry.
 *   Handoff   - everything a schematic fill actually stamps onto a placed component, rendered
 *               straight from the generated EDA registry by `components/HandoffBand.tsx`.
 *
 * The handoff half used to be a hand-written list here (mpn, manufacturer, description) while
 * `HandoffBand` rendered the same fields FROM THE REGISTRY and was rendered by nothing at all
 * after `DetailPanel` was deleted. Two editors for one field is worse than either, and the
 * hand-written one was the wrong one to keep: the registry is what lets a third EDA tool join by
 * declaring `data_fields` and regenerating, and the band also carries the symbol and footprint
 * references and the datasheet, which this sheet had no way to show at all.
 *
 * The category still goes through `moveCategory` rather than `editField`, because a move relocates
 * the part's symbol and footprint libraries too - writing `category` as a plain field would rename
 * the label and leave the files where they were.
 */
import type { PartDetail } from "../../api/types";
import type { ComponentIdentityView } from "../../api/workspaceTypes";
import { Text } from "../../lib/copy";
import { EditableText } from "../EditableText";
import { HandoffBand } from "../HandoffBand";
import { ErrorState, LoadingState, Section } from "../primitives";

/**
 * The canonical record attributes this sheet edits DIRECTLY.
 *
 * Deliberately short. Every other editable attribute is declared by the EDA registry and rendered
 * by the handoff band below, so adding one here would be adding a second editor for it.
 */
export const IDENTITY_FIELDS: ReadonlyArray<{
  field: "display_name" | "value";
  label: string;
  copyId: string;
  mono?: boolean;
}> = [
  {
    field: "display_name",
    label: "Display Name",
    copyId: "component-browser.identity-display-name",
  },
  { field: "value", label: "Value", copyId: "component-browser.identity-value", mono: true },
];

export function IdentitySheet({
  identity,
  detail,
  detailLoading,
  detailFailed,
  onRetryDetail,
  categories,
  onEditField,
  onMoveCategory,
  busy,
}: {
  identity: ComponentIdentityView;
  /**
   * The canonical record, fetched only while this sheet is open. The handoff band renders the
   * RECORD rather than the projection, because the registry names record attributes and the
   * projection has already reshaped them.
   */
  detail: PartDetail | null;
  detailLoading: boolean;
  detailFailed: boolean;
  onRetryDetail: () => void;
  /** Every category the library already has, so a move never invents a new filing by typo. */
  categories: string[];
  onEditField: (field: string, value: string) => void;
  onMoveCategory: (category: string) => void;
  busy: boolean;
}) {
  const values: Record<string, string> = {
    display_name: identity.displayName,
    value: identity.value,
  };
  // A move can only offer filings that exist. The current one is included even when the facet
  // query has not answered, so the control never renders with nothing selected.
  const options = categories.includes(identity.category)
    ? categories
    : [identity.category, ...categories].filter(Boolean);

  return (
    <div data-dev-id="component-browser.identity-sheet" className="flex flex-col gap-4">
      <Section
        title="Identity"
        copyId="component-browser.identity-title"
        note={
          <Text id="component-browser.identity-note">
            How this component is listed in Stockroom. The fields a design tool receives are below.
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
                  mono={entry.mono}
                  disabled={busy}
                  displayClassName="text-xs"
                  onSave={(next) => onEditField(entry.field, next)}
                />
              </dd>
            </div>
          ))}
        </dl>
      </Section>

      <Section
        title="Design Tool Handoff"
        copyId="component-browser.identity-handoff-title"
        note={
          <Text id="component-browser.identity-handoff-note">
            These fields are mirrored into the symbol a design tool places, so a change here changes
            what a schematic says about this component. Moving a component relocates its symbol and
            footprint libraries as well as its label.
          </Text>
        }
      >
        {detailLoading ? (
          <LoadingState id="component-browser.identity-detail-loading">
            Loading this component's record...
          </LoadingState>
        ) : detailFailed || !detail ? (
          <ErrorState id="component-browser.identity-detail-failed" onRetry={onRetryDetail}>
            This component's record could not be read.
          </ErrorState>
        ) : (
          <HandoffBand
            detail={detail}
            onEditField={onEditField}
            onMoveCategory={onMoveCategory}
            categories={options}
            busy={busy}
          />
        )}
      </Section>
    </div>
  );
}
