/**
 * The semantic typography kit: one named role per interface job, and the machine-readable
 * description of what each role is.
 *
 * WHY THIS EXISTS
 * The owner's diagnosis of the opened-component screen was that "the text system is treating the
 * MPN, generated name, manufacturer description, metadata, statuses, and actions as though they
 * have equal authority". That is what happens when hierarchy is assembled per call site out of
 * `text-xs font-semibold text-t1`: there is no place where the decision lives, so every surface
 * re-derives it and no two agree. Across this frontend that produced ~1050 ad-hoc size utilities
 * and ~200 semibold/bold decisions with nothing arbitrating between them.
 *
 * WHY BOTH A CLASS AND A COMPONENT
 * Each role ships as a CSS class in `styles/index.css` (@layer components) AND as a component in
 * the sibling `typographyRoles.tsx`.
 *
 *  - The CLASS is the authority. These roles land on a `span`, a `div`, a `dt`, a `dd`, a `th` and
 *    a `td` depending on where they sit, and a table header genuinely has to be a `<th>`. A class
 *    is the only form that works on all of them without a polymorphic type puzzle, it works inside
 *    `cx(...)` next to layout utilities, and it can be adopted by a surface one line at a time.
 *  - The COMPONENT is the ergonomics, and the thing that makes the role discoverable: it pins the
 *    default element, forwards the rest of the props, and gives the role a name that shows up in
 *    review. `<PropertyLabel>` states its intent; `className="text-2xs text-t3"` states a value.
 *
 * They cannot drift, because the component's class string IS the class name, and
 * `typography.test.tsx` reads the shipped stylesheet and asserts every role's size, weight,
 * leading and colour against `TYPOGRAPHY_SCALE` below.
 *
 * WHY THIS MODULE IS VALUES ONLY
 * The components used to live here beside the scale. A module that exports both is not a Fast
 * Refresh boundary, so editing one text role reloaded the whole page. They moved to
 * `typographyRoles.tsx` - which exports nothing but components - and are re-exported from the
 * bottom of this file, so `./typography` remains the one import surface for the kit and no call
 * site had to change.
 *
 * THE BUDGET (enforced by that test)
 *   sizes    14 / 13 / 11 / 10 px, and nothing else
 *   weights  600 / 500 / 400, and nothing else
 *   colours  primary / secondary / label / muted / disabled, and nothing else
 * 14px is the canonical MPN and only the canonical MPN. Nothing in the normal workspace reaches
 * 16px, and nothing drops below 10px.
 */

export type TextTier = "primary" | "secondary" | "label" | "muted" | "disabled";
export type TextSize = 10 | 11 | 13 | 14;
export type TextWeight = 400 | 500 | 600;
export type TextLeading = 14 | 15 | 16 | 18;

export interface TypographyRole {
  /** The CSS class that carries the role. Declared in styles/index.css. */
  className: string;
  fontSize: TextSize;
  fontWeight: TextWeight;
  lineHeight: TextLeading;
  /** The text tier the role paints in, or null when the caller supplies a status tone. */
  tier: TextTier | null;
  /** Whether the role sets `font-variant-numeric: tabular-nums`. */
  tabular: boolean;
}

/**
 * The whole type system, in one table. Read by `typography.test.tsx` against the shipped
 * stylesheet, so this is a description of what ships and not a second opinion about it.
 */
export const TYPOGRAPHY_SCALE = {
  // The canonical manufacturer part number. The one thing that outranks everything else on an
  // opened component, and the only 14px in the normal workspace.
  componentMpn: {
    className: "ui-component-mpn",
    fontSize: 14,
    fontWeight: 600,
    lineHeight: 18,
    tier: "primary",
    tabular: true,
  },
  // A dialog, viewer or modal title: one step under the MPN, because a dialog is a container and
  // the part is the subject.
  dialogTitle: {
    className: "ui-dialog-title",
    fontSize: 13,
    fontWeight: 600,
    lineHeight: 18,
    tier: "primary",
    tabular: false,
  },
  // The manufacturer's own description. Prose about the part, not the part's identity, so it takes
  // the secondary tier and body weight however long it is.
  componentDescription: {
    className: "ui-component-description",
    fontSize: 11,
    fontWeight: 400,
    lineHeight: 15,
    tier: "secondary",
    tabular: false,
  },
  // Retrieval info, timestamps, provider fetch notes.
  componentMetadata: {
    className: "ui-component-metadata",
    fontSize: 10,
    fontWeight: 400,
    lineHeight: 14,
    tier: "muted",
    tabular: true,
  },
  // A headline value the user opened the component to read: package, stock, unit price.
  keyFact: {
    className: "ui-key-fact",
    fontSize: 11,
    fontWeight: 600,
    lineHeight: 15,
    tier: "primary",
    tabular: true,
  },
  // The title strip of a docked panel or a list column.
  panelTitle: {
    className: "ui-panel-title",
    fontSize: 11,
    fontWeight: 600,
    lineHeight: 16,
    tier: "primary",
    tabular: false,
  },
  // A heading inside a panel, grouping the rows beneath it.
  sectionTitle: {
    className: "ui-section-title",
    fontSize: 11,
    fontWeight: 600,
    lineHeight: 15,
    tier: "primary",
    tabular: false,
  },
  // The static name of a field. Never bold, never uppercase, never letterspaced: a label that
  // shouts competes with the value it introduces.
  propertyLabel: {
    className: "ui-property-label",
    fontSize: 10,
    fontWeight: 500,
    lineHeight: 14,
    tier: "label",
    tabular: false,
  },
  // The value beside that label. Left-aligned; a numeric value opts into right alignment and
  // tabular figures with the `numeric` prop.
  propertyValue: {
    className: "ui-property-value",
    fontSize: 11,
    fontWeight: 400,
    lineHeight: 15,
    tier: "primary",
    tabular: false,
  },
  // Where a value came from: a provider, a datasheet, a library.
  sourceText: {
    className: "ui-source-text",
    fontSize: 11,
    fontWeight: 400,
    lineHeight: 15,
    tier: "secondary",
    tabular: false,
  },
  // A state, not a control. The class strips border, fill, pointer and focus affordances; the
  // caller adds the tone colour, which is why `tier` is null.
  statusText: {
    className: "ui-status-text",
    fontSize: 10,
    fontWeight: 500,
    lineHeight: 14,
    tier: null,
    tabular: false,
  },
  // A table column header. Sentence case; the weight does the separating, not caps and tracking.
  tableHeader: {
    className: "ui-table-header",
    fontSize: 10,
    fontWeight: 600,
    lineHeight: 14,
    tier: "label",
    tabular: false,
  },
  // The identifying text of a list row.
  rowPrimary: {
    className: "ui-row-primary",
    fontSize: 11,
    fontWeight: 600,
    lineHeight: 15,
    tier: "primary",
    tabular: false,
  },
  // The supporting text on the same row.
  rowSecondary: {
    className: "ui-row-secondary",
    fontSize: 11,
    fontWeight: 400,
    lineHeight: 15,
    tier: "secondary",
    tabular: false,
  },
  // Counts, dates and sizes trailing a row.
  rowMetadata: {
    className: "ui-row-metadata",
    fontSize: 10,
    fontWeight: 400,
    lineHeight: 14,
    tier: "muted",
    tabular: true,
  },
  // An item in a menu or a context menu.
  menuLabel: {
    className: "ui-menu-label",
    fontSize: 11,
    fontWeight: 400,
    lineHeight: 15,
    tier: "primary",
    tabular: false,
  },
  // The text on or beside a control.
  controlLabel: {
    className: "ui-control-label",
    fontSize: 11,
    fontWeight: 500,
    lineHeight: 14,
    tier: "primary",
    tabular: false,
  },
  // Genuinely machine-oriented text: file paths, raw identifiers, hashes, net names, provider keys,
  // diagnostic payloads. NOT MPNs, manufacturer names, descriptions, spec labels or ordinary
  // values. Monospace only keeps its meaning while it stays the mark of text a machine wrote.
  machineText: {
    className: "ui-machine-text",
    fontSize: 11,
    fontWeight: 400,
    lineHeight: 15,
    tier: "primary",
    tabular: true,
  },
} as const satisfies Record<string, TypographyRole>;

export type TypographyRoleName = keyof typeof TYPOGRAPHY_SCALE;

/** Every role class, for a surface that needs the raw string (a `cx(...)`, a `<th>`, a table cell). */
export const UI_COMPONENT_MPN = TYPOGRAPHY_SCALE.componentMpn.className;
export const UI_DIALOG_TITLE = TYPOGRAPHY_SCALE.dialogTitle.className;
export const UI_COMPONENT_DESCRIPTION = TYPOGRAPHY_SCALE.componentDescription.className;
export const UI_COMPONENT_METADATA = TYPOGRAPHY_SCALE.componentMetadata.className;
export const UI_KEY_FACT = TYPOGRAPHY_SCALE.keyFact.className;
export const UI_PANEL_TITLE = TYPOGRAPHY_SCALE.panelTitle.className;
export const UI_SECTION_TITLE = TYPOGRAPHY_SCALE.sectionTitle.className;
export const UI_PROPERTY_LABEL = TYPOGRAPHY_SCALE.propertyLabel.className;
export const UI_PROPERTY_VALUE = TYPOGRAPHY_SCALE.propertyValue.className;
export const UI_SOURCE_TEXT = TYPOGRAPHY_SCALE.sourceText.className;
export const UI_STATUS_TEXT = TYPOGRAPHY_SCALE.statusText.className;
export const UI_TABLE_HEADER = TYPOGRAPHY_SCALE.tableHeader.className;
export const UI_ROW_PRIMARY = TYPOGRAPHY_SCALE.rowPrimary.className;
export const UI_ROW_SECONDARY = TYPOGRAPHY_SCALE.rowSecondary.className;
export const UI_ROW_METADATA = TYPOGRAPHY_SCALE.rowMetadata.className;
export const UI_MENU_LABEL = TYPOGRAPHY_SCALE.menuLabel.className;
export const UI_CONTROL_LABEL = TYPOGRAPHY_SCALE.controlLabel.className;
export const UI_MACHINE_TEXT = TYPOGRAPHY_SCALE.machineText.className;

/** Right-aligned tabular figures: stock, prices, quantities, price breaks. */
export const UI_NUMERIC = "ui-numeric";
/** A value that is unavailable, rather than merely quiet. */
export const UI_DISABLED = "ui-disabled";

export type StatusTone = "ok" | "warn" | "err" | "neutral";

// The role components. They are DECLARED in `typographyRoles.tsx` so that module can be a Fast
// Refresh boundary; they are named here so `./typography` stays the kit's single import surface.
export {
  ComponentDescription,
  ComponentMetadata,
  ComponentMpn,
  ControlLabel,
  DialogTitle,
  KeyFact,
  MachineText,
  MenuLabel,
  PanelTitle,
  PropertyLabel,
  PropertyValue,
  RowMetadata,
  RowPrimary,
  RowSecondary,
  SectionTitle,
  SourceText,
  StatusText,
  TableHeader,
  WarnMark,
} from "./typographyRoles";
