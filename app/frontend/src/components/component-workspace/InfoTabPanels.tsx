/**
 * Specifications, Sourcing, and Sources & History as COMPACT panels.
 *
 * These live inside the workspace's fixed viewport, which never scrolls, so each one is a SUMMARY
 * by contract: real counts from the projection, the pins a person chose to keep in view, two or
 * three representative facts per populated group, and per-source outcomes - then a View All that
 * hands the exhaustive sheet to a modal, which is the only surface here allowed a scrollbar.
 *
 * The temptation each of these resists is rendering "just a few more rows". A compact tab that
 * grows into a long sheet does not become more useful, it becomes a second, worse copy of the
 * modal - and it pushes the representation dock off the screen on the way.
 */
import type {
  ComponentFact,
  ComponentWorkspaceResponse,
  SpecificationGroupView,
} from "../../api/workspaceTypes";
import { Text, useText } from "../../lib/copy";
import { isPinned, type PinnedSpecs } from "../../lib/keySpecs";
import { Badge, EmptyState, Region } from "../primitives";

import { SOURCE_STATE_LABEL, sourceStateOf, sourceStateTone } from "./workspaceStatus";

const GRID =
  "grid min-h-0 flex-1 auto-rows-fr grid-cols-1 gap-2 overflow-hidden @2xl:auto-rows-auto @2xl:grid-cols-3";

/** How many facts a compact group line stands for. Beyond this the modal is the honest answer. */
export const REPRESENTATIVE_FACTS = 2;
/** How many groups the compact list names before it starts counting the rest. */
const COMPACT_GROUPS = 4;
/** How many pinned facts the compact tab keeps in view. */
const COMPACT_PINS = 2;
/** How many pins the compact pinout region names. */
const COMPACT_PINS_SHOWN = 3;

/** The one-line stand-in for a group: its first few facts, "Label Value", never the whole group. */
export function representativeLine(group: SpecificationGroupView): string {
  return group.facts
    .slice(0, REPRESENTATIVE_FACTS)
    .map((fact) => `${fact.label} ${fact.formattedValue}`.trim())
    .join(" · ");
}

export function SpecificationsTab({
  workspace,
  pinned,
  onViewAll,
}: {
  workspace: ComponentWorkspaceResponse;
  pinned: PinnedSpecs;
  onViewAll: () => void;
}) {
  const { groups, total, pinCount, pinout } = workspace.specifications;
  const category = workspace.identity.category;
  const pinsRecorded = useText("component-browser.pins-recorded", "pins recorded");
  const moreGroups = useText("component-browser.more-groups", "more groups");
  const pinnedFacts: ComponentFact[] = groups
    .flatMap((group) => group.facts)
    .filter((fact) => isPinned(pinned, category, fact.id))
    .slice(0, COMPACT_PINS);

  return (
    <div className={GRID}>
      <Region
        devId="component-browser.specifications"
        title="Specification Groups"
        copyId="component-browser.specifications-title"
        count={total}
        onViewAll={onViewAll}
        viewAllLabel="View All Specifications"
        viewAllDevId="component-browser.specifications-all"
        viewAllCopyId="component-browser.specifications-all"
      >
        {groups.length === 0 ? (
          <EmptyState dense id="component-browser.specifications-empty">No specifications on record.</EmptyState>
        ) : (
          <ul className="min-h-0 overflow-hidden">
            {pinnedFacts.map((fact) => (
              <li
                key={`pin:${fact.id}`}
                className="flex items-baseline gap-2 border-b border-line/60 py-1"
              >
                <span className="min-w-0 flex-1 truncate text-2xs text-t1">{fact.label}</span>
                <span className="tnum flex-none font-mono text-2xs font-semibold text-t1">
                  {fact.formattedValue}
                </span>
                <Badge size="sm" tone="neutral">
                  <Text id="component-browser.spec-pinned">Pinned</Text>
                </Badge>
              </li>
            ))}
            {groups.slice(0, COMPACT_GROUPS).map((group) => (
              <li key={group.id} className="border-b border-line/60 py-1 last:border-b-0">
                <span className="flex items-baseline gap-2">
                  <span className="min-w-0 flex-1 truncate text-2xs text-t1">{group.label}</span>
                  <span className="tnum flex-none font-mono text-2xs text-t2">{group.count}</span>
                </span>
                {/* Two facts stand for the group. Rendering them all is what the modal is for. */}
                <span className="block truncate text-2xs text-t3" title={representativeLine(group)}>
                  {representativeLine(group)}
                </span>
              </li>
            ))}
            {groups.length > COMPACT_GROUPS ? (
              <li className="py-1 text-2xs text-t3">
                {`${groups.length - COMPACT_GROUPS} ${moreGroups}`}
              </li>
            ) : null}
          </ul>
        )}
      </Region>
      <Region
        devId="component-browser.pinout"
        title="Pinout"
        copyId="component-browser.pinout-title"
        count={pinCount}
      >
        {pinCount === 0 ? (
          <EmptyState dense id="component-browser.pinout-empty">No pinout on record.</EmptyState>
        ) : (
          <div className="min-h-0 overflow-hidden">
            <p className="py-1 text-2xs text-t2">{`${pinCount} ${pinsRecorded}`}</p>
            <ul>
              {pinout.slice(0, COMPACT_PINS_SHOWN).map((entry, index) => (
                <li key={index} className="truncate py-0.5 font-mono text-2xs text-t3">
                  {Object.values(entry)
                    .filter((value) => value != null && typeof value !== "object")
                    .map(String)
                    .join(" ")}
                </li>
              ))}
            </ul>
          </div>
        )}
      </Region>
      <Region
        devId="component-browser.spec-conflicts"
        title="Disagreements"
        copyId="component-browser.spec-conflicts-title"
        count={conflictCount(workspace)}
      >
        {conflictCount(workspace) === 0 ? (
          <EmptyState dense id="component-browser.spec-conflicts-empty">Every source agrees.</EmptyState>
        ) : (
          <p className="py-2 text-2xs text-t2">
            <Text id="component-browser.spec-conflicts-body">
              Open the full sheet to see which source supplied each value.
            </Text>
          </p>
        )}
      </Region>
    </div>
  );
}

export function conflictCount(workspace: ComponentWorkspaceResponse): number {
  return workspace.specifications.groups
    .flatMap((group) => group.facts)
    .filter((fact) => fact.state === "conflict").length;
}

export function SourcingTab({
  workspace,
  onViewAll,
}: {
  workspace: ComponentWorkspaceResponse;
  onViewAll: () => void;
}) {
  const { offers, relationships, resources } = workspace.sourcing;
  const stockUnknown = useText("component-browser.stock-unknown", "Stock unknown");
  return (
    <div className={GRID}>
      <Region
        devId="component-browser.sourcing"
        title="Distributors"
        copyId="component-browser.sourcing-title"
        count={offers.length}
        onViewAll={onViewAll}
        viewAllLabel="View Full Sourcing"
        viewAllDevId="component-browser.sourcing-all"
        viewAllCopyId="component-browser.sourcing-all"
      >
        {offers.length === 0 ? (
          <EmptyState dense id="component-browser.sourcing-empty">No distributor offers on record.</EmptyState>
        ) : (
          <ul className="min-h-0 overflow-hidden">
            {offers.map((offer) => (
              <li
                key={`${offer.sourceId}:${offer.partNumber}`}
                className="flex items-baseline gap-2 border-b border-line/60 py-1 last:border-b-0"
              >
                <span className="min-w-0 flex-1 truncate text-2xs text-t1">
                  {offer.sourceLabel || offer.sourceId}
                </span>
                <span className="tnum flex-none font-mono text-2xs text-t2">
                  {offer.stock === null ? stockUnknown : offer.stock.toLocaleString()}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Region>
      <Region
        devId="component-browser.relationships"
        title="Related Parts"
        copyId="component-browser.relationships-title"
        count={relationships.reduce((total, group) => total + group.count, 0)}
      >
        {relationships.length === 0 ? (
          <EmptyState dense id="component-browser.relationships-empty">No related parts were offered.</EmptyState>
        ) : (
          <ul className="min-h-0 overflow-hidden">
            {relationships.map((group) => (
              <li
                key={group.id}
                className="flex items-baseline gap-2 border-b border-line/60 py-1 last:border-b-0"
              >
                <span className="min-w-0 flex-1 truncate text-2xs text-t1">{group.label}</span>
                <span className="tnum flex-none font-mono text-2xs text-t2">{group.count}</span>
              </li>
            ))}
          </ul>
        )}
      </Region>
      <Region
        devId="component-browser.resources"
        title="Documents"
        copyId="component-browser.resources-title"
        count={resources.length}
      >
        {resources.length === 0 ? (
          <EmptyState dense id="component-browser.resources-empty">No documents were offered.</EmptyState>
        ) : (
          <ul className="min-h-0 overflow-hidden">
            {resources.map((resource) => (
              <li key={`${resource.sourceId}:${resource.url}`} className="truncate py-1 text-2xs text-t1">
                {resource.title}
              </li>
            ))}
          </ul>
        )}
      </Region>
    </div>
  );
}

export function SourcesTab({
  workspace,
  revisionCount,
  onViewAll,
}: {
  workspace: ComponentWorkspaceResponse;
  /** The component's commit count, or null while the timeline has not answered. */
  revisionCount: number | null;
  onViewAll: () => void;
}) {
  const { fields, records, diagnostics } = workspace.sources;
  const unknown = useText("component-browser.unknown", "unknown");
  const derivedBy = useText("component-browser.derived-by", "Derived by");
  const derivedAt = useText("component-browser.derived-at", "Derived at");
  const schemaVersion = useText("component-browser.schema-version", "Schema version");
  const revisions = useText("component-browser.revisions", "Revisions");
  const disagreements = useText("component-browser.disagreements", "Disagreements");
  const attributed = useText("component-browser.attributed", "attributed");
  const newerBuild = useText(
    "component-browser.unknown-keys",
    "keys written by a newer build",
  );
  const conflicts = fields.filter((field) => field.state === "conflict").length;

  return (
    <div className={GRID}>
      <Region
        devId="component-browser.sources"
        title="Source Records"
        copyId="component-browser.sources-title"
        count={records.length}
        onViewAll={onViewAll}
        viewAllDevId="component-browser.sources-all"
        viewAllCopyId="component-browser.sources-all"
      >
        {records.length === 0 ? (
          <EmptyState dense id="component-browser.sources-empty">No captured source records.</EmptyState>
        ) : (
          <ul className="min-h-0 overflow-hidden">
            {records.map((record) => {
              const state = sourceStateOf(record.state);
              return (
                <li
                  key={record.id}
                  data-dev-id="component-browser.source-state"
                  className="flex items-baseline gap-2 border-b border-line/60 py-1 last:border-b-0"
                >
                  <span className="min-w-0 flex-1 truncate text-2xs text-t1">{record.label}</span>
                  <span className="tnum flex-none font-mono text-2xs text-t3">
                    {`${record.fieldCount ?? 0} ${attributed}`}
                  </span>
                  <Badge size="sm" tone={sourceStateTone(state)}>
                    {SOURCE_STATE_LABEL[state]}
                  </Badge>
                </li>
              );
            })}
          </ul>
        )}
      </Region>
      <Region
        devId="component-browser.field-sources"
        title="Attributed Fields"
        copyId="component-browser.field-sources-title"
        count={fields.length}
      >
        {fields.length === 0 ? (
          <EmptyState dense id="component-browser.field-sources-empty">No field carries an attribution.</EmptyState>
        ) : (
          <ul className="min-h-0 overflow-hidden text-2xs text-t2">
            <li className="truncate py-1">{`${disagreements} ${conflicts}`}</li>
            {fields.slice(0, 4).map((field) => (
              <li
                key={field.id}
                className="flex items-baseline gap-2 border-b border-line/60 py-1 last:border-b-0"
              >
                <span className="min-w-0 flex-1 truncate text-t1">{field.label}</span>
                <span className="flex-none truncate text-t3">
                  {field.source?.label ?? <Text id="component-browser.manual">Manual</Text>}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Region>
      <Region
        devId="component-browser.diagnostics"
        title="Diagnostics"
        copyId="component-browser.diagnostics-title"
        count={diagnostics.unknownKeys.length}
      >
        <ul className="min-h-0 overflow-hidden text-2xs text-t2">
          <li className="truncate py-1">{`${derivedBy} ${diagnostics.derivedBy || unknown}`}</li>
          <li className="truncate py-1">{`${derivedAt} ${diagnostics.derivedAt || unknown}`}</li>
          <li className="truncate py-1">{`${schemaVersion} ${diagnostics.schemaVersion}`}</li>
          <li className="truncate py-1">
            {`${revisions} ${revisionCount == null ? unknown : revisionCount}`}
          </li>
          {diagnostics.unknownKeys.length > 0 ? (
            <li className="truncate py-1 text-warn">
              {`${diagnostics.unknownKeys.length} ${newerBuild}`}
            </li>
          ) : null}
        </ul>
      </Region>
    </div>
  );
}
