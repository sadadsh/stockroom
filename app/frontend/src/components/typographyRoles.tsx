/**
 * The typography kit's COMPONENTS, and nothing else.
 *
 * The scale itself - `TYPOGRAPHY_SCALE`, the `UI_*` class names and the role types - lives in the
 * sibling `typography.ts`, which is also the kit's import surface: every existing call site keeps
 * importing from `./typography` and is unaffected by this split.
 *
 * WHY THE SPLIT
 * A module that exports components AND values is not a Fast Refresh boundary: react-refresh cannot
 * prove the module is safe to hot-swap, so editing one role forced a full page reload and threw away
 * whatever state the screen was holding. Components live here, where every export is a component;
 * the values live next door, where nothing is.
 *
 * WHY EACH ROLE IS A DECLARED FUNCTION
 * The roles used to be built by a factory (`export const PropertyLabel = role("propertyLabel",
 * "span")`). That is invisible to react-refresh for the same reason: a call expression is not
 * recognisable as a component, so seventeen of the app's most-used text elements sat outside the
 * refresh boundary. Each role is now a named function whose whole body is one `RoleText` element, so
 * the single implementation below is still the only place a role class is applied - a role cannot be
 * half-applied - while the export is something the toolchain can see.
 */
import type { ElementType, HTMLAttributes, ReactNode } from "react";
import {
  TYPOGRAPHY_SCALE,
  UI_DISABLED,
  UI_NUMERIC,
  UI_STATUS_TEXT,
  type StatusTone,
  type TypographyRoleName,
} from "./typography";
import { Icon } from "./Icon";

function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

interface RoleProps extends Omit<HTMLAttributes<HTMLElement>, "color"> {
  /** The element to render. Defaults per role, because a table header must be a `th`. */
  as?: ElementType;
  /** Right-align with tabular figures. For stock, prices, quantities and price breaks. */
  numeric?: boolean;
  /** Paint the disabled tier: an unavailable value, not a quiet one. */
  disabled?: boolean;
  children?: ReactNode;
}

// One implementation behind every role. Each exported role below is a thin binding of a role name
// and a default element, so a role can never be half-applied and the props stay uniform.
function RoleText({
  roleName,
  defaultAs,
  as,
  numeric,
  disabled,
  className,
  children,
  ...rest
}: { roleName: TypographyRoleName; defaultAs: ElementType } & RoleProps) {
  const Element = as ?? defaultAs;
  return (
    <Element
      className={cx(
        TYPOGRAPHY_SCALE[roleName].className,
        numeric && UI_NUMERIC,
        disabled && UI_DISABLED,
        className,
      )}
      {...rest}
    >
      {children}
    </Element>
  );
}

export function ComponentMpn(props: RoleProps) {
  return <RoleText roleName="componentMpn" defaultAs="span" {...props} />;
}

export function DialogTitle(props: RoleProps) {
  return <RoleText roleName="dialogTitle" defaultAs="h2" {...props} />;
}

export function ComponentDescription(props: RoleProps) {
  return <RoleText roleName="componentDescription" defaultAs="p" {...props} />;
}

export function ComponentMetadata(props: RoleProps) {
  return <RoleText roleName="componentMetadata" defaultAs="span" {...props} />;
}

export function KeyFact(props: RoleProps) {
  return <RoleText roleName="keyFact" defaultAs="span" {...props} />;
}

export function PanelTitle(props: RoleProps) {
  return <RoleText roleName="panelTitle" defaultAs="div" {...props} />;
}

export function SectionTitle(props: RoleProps) {
  return <RoleText roleName="sectionTitle" defaultAs="div" {...props} />;
}

export function PropertyLabel(props: RoleProps) {
  return <RoleText roleName="propertyLabel" defaultAs="span" {...props} />;
}

export function PropertyValue(props: RoleProps) {
  return <RoleText roleName="propertyValue" defaultAs="span" {...props} />;
}

export function SourceText(props: RoleProps) {
  return <RoleText roleName="sourceText" defaultAs="span" {...props} />;
}

export function TableHeader(props: RoleProps) {
  return <RoleText roleName="tableHeader" defaultAs="th" {...props} />;
}

export function RowPrimary(props: RoleProps) {
  return <RoleText roleName="rowPrimary" defaultAs="span" {...props} />;
}

export function RowSecondary(props: RoleProps) {
  return <RoleText roleName="rowSecondary" defaultAs="span" {...props} />;
}

export function RowMetadata(props: RoleProps) {
  return <RoleText roleName="rowMetadata" defaultAs="span" {...props} />;
}

export function MenuLabel(props: RoleProps) {
  return <RoleText roleName="menuLabel" defaultAs="span" {...props} />;
}

export function ControlLabel(props: RoleProps) {
  return <RoleText roleName="controlLabel" defaultAs="span" {...props} />;
}

export function MachineText(props: RoleProps) {
  return <RoleText roleName="machineText" defaultAs="span" {...props} />;
}

const STATUS_TONE: Record<StatusTone, string> = {
  ok: "text-ok-text",
  warn: "text-warn",
  err: "text-err-text",
  neutral: "text-t3",
};

/**
 * The warning triangle a `warn` status draws beside its own word.
 *
 * `--c-warn` is a NEUTRAL: the amber it used to be ended up carrying `Missing`,
 * `Missing Datasheet + Purchase Link`, `3 Required Values Missing` and `Update Available` as well as
 * the selection accent, which made the warning colour the most common colour on screen and therefore
 * no warning at all. So the mark moved from the hue to a shape. The triangle carries the warning, the
 * exact word says which warning it is, and the state no longer depends on colour in either
 * direction - which is the accessibility rule stated properly rather than satisfied by having text
 * next to a hue.
 *
 * `aria-hidden`, because the word beside it is the accessible name and a screen reader announcing
 * "warning warning" is worse than either alone.
 */
export function WarnMark({ className }: { className?: string } = {}) {
  return (
    <Icon
      id="status.warn"
      className={cx("mr-0.5 inline-block h-[9px] w-[9px] flex-none align-[-0.5px]", className)}
    />
  );
}

/**
 * A status is a STATE, not a control.
 *
 * It renders as a bare `span` carrying the tone colour and nothing else: no border, no fill, no
 * rounded box, no pointer cursor, no hover, no press and no focus ring. Every one of those says
 * "you can click this", and a status cannot be clicked. The role class also pins `cursor: default`
 * so an ancestor's `cursor-pointer` cannot leak onto it.
 *
 * A `warn` status additionally draws the triangle above, because its tone is a neutral and the shape
 * is what marks it. `ok` and `err` keep their hues and need no glyph.
 */
export function StatusText({
  tone = "neutral",
  as: Element = "span",
  className,
  children,
  ...rest
}: { tone?: StatusTone } & RoleProps) {
  return (
    <Element className={cx(UI_STATUS_TEXT, STATUS_TONE[tone], className)} {...rest}>
      {tone === "warn" ? <WarnMark /> : null}
      {children}
    </Element>
  );
}
