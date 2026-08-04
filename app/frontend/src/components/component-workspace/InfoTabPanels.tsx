/**
 * Specifications, Sourcing, and Sources & History as COMPACT panels.
 *
 * Each one renders the real projection - the actual groups, the actual distributors, the actual
 * source records and their counts - inside the same bounded region shell the Overview uses, and
 * hands the exhaustive view to a modal. The modals are deliberately shells in this slice: they
 * open, they are addressable, and they say what they will hold. The full sheets (per-fact
 * provenance, the price ladder, the substitution tables, the commit trail) are their own slice,
 * and shipping a half-built one here would put a second, worse specification sheet in the app
 * beside the one it is meant to replace.
 */
import type { ComponentWorkspaceResponse } from "../../api/workspaceTypes";
import { Text, useText } from "../../lib/copy";
import { Empty, Region } from "./WorkspaceRegion";

const GRID =
  "grid min-h-0 flex-1 auto-rows-fr grid-cols-1 gap-2 overflow-hidden @2xl:auto-rows-auto @2xl:grid-cols-3";

export function SpecificationsTab({
  workspace,
  onViewAll,
}: {
  workspace: ComponentWorkspaceResponse;
  onViewAll: () => void;
}) {
  const { groups, total, pinCount } = workspace.specifications;
  const pinsRecorded = useText("component-browser.pins-recorded", "pins recorded");
  return (
    <div className={GRID}>
      <Region
        devId="component-browser.specifications"
        title="Specification Groups"
        copyId="component-browser.specifications-title"
        count={total}
        onViewAll={onViewAll}
        viewAllDevId="component-browser.specifications-all"
        viewAllCopyId="component-browser.specifications-all"
      >
        {groups.length === 0 ? (
          <Empty id="component-browser.specifications-empty">No specifications on record.</Empty>
        ) : (
          <ul className="min-h-0 overflow-hidden">
            {groups.map((group) => (
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
        devId="component-browser.pinout"
        title="Pinout"
        copyId="component-browser.pinout-title"
        count={pinCount}
      >
        {pinCount === 0 ? (
          <Empty id="component-browser.pinout-empty">No pinout on record.</Empty>
        ) : (
          <p className="py-2 text-2xs text-t2">{`${pinCount} ${pinsRecorded}`}</p>
        )}
      </Region>
      <Region
        devId="component-browser.spec-conflicts"
        title="Disagreements"
        copyId="component-browser.spec-conflicts-title"
        count={conflictCount(workspace)}
      >
        {conflictCount(workspace) === 0 ? (
          <Empty id="component-browser.spec-conflicts-empty">Every source agrees.</Empty>
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

function conflictCount(workspace: ComponentWorkspaceResponse): number {
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
        viewAllDevId="component-browser.sourcing-all"
        viewAllCopyId="component-browser.sourcing-all"
      >
        {offers.length === 0 ? (
          <Empty id="component-browser.sourcing-empty">No distributor offers on record.</Empty>
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
          <Empty id="component-browser.relationships-empty">No related parts were offered.</Empty>
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
          <Empty id="component-browser.resources-empty">No documents were offered.</Empty>
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
  onViewAll,
}: {
  workspace: ComponentWorkspaceResponse;
  onViewAll: () => void;
}) {
  const { fields, records, diagnostics } = workspace.sources;
  const undated = useText("component-browser.undated", "Undated");
  const manual = useText("component-browser.manual", "Manual");
  const unknown = useText("component-browser.unknown", "unknown");
  const derivedBy = useText("component-browser.derived-by", "Derived by");
  const derivedAt = useText("component-browser.derived-at", "Derived at");
  const schemaVersion = useText("component-browser.schema-version", "Schema version");
  const newerBuild = useText(
    "component-browser.unknown-keys",
    "keys written by a newer build",
  );
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
          <Empty id="component-browser.sources-empty">No captured source records.</Empty>
        ) : (
          <ul className="min-h-0 overflow-hidden">
            {records.map((record) => (
              <li
                key={record.id}
                className="flex items-baseline gap-2 border-b border-line/60 py-1 last:border-b-0"
              >
                <span className="min-w-0 flex-1 truncate text-2xs text-t1">{record.label}</span>
                <span className="flex-none text-2xs text-t3">{record.fetchedAt || undated}</span>
              </li>
            ))}
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
          <Empty id="component-browser.field-sources-empty">No field carries an attribution.</Empty>
        ) : (
          <ul className="min-h-0 overflow-hidden">
            {fields.map((field) => (
              <li
                key={field.id}
                className="flex items-baseline gap-2 border-b border-line/60 py-1 last:border-b-0"
              >
                <span className="min-w-0 flex-1 truncate text-2xs text-t1">{field.label}</span>
                <span className="flex-none truncate text-2xs text-t3">
                  {field.source?.label ?? manual}
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
