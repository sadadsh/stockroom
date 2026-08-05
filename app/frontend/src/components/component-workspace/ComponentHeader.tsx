/**
 * The opened component's identity header.
 *
 * It is the one thing on this workspace that never changes when the information tabs do. Whichever
 * question the person is currently asking - what is it, what are its numbers, where do we buy it,
 * where did the answers come from - the answer to "which component am I looking at, and is it in
 * good shape" has to stay on screen, or every tab has to restate it and the four tabs drift into
 * four different identities for one part.
 *
 * Everything here comes from the workspace projection. No provider shapes, no record spelunking,
 * and no derived claim that the projection did not already make.
 */
import type { ComponentWorkspaceResponse } from "../../api/workspaceTypes";
import { Badge, Button } from "../primitives";
import { ExternalIcon } from "../icons";
import { Text, useText } from "../../lib/copy";
import { statusTone, toolStatus } from "./workspaceStatus";

/** The label for the one contextual primary action, derived from the top attention item. */
export function primaryActionLabel(action: string | null): string {
  if (!action) return "Open Full Specifications";
  if (action === "edit-identity") return "Add Missing Identity";
  if (action === "open-requirements") return "Review Requirements";
  if (action.startsWith("open-representation:")) {
    const kind = action.slice("open-representation:".length);
    const noun = kind === "model" ? "3D Model" : kind.charAt(0).toUpperCase() + kind.slice(1);
    return `Fix ${noun}`;
  }
  if (action.startsWith("open-field-source:")) return "Resolve Source Conflict";
  return "Review Component";
}

/**
 * The attention item the header speaks for: blocking first, then warning, then info.
 *
 * One action, not a row of them. A header that offers five things offers none: the point of the
 * slot is that the component itself names the next move.
 */
export function primaryAttention(
  workspace: ComponentWorkspaceResponse,
): ComponentWorkspaceResponse["attention"][number] | null {
  const order = { blocking: 0, warning: 1, info: 2 } as const;
  const sorted = [...workspace.attention].sort(
    (a, b) => order[a.severity] - order[b.severity],
  );
  return sorted[0] ?? null;
}

export function ComponentHeader({
  workspace,
  onPrimaryAction,
  onEditIdentity,
  onOpenDatasheet,
  onOpenProviders,
}: {
  workspace: ComponentWorkspaceResponse;
  onPrimaryAction: (action: string | null) => void;
  /** Identity is edited from the header because the header is what identity IS on this surface. */
  onEditIdentity: () => void;
  onOpenDatasheet: () => void;
  /** Opens Complete Component: the whole provider trip, in the one modal allowed to scroll. */
  onOpenProviders: () => void;
}) {
  const { identity, summary, representations } = workspace;
  const kicad = toolStatus(representations, "kicad");
  const altium = toolStatus(representations, "altium");
  const attention = primaryAttention(workspace);
  const providers = workspace.providers;
  // How many providers could supply the WHOLE set, out of how many exist. Two numbers, because
  // "2 of 9" and "2" are different facts and only the first says whether to keep looking.
  const providerSummary = `${providers.completeProviders.length}/${providers.rows.length}`;
  const providersTitle = useText(
    "component-browser.providers-summary-title",
    "Providers that can supply the symbol, the footprint and the 3D model",
  );
  const actionLabel = useText(
    "component-browser.header-action",
    primaryActionLabel(attention?.action ?? null),
  );
  const datasheetLabel = useText("component-browser.header-datasheet", "Datasheet");
  const editLabel = useText("component-browser.header-edit", "Edit Identity");
  // A value that merely restates the part number is not a second fact. Only a genuinely different
  // one earns the space (a resistor's `10k`, a crystal's `16 MHz`).
  const distinctValue =
    identity.value && identity.value.trim() !== identity.mpn.trim() ? identity.value : "";
  const productUrl = workspace.sourcing.offers.find((offer) => offer.url)?.url ?? "";

  return (
    <header
      data-dev-id="component-browser.header"
      className="flex flex-none flex-col gap-1.5 border-b border-line bg-surface px-4 py-2.5"
    >
      <div className="flex min-w-0 items-baseline gap-3">
        <h1
          data-dev-id="component-browser.header-name"
          className="min-w-0 truncate text-base font-semibold text-t1"
          title={identity.displayName}
        >
          {identity.displayName}
        </h1>
        {distinctValue ? (
          <span className="flex-none font-mono text-xs text-t2">{distinctValue}</span>
        ) : null}
        <span className="min-w-0 flex-none truncate font-mono text-xs text-t2">
          {identity.mpn || "—"}
        </span>
        <span className="ml-auto flex flex-none items-center gap-1.5">
          <span
            data-dev-id="component-browser.header-status"
            className="flex flex-none items-center gap-1.5"
          >
            <Badge size="sm" tone={statusTone(kicad)} title={`KiCad ${kicad}`}>
              {`KiCad ${kicad}`}
            </Badge>
            <Badge size="sm" tone={statusTone(altium)} title={`Altium ${altium}`}>
              {`Altium ${altium}`}
            </Badge>
          </span>
        </span>
      </div>
      {/* The identity has a FLOOR, and the actions give way rather than the facts.
          None of these actions can shrink below its own label, so a single unbreakable row handed
          the identity whatever was left - at 960 (the supported minimum) that was nothing, and the
          row rendered `Manufacturer Package Category` with no values at all. The facts now claim a
          basis first; when the actions cannot sit beside it they take their own line, which costs
          one control row and keeps every value. */}
      <div className="flex min-w-0 flex-wrap items-center justify-end gap-3">
        <dl className="flex min-w-0 shrink grow basis-40 flex-wrap items-center gap-x-3 gap-y-0.5 overflow-hidden text-xs text-t2">
          <HeaderFact label="Manufacturer" value={identity.manufacturer} />
          <HeaderFact label="Package" value={identity.package ?? ""} />
          <HeaderFact label="Category" value={identity.category} />
          <HeaderFact label="Lifecycle" value={identity.lifecycle ?? ""} />
        </dl>
        <span
          data-dev-id="component-browser.header-links"
          className="flex flex-none items-center gap-2"
        >
          {summary.datasheetUrl || summary.datasheetFile ? (
            <Button
              data-dev-id="component-browser.header-datasheet"
              small
              onClick={onOpenDatasheet}
              aria-label={datasheetLabel}
            >
              <Text id="component-browser.header-datasheet">Datasheet</Text>
            </Button>
          ) : null}
          {productUrl ? (
            <a
              data-dev-id="component-browser.header-product-link"
              href={productUrl}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 rounded-control px-1.5 py-1 text-xs text-t2 transition-colors hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc"
            >
              <Text id="component-browser.header-product">Product Page</Text>
              <ExternalIcon />
            </a>
          ) : null}
        </span>
        <Button
          data-dev-id="component-browser.providers-summary"
          small
          title={providersTitle}
          onClick={onOpenProviders}
        >
          <Text id="component-browser.providers-open">Complete Component</Text>
          <span className="tnum font-mono text-2xs text-t2">{providerSummary}</span>
        </Button>
        <Button
          data-dev-id="component-browser.identity-edit"
          small
          aria-label={editLabel}
          onClick={onEditIdentity}
        >
          <Text id="component-browser.header-edit">Edit Identity</Text>
        </Button>
        <Button
          data-dev-id="component-browser.header-action"
          variant="accent"
          small
          onClick={() => onPrimaryAction(attention?.action ?? null)}
        >
          {actionLabel}
        </Button>
      </div>
    </header>
  );
}

/**
 * One identity fact. An absent value renders nothing rather than an empty labelled hole.
 *
 * Under the container threshold the label is `sr-only` and the VALUE stays. The three labels cost
 * more room than all four values together, so a single-line row that keeps them keeps the
 * decoration and drops the information, which is exactly backwards. The `<dt>` never leaves the
 * tree, so a screen reader still hears which fact this is; the hover title says the same thing for
 * a pointer. `not-sr-only` restores it as soon as the workspace is wide enough to afford it.
 */
function HeaderFact({ label, value }: { label: string; value: string }) {
  if (!value.trim()) return null;
  return (
    <span className="flex min-w-0 items-baseline gap-1.5" title={`${label} ${value}`}>
      <dt className="flex-none text-t3 sr-only @[48rem]:not-sr-only">{label}</dt>
      <dd className="min-w-0 truncate text-t1">{value}</dd>
    </span>
  );
}
