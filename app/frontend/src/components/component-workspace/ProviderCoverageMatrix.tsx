/**
 * Compare Sources: every provider's coverage of ONE component, as a dense table.
 *
 * Five columns of facts - `Provider | Symbol | Footprint | 3D Model | Validation` - and one
 * action. Never a card per provider: a person comparing eight providers is scanning a column,
 * and eight stacked panels turn one comparison into eight readings of the same four fields.
 *
 * The screen answers one question: which provider can supply the whole set for this part, so a
 * person can go there and come back with a coherent download. Stockroom never combines files
 * from two providers, and this table does not offer a way to: the SET choice is the primary
 * control, a per-asset choice exists because pinning one artifact is a legitimate thing to want,
 * and a per-asset choice that would leave two providers in force is offered DISABLED with the
 * reason on it rather than accepted and refused afterwards.
 *
 * No EDA application is named here. The two per-tool count columns this replaces put `KiCad` and
 * `Altium` in the middle of an ordinary comparison, which is a compatibility report wearing a
 * coverage table's clothes. What a person compares is availability, validation and source; which
 * application can open the result belongs behind an explicit export action.
 *
 * Nothing is re-sorted: rows arrive ranked by evidence and are rendered in the given order. No
 * confidence percentages appear anywhere, because a number between 0 and 1 would only be an
 * opinion wearing a measurement's clothes.
 *
 * A person may correct two things and only two: whether a provider HAS an artifact, or does not.
 * "Downloaded" and "validated" are claims about bytes Stockroom is holding, so they are not
 * offered. When Stockroom's own evidence outranks a correction the row says so rather than
 * quietly discarding what the person said.
 */
import type {
  CadPreferenceOption,
  CadPreferenceView,
  ComponentProvidersView,
  CoverageArtifact,
  CoverageStatus,
  ProviderCoverageRow,
} from "../../api/dossierTypes";
import { componentProviderDevId } from "../../lib/componentDevIds";
import { Text, useText } from "../../lib/copy";
import { Button } from "../primitives";
import { StatusText, type StatusTone } from "../typography";

/** The only two answers a person can give, plus withdrawing one they already gave. */
export type UserCoverageStatus = "available" | "not_available" | "";

const ARTIFACT_LABEL: Record<CoverageArtifact, string> = {
  symbol: "Symbol",
  footprint: "Footprint",
  model: "3D Model",
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

/**
 * The tone a status carries. Semantic only where it means something: a file we hold and checked
 * is good news, a provider that says it has nothing is a warning, and silence is neutral.
 */
function statusTone(status: CoverageStatus): StatusTone {
  if (status === "validated" || status === "downloaded") return "ok";
  if (status === "not_available") return "warn";
  return "neutral";
}

export interface ProviderMatrixLabels {
  provider: string;
  action: string;
  validation: string;
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
  useForSet: string;
  useForAsset: string;
  inForce: string;
  nothingValidated: string;
  validatedCount: string;
}

/** Every user-visible string in the matrix, resolved once through the copy layer. */
export function useProviderMatrixLabels(): ProviderMatrixLabels {
  return {
    provider: useText("component-browser.provider-col-provider", "Provider"),
    action: useText("component-browser.provider-col-action", "Action"),
    validation: useText("component-browser.provider-col-validation", "Validation"),
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
    keepStockroom: useText("component-browser.provider-answer-keep", "Use Stockroom's Answer"),
    sayAvailable: useText("component-browser.provider-answer-available", "Available"),
    sayNotAvailable: useText("component-browser.provider-answer-not-available", "Not Available"),
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
    useForSet: useText("component-browser.provider-use-set", "Use For The Whole Set"),
    useForAsset: useText("component-browser.provider-use-asset", "Prefer This Source"),
    inForce: useText("component-browser.provider-in-force", "Preferred"),
    nothingValidated: useText("component-browser.provider-none-validated", "Nothing checked yet"),
    validatedCount: useText("component-browser.provider-validated-count", "checked and passed"),
  };
}

export function ProviderCoverageMatrix({
  componentId,
  coverage,
  preference,
  labels,
  onOpenProvider,
  onCorrect,
  onPreferSet,
  onPreferAsset,
  openDisabledReason = "",
  correcting = null,
  preferring = false,
}: {
  componentId: string;
  coverage: ComponentProvidersView;
  /** What is in force and what each choice would replace, already planned by the backend. */
  preference: CadPreferenceView;
  labels: ProviderMatrixLabels;
  /** The person goes to the provider; Stockroom only opens the page they asked for. */
  onOpenProvider: (row: ProviderCoverageRow) => void;
  onCorrect: (
    row: ProviderCoverageRow,
    artifact: CoverageArtifact,
    status: UserCoverageStatus,
  ) => void;
  onPreferSet: (provider: string) => void;
  onPreferAsset: (asset: CoverageArtifact, provider: string) => void;
  /** Why Open Provider is unavailable right now, independent of whether a page exists. */
  openDisabledReason?: string;
  /** The one correction currently in flight, so the row it belongs to can say so. */
  correcting?: { provider: string; artifact: CoverageArtifact } | null;
  preferring?: boolean;
}) {
  if (coverage.rows.length === 0) {
    return (
      <p data-dev-id="component-browser.provider-matrix" className="ui-row-secondary py-2">
        {labels.empty}
      </p>
    );
  }

  const options = new Map(preference.options.map((option) => [option.provider, option]));

  return (
    // Wide by construction: six columns of real facts. It scrolls sideways INSIDE its own box
    // rather than widening the modal or the workspace behind it.
    <div data-dev-id="component-browser.provider-matrix" className="overflow-x-auto">
      <table className="w-full min-w-[720px] border-collapse text-left">
        <caption className="sr-only">
          <Text id="component-browser.provider-matrix-caption">
            Which provider can supply the whole CAD set for this component
          </Text>
        </caption>
        <thead>
          <tr>
            <th scope="col" className="ui-table-header py-1 pr-3">
              {labels.provider}
            </th>
            {coverage.artifacts.map((artifact) => (
              <th key={artifact} scope="col" className="ui-table-header py-1 pr-3">
                {labels.artifacts[artifact]}
              </th>
            ))}
            <th scope="col" className="ui-table-header py-1 pr-3">
              {labels.validation}
            </th>
            <th scope="col" className="ui-table-header py-1">
              {labels.action}
            </th>
          </tr>
        </thead>
        <tbody>
          {coverage.rows.map((row) => (
            <ProviderRow
              key={row.id}
              componentId={componentId}
              row={row}
              option={options.get(row.id) ?? null}
              artifacts={coverage.artifacts}
              labels={labels}
              onOpenProvider={onOpenProvider}
              onCorrect={onCorrect}
              onPreferSet={onPreferSet}
              onPreferAsset={onPreferAsset}
              openDisabledReason={openDisabledReason}
              correcting={correcting}
              preferring={preferring}
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
  option,
  artifacts,
  labels,
  onOpenProvider,
  onCorrect,
  onPreferSet,
  onPreferAsset,
  openDisabledReason,
  correcting,
  preferring,
}: {
  componentId: string;
  row: ProviderCoverageRow;
  option: CadPreferenceOption | null;
  artifacts: CoverageArtifact[];
  labels: ProviderMatrixLabels;
  onOpenProvider: (row: ProviderCoverageRow) => void;
  onCorrect: (
    row: ProviderCoverageRow,
    artifact: CoverageArtifact,
    status: UserCoverageStatus,
  ) => void;
  onPreferSet: (provider: string) => void;
  onPreferAsset: (asset: CoverageArtifact, provider: string) => void;
  openDisabledReason: string;
  correcting: { provider: string; artifact: CoverageArtifact } | null;
  preferring: boolean;
}) {
  const reachable = row.url !== "";
  const set = option?.set ?? null;
  return (
    <tr
      // One row per provider, so the row names the provider it IS and the class it belongs to.
      data-dev-id={componentProviderDevId(componentId, row.id)}
      data-dev-role="component-browser.provider-row"
      data-provider={row.id}
      // A complete provider is the ANSWER to this screen, so it is marked three ways: a tinted
      // row, a leading accent rule, and a word. Colour alone would fail a person who cannot see it.
      data-complete={row.complete}
      data-preferred={set?.current ?? false}
      className={"border-t border-line align-top " + (row.complete ? "bg-ok/[0.07]" : "")}
    >
      <th scope="row" className="py-1.5 pr-3 text-left font-normal">
        <span className="flex min-w-0 items-start gap-2">
          <span
            aria-hidden
            className={
              "mt-0.5 w-0.5 flex-none self-stretch " + (row.complete ? "bg-ok" : "bg-transparent")
            }
          />
          <span className="min-w-0">
            <span className="ui-row-primary block truncate" title={row.instruction || row.label}>
              {row.label}
            </span>
            <span className="mt-0.5 flex flex-wrap items-center gap-1.5">
              <StatusText tone={row.complete ? "ok" : "neutral"}>
                {row.complete ? (
                  <span title={labels.completeHint}>{labels.completeSet}</span>
                ) : (
                  <span title={labels.partialHint}>
                    {`${row.statusCounts.validated + row.statusCounts.downloaded + row.statusCounts.available}/${artifacts.length}`}
                  </span>
                )}
              </StatusText>
              {row.needsLogin ? (
                <StatusText tone="neutral">{labels.signIn}</StatusText>
              ) : null}
              {row.aggregator ? (
                <StatusText tone="neutral">{labels.aggregator}</StatusText>
              ) : null}
            </span>
            {/* The SET choice: the primary control, on the provider itself, because the whole
                table exists to answer "which provider supplies everything". */}
            {set ? (
              <label className="mt-1 flex items-center gap-1.5">
                <input
                  type="radio"
                  data-dev-id="component-browser.provider-prefer-set"
                  name={`cad-preferred-source-${componentId}`}
                  checked={set.current}
                  disabled={!set.allowed || preferring}
                  aria-label={`${labels.useForSet}: ${row.label}`}
                  title={set.allowed ? labels.useForSet : set.reason}
                  onChange={() => onPreferSet(row.id)}
                  className="h-3 w-3 flex-none accent-[var(--c-t1)]"
                />
                <span className="ui-control-label text-t2">
                  {set.current ? labels.inForce : labels.useForSet}
                </span>
              </label>
            ) : null}
            {/* A disabled control has to SAY why, in the row: a `title` on a disabled input is
                unreachable by keyboard and unannounced by a screen reader. */}
            {set && !set.allowed && set.reason ? (
              <span className="ui-row-metadata mt-0.5 block max-w-[16rem] leading-snug">
                {set.reason}
              </span>
            ) : null}
          </span>
        </span>
      </th>

      {artifacts.map((artifact) => (
        <td key={artifact} className="py-1.5 pr-3">
          <ArtifactCell
            row={row}
            artifact={artifact}
            option={option}
            labels={labels}
            onCorrect={onCorrect}
            onPreferAsset={onPreferAsset}
            busy={correcting?.provider === row.id && correcting.artifact === artifact}
            preferring={preferring}
          />
        </td>
      ))}

      <td className="py-1.5 pr-3">
        <ValidationCell row={row} artifacts={artifacts} labels={labels} />
      </td>

      <td className="py-1.5">
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
        {!reachable ? (
          <span className="ui-row-metadata mt-1 block max-w-[15rem] leading-snug">
            {labels.noPage}
          </span>
        ) : openDisabledReason !== "" ? (
          <span className="ui-row-metadata mt-1 block max-w-[15rem] leading-snug">
            {openDisabledReason}
          </span>
        ) : null}
      </td>
    </tr>
  );
}

/**
 * What this provider proved, counted from the statuses it already carries.
 *
 * `validated` says Stockroom read the artifact and the inspection passed; `downloaded` says only
 * that we hold the bytes. Reporting them as one number would let an unchecked download read as a
 * verified one, which is the distinction the whole coverage vocabulary exists to keep.
 */
function ValidationCell({
  row,
  artifacts,
  labels,
}: {
  row: ProviderCoverageRow;
  artifacts: CoverageArtifact[];
  labels: ProviderMatrixLabels;
}) {
  const validated = row.statusCounts.validated;
  return (
    <span className="flex min-w-0 flex-col">
      <StatusText tone={validated > 0 ? "ok" : "neutral"} data-validated={validated}>
        {validated === 0
          ? labels.nothingValidated
          : `${validated}/${artifacts.length} ${labels.validatedCount}`}
      </StatusText>
      {row.statusCounts.downloaded > 0 ? (
        <span className="ui-row-metadata">
          {`${row.statusCounts.downloaded} ${labels.statuses.downloaded}`}
        </span>
      ) : null}
    </span>
  );
}

function ArtifactCell({
  row,
  artifact,
  option,
  labels,
  onCorrect,
  onPreferAsset,
  busy,
  preferring,
}: {
  row: ProviderCoverageRow;
  artifact: CoverageArtifact;
  option: CadPreferenceOption | null;
  labels: ProviderMatrixLabels;
  onCorrect: (
    row: ProviderCoverageRow,
    artifact: CoverageArtifact,
    status: UserCoverageStatus,
  ) => void;
  onPreferAsset: (asset: CoverageArtifact, provider: string) => void;
  busy: boolean;
  preferring: boolean;
}) {
  const cell = row[artifact];
  const assertion = cell.userAssertion;
  const overruled = assertion !== null && assertion.applied === false;
  const scope = option?.assets[artifact] ?? null;
  return (
    <span className="flex min-w-0 flex-col gap-1">
      <StatusText
        tone={statusTone(cell.status)}
        data-status={cell.status}
        data-supplied={SUPPLIED.has(cell.status)}
      >
        {labels.statuses[cell.status]}
      </StatusText>
      {/* The per-asset choice, offered only where the backend says it is legitimate - and
          offered DISABLED with its reason where it is not, so a refusal is visible before the
          click rather than arriving as an error after it. */}
      {scope ? (
        <button
          type="button"
          data-dev-id="component-browser.provider-prefer-asset"
          data-current={scope.current}
          disabled={!scope.allowed || scope.current || preferring}
          aria-pressed={scope.current}
          aria-label={`${labels.useForAsset}: ${row.label} ${labels.artifacts[artifact]}`}
          title={scope.allowed ? labels.useForAsset : scope.reason}
          onClick={() => onPreferAsset(artifact, row.id)}
          className={
            "ui-control-label h-[20px] rounded-control border border-line px-2 text-left " +
            "text-t2 hover:bg-control-hover disabled:opacity-50 disabled:hover:bg-transparent " +
            "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 " +
            "focus-visible:outline-focus " +
            (scope.current ? "bg-selected text-t1" : "")
          }
        >
          {scope.current ? labels.inForce : labels.useForAsset}
        </button>
      ) : null}
      <select
        data-dev-id="component-browser.provider-assert"
        aria-label={`${labels.yourAnswer}: ${row.label} ${labels.artifacts[artifact]}`}
        value={
          assertion?.status === "available" || assertion?.status === "not_available"
            ? assertion.status
            : ""
        }
        disabled={busy}
        onChange={(event) => onCorrect(row, artifact, event.target.value as UserCoverageStatus)}
        className={
          "ui-control-label h-[20px] w-full min-w-[8rem] rounded-control border border-line " +
          "bg-field px-1.5 text-t2 outline-none focus-visible:outline focus-visible:outline-2 " +
          "focus-visible:outline-offset-1 focus-visible:outline-focus disabled:opacity-50"
        }
      >
        <option value="">{labels.keepStockroom}</option>
        <option value="available">{labels.sayAvailable}</option>
        <option value="not_available">{labels.sayNotAvailable}</option>
      </select>
      {overruled ? (
        <span
          data-overruled="true"
          className="ui-row-metadata max-w-[13rem] leading-snug text-warn"
        >
          {`${labels.evidenceWins} ${labels.statuses[cell.status]}.`}
        </span>
      ) : null}
    </span>
  );
}
