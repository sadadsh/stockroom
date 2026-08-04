/**
 * Overview: the four things a person wants in the first two seconds of opening a component.
 *
 * What it is (description), the numbers that decide it (key specifications), what is wrong with it
 * (needs attention), and whether it can be bought (sourcing snapshot). Each region is BOUNDED - a
 * clamped description, a capped spec block, a capped issue list, the top few distributors - because
 * the workspace does not scroll. When a region has more to say it says how much more and offers the
 * tab or modal that holds the rest, instead of growing the page until the dock is pushed off it.
 */
import type { ComponentWorkspaceResponse } from "../../api/workspaceTypes";
import type { ComponentInfoTab } from "../../lib/uiSession";
import { Text, useText } from "../../lib/copy";
import {
  KEY_SPEC_LIMIT,
  effectiveKeySpecKeys,
  isCuratedOnly,
  isPinned,
  keySpecRows,
  type PinnedSpecs,
} from "../../lib/keySpecs";
import { Badge, Dot, type BadgeTone } from "../primitives";
import { Empty, Region } from "./WorkspaceRegion";
import { specGroupsFromWorkspace } from "./workspaceSpecs";

/** The most a snapshot shows. Beyond this the Sourcing tab is the honest answer, not a taller card. */
const SNAPSHOT_OFFERS = 3;
/** The most issues the panel lists before it starts counting the rest. */
const ATTENTION_LIMIT = 4;

const SEVERITY_TONE: Record<string, BadgeTone> = {
  blocking: "err",
  warning: "warn",
  info: "neutral",
};

export function OverviewTab({
  workspace,
  pinned,
  onTogglePin,
  onAttentionAction,
  onOpenTab,
}: {
  workspace: ComponentWorkspaceResponse;
  pinned: PinnedSpecs;
  onTogglePin: (category: string, specKey: string) => void;
  onAttentionAction: (action: string) => void;
  onOpenTab: (tab: ComponentInfoTab) => void;
}) {
  const description = workspace.summary.description;
  const groups = specGroupsFromWorkspace(workspace.specifications);
  const category = workspace.identity.category;
  const rows = keySpecRows(groups, category, pinned).slice(0, KEY_SPEC_LIMIT);
  const effective = effectiveKeySpecKeys(groups, category, pinned);
  const attention = workspace.attention;
  const offers = workspace.sourcing.offers;
  const noStock = useText("component-browser.stock-unknown", "Stock unknown");
  const inStock = useText("component-browser.in-stock", "in stock");
  const noPrice = useText("component-browser.no-price", "No price");

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-hidden">
      <section
        data-dev-id="component-browser.description"
        className="flex-none rounded-card border border-line bg-raise px-3 py-2"
      >
        <div className="mb-0.5 flex items-center gap-2">
          <span className="text-2xs font-medium text-t3">
            <Text id="component-browser.description-title">Description</Text>
          </span>
          {description.state === "conflict" ? (
            <Badge size="sm" tone="warn">
              <Text id="component-browser.description-conflict">Sources Disagree</Text>
            </Badge>
          ) : null}
        </div>
        <p className="line-clamp-2 text-xs leading-relaxed text-t1">
          {description.formattedValue || (
            <Text id="component-browser.description-empty">No description on record.</Text>
          )}
        </p>
      </section>

      <div className="grid min-h-0 flex-1 auto-rows-fr grid-cols-1 gap-2 overflow-hidden @2xl:auto-rows-auto @2xl:grid-cols-3">
        <Region
          devId="component-browser.key-specs"
          title="Key Specifications"
          copyId="component-browser.key-specs-title"
          count={workspace.specifications.total}
          onViewAll={() => onOpenTab("specifications")}
        >
          {rows.length === 0 ? (
            <Empty id="component-browser.key-specs-empty">No specifications on record.</Empty>
          ) : (
            <dl className="min-h-0 overflow-hidden">
              {rows.map((row) => (
                <div
                  key={row.key}
                  className="flex items-baseline gap-2 border-b border-line/60 py-1 last:border-b-0"
                >
                  <dt className="min-w-0 flex-1 truncate text-2xs text-t2" title={row.label}>
                    {row.label}
                  </dt>
                  <dd className="tnum flex-none font-mono text-2xs font-semibold text-t1">
                    {row.unit ? `${row.value} ${row.unit}` : row.value}
                  </dd>
                  {isCuratedOnly(effective, pinned, category, row.key) ? null : (
                    <button
                      type="button"
                      data-dev-id="component-browser.key-spec-pin"
                      aria-pressed={isPinned(pinned, category, row.id ?? row.key)}
                      aria-label={
                        isPinned(pinned, category, row.id ?? row.key)
                          ? `Unpin ${row.label}`
                          : `Pin ${row.label}`
                      }
                      onClick={() => onTogglePin(category, row.id ?? row.key)}
                      className="flex-none rounded-control px-1 text-2xs text-t3 transition-colors hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc"
                    >
                      {isPinned(pinned, category, row.id ?? row.key) ? (
                        <Text id="component-browser.spec-pinned">Pinned</Text>
                      ) : (
                        <Text id="component-browser.spec-pin">Pin</Text>
                      )}
                    </button>
                  )}
                </div>
              ))}
            </dl>
          )}
        </Region>

        <Region
          devId="component-browser.attention"
          title="Needs Attention"
          copyId="component-browser.attention-title"
          count={attention.length}
        >
          {attention.length === 0 ? (
            <Empty id="component-browser.attention-empty">Nothing needs attention.</Empty>
          ) : (
            <ul className="min-h-0 overflow-hidden">
              {attention.slice(0, ATTENTION_LIMIT).map((item) => (
                <li
                  key={item.id}
                  data-dev-id="component-browser.attention-item"
                  className="flex items-start gap-2 border-b border-line/60 py-1.5 last:border-b-0"
                >
                  <span className="mt-1 flex-none">
                    <Dot tone={SEVERITY_TONE[item.severity] ?? "neutral"} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-2xs font-medium text-t1" title={item.title}>
                      {item.title}
                    </span>
                    <span className="block truncate text-2xs text-t3" title={item.detail}>
                      {item.detail}
                    </span>
                  </span>
                  <button
                    type="button"
                    data-dev-id="component-browser.attention-action"
                    onClick={() => onAttentionAction(item.action)}
                    aria-label={`${item.title}: ${item.action}`}
                    className="flex-none rounded-control px-1.5 py-0.5 text-2xs font-medium text-acc transition-colors hover:brightness-125 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc"
                  >
                    <Text id="component-browser.attention-resolve">Resolve</Text>
                  </button>
                </li>
              ))}
              {attention.length > ATTENTION_LIMIT ? (
                <li className="py-1 text-2xs text-t3">
                  {`${attention.length - ATTENTION_LIMIT} more`}
                </li>
              ) : null}
            </ul>
          )}
        </Region>

        <Region
          devId="component-browser.sourcing-snapshot"
          title="Sourcing Snapshot"
          copyId="component-browser.sourcing-snapshot-title"
          count={offers.length}
          onViewAll={() => onOpenTab("sourcing")}
          viewAllLabel="View Full Sourcing"
          viewAllCopyId="component-browser.sourcing-snapshot-all"
          viewAllDevId="component-browser.sourcing-snapshot-all"
        >
          {offers.length === 0 ? (
            <Empty id="component-browser.sourcing-snapshot-empty">No distributor offers on record.</Empty>
          ) : (
            <ul className="min-h-0 overflow-hidden">
              {offers.slice(0, SNAPSHOT_OFFERS).map((offer) => (
                <li
                  key={`${offer.sourceId}:${offer.partNumber}`}
                  className="flex items-baseline gap-2 border-b border-line/60 py-1 last:border-b-0"
                >
                  <span className="min-w-0 flex-1 truncate text-2xs text-t1">
                    {offer.sourceLabel || offer.sourceId}
                  </span>
                  <span className="tnum flex-none font-mono text-2xs text-t2">
                    {offer.stock === null ? noStock : `${offer.stock.toLocaleString()} ${inStock}`}
                  </span>
                  <span className="tnum flex-none font-mono text-2xs font-semibold text-t1">
                    {bestPrice(offer.priceBreaks, offer.currency, noPrice)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Region>
      </div>
    </div>
  );
}

/** The lowest quoted unit price, or an honest blank. Never a computed "from" price nobody quoted. */
function bestPrice(
  breaks: Array<{ qty: number | null; price: number | null }>,
  currency: string,
  absent: string,
): string {
  const prices = breaks.map((entry) => entry.price).filter((price): price is number => price != null);
  if (prices.length === 0) return absent;
  return `${currency || ""}${Math.min(...prices).toFixed(4)}`.trim();
}
