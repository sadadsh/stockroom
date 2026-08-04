/**
 * Every provider's coverage of ONE component, in the order the backend ranked them.
 *
 * The screen answers one question: which provider can supply the whole set for this part - a
 * symbol, a footprint and a 3D model - so a person can go to that provider and come back with a
 * coherent download. Stockroom never combines files from two providers, so there is deliberately
 * NO per-artifact provider chooser here and there must never be one: what a row offers is a whole
 * set or an honest shortfall, and `complete` is the thing the eye should find first.
 *
 * Nothing is re-sorted: rows arrive ranked by evidence and are rendered in the given order. No
 * confidence percentages appear anywhere, because a number between 0 and 1 would only be an
 * opinion wearing a measurement's clothes.
 *
 * A person may correct two things and only two: whether a provider HAS an artifact, or does not.
 * "Downloaded" and "validated" are claims about bytes Stockroom is holding, so they are not
 * offered - the backend rejects them, and a control that could only produce a 422 is not a
 * control. When Stockroom's own evidence outranks a correction the row says so rather than
 * quietly discarding what the person said.
 */
import type {
  ComponentProvidersView,
  CoverageArtifact,
  CoverageStatus,
  ProviderCoverageRow,
} from "../../api/workspaceTypes";
import { providerToolCoverage } from "../../api/workspaceTypes";
import { componentProviderDevId } from "../../lib/componentDevIds";
import { Text, useText } from "../../lib/copy";
import { Badge, Button } from "../primitives";

/** The only two answers a person can give, plus withdrawing one they already gave. */
export type UserCoverageStatus = "available" | "not_available" | "";

const ARTIFACT_LABEL: Record<CoverageArtifact, string> = {
  symbol: "Symbol",
  footprint: "Footprint",
  model: "3D Model",
};

const TOOL_LABEL: Record<string, string> = {
  kicad: "KiCad",
  altium: "Altium",
};

const STATUS_LABEL: Record<CoverageStatus, string> = {
  unknown: "Unknown",
  available: "Available",
  not_available: "Not Available",
  downloaded: "Downloaded",
  validated: "Validated",
};

/** Statuses that mean "this provider supplies it". Mirrors the backend's SUPPLIED_STATUSES. */
const SUPPLIED: ReadonlySet<CoverageStatus> = new Set<CoverageStatus>([
  "available",
  "downloaded",
  "validated",
]);

function statusClass(status: CoverageStatus): string {
  if (status === "validated" || status === "downloaded") return "text-ok";
  if (status === "available") return "text-t1";
  if (status === "not_available") return "text-warn";
  return "text-t3";
}

export interface ProviderMatrixLabels {
  provider: string;
  action: string;
  statuses: Record<CoverageStatus, string>;
  artifacts: Record<CoverageArtifact, string>;
  completeSet: string;
  completeHint: string;
  partialHint: string;
  signIn: string;
  aggregator: string;
  yourAnswer: string;
  keepStockroom: string;
  sayAvailable: string;
  sayNotAvailable: string;
  evidenceWins: string;
  openProvider: string;
  noPage: string;
  searchPage: string;
  empty: string;
  toolNotOffered: string;
  tools: Record<string, string>;
}

/** Every user-visible string in the matrix, resolved once through the copy layer. */
export function useProviderMatrixLabels(): ProviderMatrixLabels {
  return {
    provider: useText("component-browser.provider-col-provider", "Provider"),
    action: useText("component-browser.provider-col-action", "Action"),
    statuses: {
      unknown: useText("component-browser.provider-status-unknown", STATUS_LABEL.unknown),
      available: useText("component-browser.provider-status-available", STATUS_LABEL.available),
      not_available: useText(
        "component-browser.provider-status-not-available",
        STATUS_LABEL.not_available,
      ),
      downloaded: useText("component-browser.provider-status-downloaded", STATUS_LABEL.downloaded),
      validated: useText("component-browser.provider-status-validated", STATUS_LABEL.validated),
    },
    artifacts: {
      symbol: useText("component-browser.provider-col-symbol", ARTIFACT_LABEL.symbol),
      footprint: useText("component-browser.provider-col-footprint", ARTIFACT_LABEL.footprint),
      model: useText("component-browser.provider-col-model", ARTIFACT_LABEL.model),
    },
    completeSet: useText("component-browser.provider-complete", "Complete Set"),
    completeHint: useText(
      "component-browser.provider-complete-hint",
      "This provider can supply the symbol, the footprint and the 3D model for this component.",
    ),
    partialHint: useText(
      "component-browser.provider-partial-hint",
      "This provider cannot supply the whole set for this component.",
    ),
    signIn: useText("component-browser.provider-sign-in", "Sign In Needed"),
    aggregator: useText("component-browser.provider-aggregator", "Aggregator"),
    yourAnswer: useText("component-browser.provider-your-answer", "Your Answer"),
    keepStockroom: useText(
      "component-browser.provider-answer-keep",
      "Use Stockroom's Answer",
    ),
    sayAvailable: useText("component-browser.provider-answer-available", "Available"),
    sayNotAvailable: useText(
      "component-browser.provider-answer-not-available",
      "Not Available",
    ),
    evidenceWins: useText(
      "component-browser.provider-evidence-wins",
      "Your answer is recorded but not applied. Stockroom holds a file for this artifact, so its own evidence stands:",
    ),
    openProvider: useText("component-browser.provider-open-label", "Open Provider"),
    noPage: useText(
      "component-browser.provider-no-page",
      "No page is on record for this provider and this component.",
    ),
    searchPage: useText(
      "component-browser.provider-search-page",
      "Opens this provider's search for the part number. You choose the formats and download.",
    ),
    empty: useText(
      "component-browser.provider-empty",
      "No providers are registered for this component.",
    ),
    toolNotOffered: useText(
      "component-browser.provider-tool-not-offered",
      "This provider does not export for this tool.",
    ),
    // The registered tools, by key. A tool the backend adds later still gets a column: it falls
    // back to its own key rather than to a blank header.
    tools: {
      kicad: useText("component-browser.provider-col-kicad", TOOL_LABEL.kicad),
      altium: useText("component-browser.provider-col-altium", TOOL_LABEL.altium),
    },
  };
}

export function ProviderCoverageMatrix({
  componentId,
  coverage,
  labels,
  onOpenProvider,
  onCorrect,
  openDisabledReason = "",
  correcting = null,
}: {
  componentId: string;
  coverage: ComponentProvidersView;
  labels: ProviderMatrixLabels;
  /** The person goes to the provider; Stockroom only opens the page they asked for. */
  onOpenProvider: (row: ProviderCoverageRow) => void;
  onCorrect: (
    row: ProviderCoverageRow,
    artifact: CoverageArtifact,
    status: UserCoverageStatus,
  ) => void;
  /** Why Open Provider is unavailable right now, independent of whether a page exists. */
  openDisabledReason?: string;
  /** The one correction currently in flight, so the row it belongs to can say so. */
  correcting?: { provider: string; artifact: CoverageArtifact } | null;
}) {
  if (coverage.rows.length === 0) {
    return (
      <p data-dev-id="component-browser.provider-matrix" className="py-2 text-2xs text-t3">
        {labels.empty}
      </p>
    );
  }

  return (
    // Wide by construction: seven columns of real facts. It scrolls sideways INSIDE its own box
    // rather than widening the modal or the workspace behind it.
    <div data-dev-id="component-browser.provider-matrix" className="overflow-x-auto">
      <table className="w-full min-w-[760px] border-collapse text-left text-xs">
        <caption className="sr-only">
          <Text id="component-browser.provider-matrix-caption">
            Which provider can supply the whole CAD set for this component
          </Text>
        </caption>
        <thead className="text-2xs text-t3">
          <tr>
            <th scope="col" className="py-1 pr-3 font-medium">
              {labels.provider}
            </th>
            {coverage.artifacts.map((artifact) => (
              <th key={artifact} scope="col" className="py-1 pr-3 font-medium">
                {labels.artifacts[artifact]}
              </th>
            ))}
            {coverage.tools.map((tool) => (
              <th key={tool} scope="col" className="py-1 pr-3 font-medium">
                {labels.tools[tool] ?? tool}
              </th>
            ))}
            <th scope="col" className="py-1 font-medium">
              {labels.action}
            </th>
          </tr>
        </thead>
        <tbody className="text-t1">
          {coverage.rows.map((row) => (
            <ProviderRow
              key={row.id}
              componentId={componentId}
              row={row}
              tools={coverage.tools}
              artifacts={coverage.artifacts}
              labels={labels}
              onOpenProvider={onOpenProvider}
              onCorrect={onCorrect}
              openDisabledReason={openDisabledReason}
              correcting={correcting}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ProviderRow({
  componentId,
  row,
  tools,
  artifacts,
  labels,
  onOpenProvider,
  onCorrect,
  openDisabledReason,
  correcting,
}: {
  componentId: string;
  row: ProviderCoverageRow;
  tools: string[];
  artifacts: CoverageArtifact[];
  labels: ProviderMatrixLabels;
  onOpenProvider: (row: ProviderCoverageRow) => void;
  onCorrect: (
    row: ProviderCoverageRow,
    artifact: CoverageArtifact,
    status: UserCoverageStatus,
  ) => void;
  openDisabledReason: string;
  correcting: { provider: string; artifact: CoverageArtifact } | null;
}) {
  const reachable = row.url !== "";
  return (
    <tr
      data-dev-id={componentProviderDevId(componentId, row.id)}
      data-provider={row.id}
      // A complete provider is the ANSWER to this screen, so it is marked three ways: a tinted
      // row, a leading accent rule, and a badge that says it in words. Colour alone would fail a
      // person who cannot see it.
      data-complete={row.complete}
      className={
        "border-t border-line align-top " + (row.complete ? "bg-ok/[0.07]" : "")
      }
    >
      <th scope="row" className="py-2 pr-3 text-left font-normal">
        <span className="flex min-w-0 items-start gap-2">
          <span
            aria-hidden
            className={
              "mt-0.5 w-0.5 flex-none self-stretch rounded-control " +
              (row.complete ? "bg-ok" : "bg-transparent")
            }
          />
          <span className="min-w-0">
            <span
              className="block truncate text-xs font-semibold text-t1"
              title={row.instruction || row.label}
            >
              {row.label}
            </span>
            <span className="mt-1 flex flex-wrap items-center gap-1">
              {row.complete ? (
                <Badge tone="ok" size="sm" title={labels.completeHint}>
                  {labels.completeSet}
                </Badge>
              ) : (
                <span className="text-2xs text-t3" title={labels.partialHint}>
                  {row.statusCounts.validated +
                    row.statusCounts.downloaded +
                    row.statusCounts.available}
                  /{artifacts.length}
                </span>
              )}
              {row.needsLogin ? (
                <Badge tone="neutral" size="sm">
                  {labels.signIn}
                </Badge>
              ) : null}
              {row.aggregator ? (
                <Badge tone="neutral" size="sm">
                  {labels.aggregator}
                </Badge>
              ) : null}
            </span>
          </span>
        </span>
      </th>

      {artifacts.map((artifact) => (
        <td key={artifact} className="py-2 pr-3">
          <ArtifactCell
            row={row}
            artifact={artifact}
            labels={labels}
            onCorrect={onCorrect}
            busy={correcting?.provider === row.id && correcting.artifact === artifact}
          />
        </td>
      ))}

      {tools.map((tool) => {
        const cell = providerToolCoverage(row, tool);
        return (
          <td key={tool} className="py-2 pr-3">
            <span
              className={
                "tnum font-mono text-2xs " +
                (cell?.complete ? "font-semibold text-ok" : "text-t2")
              }
              title={cell && !cell.supported ? labels.toolNotOffered : undefined}
            >
              {cell?.summary ?? ""}
            </span>
          </td>
        );
      })}

      <td className="py-2">
        <Button
          type="button"
          data-dev-id="component-browser.provider-open"
          small
          variant={row.complete ? "accent" : "default"}
          disabled={!reachable || openDisabledReason !== ""}
          aria-label={`${labels.openProvider}: ${row.label}`}
          title={
            !reachable
              ? labels.noPage
              : openDisabledReason !== ""
                ? openDisabledReason
                : row.urlKind === "search"
                  ? labels.searchPage
                  : undefined
          }
          onClick={() => onOpenProvider(row)}
        >
          {labels.openProvider}
        </Button>
        {/* A disabled control has to SAY why, in the row. A `title` on a disabled button is
            unreachable by keyboard and unannounced by a screen reader, so the reason a trip is
            unavailable was visible for one cause (no page) and invisible for the other. */}
        {!reachable ? (
          <span className="mt-1 block max-w-[15rem] text-2xs leading-snug text-t3">
            {labels.noPage}
          </span>
        ) : openDisabledReason !== "" ? (
          <span className="mt-1 block max-w-[15rem] text-2xs leading-snug text-t3">
            {openDisabledReason}
          </span>
        ) : null}
      </td>
    </tr>
  );
}

function ArtifactCell({
  row,
  artifact,
  labels,
  onCorrect,
  busy,
}: {
  row: ProviderCoverageRow;
  artifact: CoverageArtifact;
  labels: ProviderMatrixLabels;
  onCorrect: (
    row: ProviderCoverageRow,
    artifact: CoverageArtifact,
    status: UserCoverageStatus,
  ) => void;
  busy: boolean;
}) {
  const cell = row[artifact];
  const assertion = cell.userAssertion;
  const overruled = assertion !== null && assertion.applied === false;
  return (
    <span className="flex min-w-0 flex-col gap-1">
      <span
        className={"text-2xs font-medium " + statusClass(cell.status)}
        data-status={cell.status}
        data-supplied={SUPPLIED.has(cell.status)}
      >
        {labels.statuses[cell.status]}
      </span>
      <select
        data-dev-id="component-browser.provider-assert"
        aria-label={`${labels.yourAnswer}: ${row.label} ${labels.artifacts[artifact]}`}
        value={assertion?.status === "available" || assertion?.status === "not_available"
          ? assertion.status
          : ""}
        disabled={busy}
        onChange={(event) =>
          onCorrect(row, artifact, event.target.value as UserCoverageStatus)
        }
        className="h-6 w-full min-w-[8.5rem] rounded-control border border-line bg-field px-1.5 text-2xs text-t2 outline-none focus:border-acc disabled:opacity-50"
      >
        <option value="">{labels.keepStockroom}</option>
        <option value="available">{labels.sayAvailable}</option>
        <option value="not_available">{labels.sayNotAvailable}</option>
      </select>
      {overruled ? (
        <span
          data-overruled="true"
          className="max-w-[13rem] text-2xs leading-snug text-warn"
        >
          {`${labels.evidenceWins} ${labels.statuses[cell.status]}.`}
        </span>
      ) : null}
    </span>
  );
}
