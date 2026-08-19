/**
 * THE EDA HANDOFF BAND - what an EDA tool actually receives from this part, at the top of the sheet.
 *
 * Owner, 2026-07-25: "the most important fields (like the ones that go to the eda tools) should be
 * top above the specifications. thats the most important info."
 *
 * That is an information-hierarchy change, not a styling one. Before this, the five fields a
 * schematic fill stamps onto a placed component were scattered across three columns by ACCIDENT of
 * where each happened to be authored: MPN and Manufacturer read as a breadcrumb under the title,
 * Datasheet and Description sat at the very bottom of the third column (below Links, the least
 * visible spot on the sheet), and the symbol/footprint references were only implied by the preview
 * tiles. Nothing anywhere answered "is this part ready to place, and with what".
 *
 * WHICH fields appear is not decided here. `EDA_DATA_FIELDS` is generated from the Python EDA
 * registry, so a third tool joins this band by declaring `data_fields` and regenerating - with no
 * edit in this file. The band renders the `origin: "curated"` half: the vendor-owned fields are the
 * Sourcing column's subject and change on their own, and the derived ones are computed at emit time
 * and stored nowhere (see FIELD_ORIGINS in the registry for the full reasoning).
 */
import type { ReactNode } from "react";
import type { PartDetail } from "../api/types";
import { edaTool } from "../lib/edaRegistry.generated";
import { assetRef, assetsFor } from "../lib/edaTarget";
import { compactUrl } from "../lib/compactUrl";
import { Text, useCopyFormatter, useText } from "../lib/copy";
import { instanceDevId } from "../lib/componentDevIds";
import { EditableText } from "./EditableText";
import { AdaptiveChoice } from "./AdaptiveChoice";
import { Icon } from "./Icon";
import { EYEBROW_DENSE } from "./primitives";
import { handoffFields } from "./handoffFields";

/** The value a field currently holds on the record, and how to present it. */
interface Resolved {
  /** The display text. Empty means the field is not set, which the band shows as a gap. */
  text: string;
  /** The full underlying value for a `title`, when `text` is a shortened form of it. */
  full?: string;
  /** An external link this field opens, when it has one. */
  href?: string;
}

function resolve(field: string, detail: PartDetail): Resolved {
  const kicad = assetsFor(detail, "kicad");
  switch (field) {
    case "mpn":
      return { text: detail.mpn ?? "" };
    case "manufacturer":
      return { text: detail.manufacturer ?? "" };
    case "category":
      // Read through: a record written by an older build may carry no `derived` block at all, and
      // a blank cell is the honest answer there. It used to throw, which blanked the whole sheet.
      return { text: detail.derived?.category ?? "" };
    case "description":
      return { text: detail.derived?.description ?? "" };
    case "symbol":
    case "footprint": {
      // The reference as the TOOL resolves it (`<lib>:<name>`), not the on-disk file name: that
      // is the string the schematic actually carries, so it is the one worth checking.
      const ref = assetRef(field === "symbol" ? kicad.symbol : kicad.footprint);
      const lib = (ref?.lib ?? "").trim();
      const name = (ref?.name ?? "").trim();
      if (!name) return { text: "" };
      return { text: lib ? `${lib}:${name}` : name, full: lib ? `${lib}:${name}` : name };
    }
    case "datasheet": {
      const url = detail.datasheet?.source_url || detail.datasheet?.file || "";
      if (!url) return { text: "" };
      return {
        text: compactUrl(url, 34),
        full: url,
        href: detail.datasheet?.source_url || undefined,
      };
    }
    default:
      return { text: "" };
  }
}

export function HandoffBand({
  detail,
  onEditField,
  onMoveCategory,
  categories,
  busy,
}: {
  detail: PartDetail;
  onEditField?: (field: string, value: string) => void;
  onMoveCategory?: (category: string) => void;
  categories?: string[];
  busy?: boolean;
}) {
  const bandLabel = useText("detail.handoff-label", "EDA Handoff");
  const fields = handoffFields();
  const resolved = fields.map((f) => ({ field: f, value: resolve(f.key, detail) }));
  const ready = resolved.filter((r) => r.value.text.trim()).length;
  const total = resolved.length;
  // Name the tools by their real labels rather than saying "your EDA tools": a person who only
  // uses KiCad should see KiCad named, and the registry already knows what is registered.
  const toolNames = [...new Set(fields.flatMap((f) => f.tools))]
    .map((k) => edaTool(k)?.label ?? k)
    .join(" and ");

  return (
    // `@container`: the cell count must react to THIS BAND's width, not the sheet's. The band
    // lives at the top of the Specifications COLUMN (~392px), while the sheet container is the
    // whole pane (~1041px) - so sheet-relative breakpoints put four cells in a 392px column, at
    // ~95px each, and "TPD6E05U06RVZR" broke mid-word while "MANUFACTURER" truncated to
    // "MANUFACT...". Measured. This is the same lesson the sheet grid already learned: query the
    // box the content actually has, never an ancestor that happens to be wider.
    <section
      data-dev-id="detail.handoff"
      aria-label={bandLabel}
      className="@container flex flex-none flex-col rounded-card border border-line bg-surface"
    >
      <header className="flex items-center gap-3 border-b border-line px-3 py-1.5">
        <span className={EYEBROW_DENSE}>
          <Text id="detail.handoff">EDA Handoff</Text>
        </span>
        <span className="ml-auto min-w-0 truncate text-2xs text-t3">
          {/* States the SET, so the band is answerable at a glance without reading every cell.
              The count is of curated fields actually FILLED.

              It said "7 of 7 ready", and that word was doing three different jobs within one
              window: here it meant non-empty TEXT FIELDS, the CAD chip 12px away said
              "Incomplete" about ASSETS, and Settings said "0 of 1 parts ready to place" about
              PLACEABILITY. One part, three verdicts, all using the same vocabulary. "Ready" now
              belongs to placement alone; this band says what it actually counts. */}
          <span
            data-dev-id="detail.handoff-ready"
            className={ready === total ? "font-medium text-ok-text" : "font-medium text-warn"}
          >
            <Text id="detail.handoff.filled-count" values={{ ready, total }}>
              {"{ready} of {total} filled"}
            </Text>
          </span>
          {/* hidden in a narrow band: the COUNT is the load-bearing half, and the tool names
              are what push the header into a truncation nobody can read */}
          <span className="hidden text-t3 @sm:inline"> for {toolNames}</span>
        </span>
      </header>
      {/* Two rows of four at full width, collapsing with the sheet. Description spans the last two
          cells because it is prose and a 200px cell would show three words of it. */}
      {/* Two cells across in a normal Specifications column, three only when it is genuinely
          wide. Container-relative: @sm is 24rem, @2xl is 42rem, measured against the band. */}
      <div className="grid grid-cols-1 gap-px bg-line @sm:grid-cols-2 @2xl:grid-cols-3">
        {resolved.map(({ field, value }) => (
          <HandoffCell
            key={field.key}
            fieldKey={field.key}
            label={field.label}
            value={value}
            // A field only ONE tool receives is the exception worth marking. Marking every cell
            // with both tools would be eight identical badges saying nothing.
            only={field.tools.length === 1 ? (edaTool(field.tools[0])?.label ?? "") : ""}
            className={field.key === "description" ? "col-span-full" : ""}
            edit={
              field.key === "category"
                ? onMoveCategory && categories?.length
                  ? { kind: "select" as const, options: categories, onSave: onMoveCategory }
                  : undefined
                : onEditField && EDITABLE.has(field.key)
                  ? {
                      kind: "text" as const,
                      multiline: field.key === "description",
                      onSave: (v: string) => onEditField(field.key, v),
                    }
                  : undefined
            }
            busy={busy}
          />
        ))}
      </div>
    </section>
  );
}

// The fields `onEditField` genuinely accepts. A symbol or footprint reference is NOT typed in by
// hand - it is attached through Complete Part, which copies the real file and records its hash - so
// offering a text box for it would invite a reference to a file that does not exist.
const EDITABLE = new Set(["mpn", "manufacturer", "datasheet", "description"]);

type Edit =
  | { kind: "text"; multiline?: boolean; onSave: (value: string) => void }
  | { kind: "select"; options: string[]; onSave: (value: string) => void };

function HandoffCell({
  fieldKey,
  label,
  value,
  only,
  className,
  edit,
  busy,
}: {
  fieldKey: string;
  label: string;
  value: Resolved;
  only: string;
  className?: string;
  edit?: Edit;
  busy?: boolean;
}) {
  const missing = !value.text.trim();
  // The tool name in the hole is registry data; the sentence around it is ours.
  const onlyReceives = useCopyFormatter(
    "detail.handoff-only-tip",
    "{tool} alone receives this field",
  );
  return (
    <div
      // One cell per registry field: the cell names the field it IS and the class it belongs to,
      // so a field key carrying a space or a bracket can never forge another cell's id.
      data-dev-id={instanceDevId("detail.handoff-field", fieldKey)}
      data-dev-role="detail.handoff-field"
      className={`flex min-w-0 flex-col justify-start gap-0.5 bg-canvas px-3 py-2 ${className ?? ""}`}
    >
      <div className="flex min-w-0 items-center gap-1.5">
        <span className={`truncate ${EYEBROW_DENSE}`}>{label}</span>
        {only ? (
          <span
            // Quiet by construction: no fill, no box, just the smallest label the type scale has.
            // As a filled chip it was ~110px wide - wider than the CATEGORY label beside it and
            // louder than the value beneath it, which inverted the cell's hierarchy for the one
            // field that is a footnote rather than a headline.
            className="ml-auto min-w-0 flex-none truncate ui-row-metadata"
            title={onlyReceives({ tool: only })}
          >
            <Text id="detail.handoff.only-tool" values={{ tool: only }}>
              {"{tool} alone"}
            </Text>
          </span>
        ) : null}
      </div>
      <HandoffValue
        fieldKey={fieldKey}
        label={label}
        value={value}
        missing={missing}
        edit={edit}
        busy={busy}
      />
    </div>
  );
}

function HandoffValue({
  fieldKey,
  label,
  value,
  missing,
  edit,
  busy,
}: {
  fieldKey: string;
  label: string;
  value: Resolved;
  missing: boolean;
  edit?: Edit;
  busy?: boolean;
}): ReactNode {
  // Resolved before the branches below, because a hook cannot sit past an early return. The field
  // NAME in each hole is registry vocabulary; the sentence it sits in is ours.
  const noneOnRecord = useCopyFormatter("detail.handoff-missing-tip", "No {field} on record");
  // The in-field hint and the accessible name of the open affordance. Both hold a field NAME in
  // their hole, which is registry vocabulary, while the words around it are ours.
  const addHint = useCopyFormatter("detail.handoff-add-placeholder", "Add {field}");
  const openName = useCopyFormatter("detail.handoff-open-aria", "Open {field}");
  if (edit?.kind === "select") {
    return (
      <AdaptiveChoice
        devId="detail.category-control"
        label={label}
        value={value.text}
        disabled={busy}
        onChange={(next) => next !== value.text && edit.onSave(next)}
        options={edit.options.map((option) => ({ value: option, label: option }))}
        className="h-7 w-full"
      />
    );
  }

  if (edit?.kind === "text") {
    const editor = (
      <EditableText
        value={value.full ?? value.text}
        onSave={edit.onSave}
        label={label}
        placeholder={addHint({ field: label })}
        multiline={edit.multiline}
        clampLines={edit.multiline ? 2 : undefined}
        // TRUNCATE every single-line value. MEASURED in the owner's REAL window (1423px viewport,
        // 2026-07-25): the datasheet cell reported clientWidth 261 against scrollWidth 357 - the URL
        // pushed 96px past its own box and dragged the whole handoff block into overflow. Offscreen
        // shots at 1600px never showed it because the cell was wide enough there. `break-words` is
        // EditableText's default and is right for prose; a URL has no spaces to break at, so it
        // simply runs. The full value stays reachable: the editor opens on it and `title` holds it.
        truncate={!edit.multiline}
        disabled={busy}
        displayClassName="text-xs font-medium text-t1"
        // The DISPLAY is shortened while the EDITOR still opens on the full value: a person
        // editing a datasheet link must get the whole URL in the box, never the elided label.
        // `display` is EditableText's existing prop for exactly this and already had a caller.
        display={value.full && value.full !== value.text ? value.text : undefined}
      />
    );
    // A datasheet is the one editable field that is also a DESTINATION. Click-to-edit alone would
    // mean the only way to read the datasheet is to open its editor and copy the URL out, so the
    // cell carries a separate open affordance beside the editor - the same two jobs the shipped
    // datasheet row does (punch 8), in the room a cell has.
    if (!value.href) return editor;
    return (
      <div className="flex min-w-0 items-center gap-1.5">
        <div className="min-w-0 flex-1">{editor}</div>
        <a
          href={value.href}
          target="_blank"
          rel="noreferrer"
          data-dev-id={instanceDevId("detail.handoff-open", fieldKey)}
          data-dev-role="detail.handoff-open"
          aria-label={openName({ field: label })}
          title={value.full}
          className="flex-none rounded-control p-0.5 text-t3 transition-colors hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
        >
          <Icon id="action.external" className="h-3 w-3" />
        </a>
      </div>
    );
  }

  if (missing) {
    return (
      <span className="truncate text-xs font-medium text-warn" title={noneOnRecord({ field: label })}>
        <Text id="detail.handoff-missing">Not Set</Text>
      </span>
    );
  }

  if (value.href) {
    return (
      <a
        href={value.href}
        target="_blank"
        rel="noreferrer"
        title={value.full}
        // The SAME accessible name the editable branch gives it. The visible text is a shortened
        // URL, which would otherwise make this control's screen-reader name depend on whether the
        // caller happened to allow editing - one control, two names.
        aria-label={openName({ field: label })}
        className="truncate text-xs font-medium text-t1 underline decoration-line underline-offset-2 transition-colors hover:decoration-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
      >
        {value.text}
      </a>
    );
  }

  return (
    <span className="truncate text-xs font-medium text-t1" title={value.full ?? value.text}>
      {value.text}
    </span>
  );
}
