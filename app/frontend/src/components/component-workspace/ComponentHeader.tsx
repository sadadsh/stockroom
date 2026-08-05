/**
 * The opened component's identity header: four lines, one lifecycle state, one quality summary,
 * and four actions. Not a hero.
 *
 * The owner's diagnosis was that the surface treated "the MPN, generated name, manufacturer
 * description, metadata, statuses, and actions as though they have equal authority". This is where
 * that is settled. The MPN takes the only 14px on the screen; the generated display name is never
 * placed before it and never outranks it; the manufacturer's description is prose at body weight;
 * classification and key facts are metadata; the lifecycle is a STATE aligned in its own slot, not
 * a suffix on the part number; and the actions are four compact controls, none of them shouting.
 *
 * Two things arrive already decided and are not re-derived here. The key facts on line four ARE the
 * dossier's `keySpecifications`, chosen by the category schema - a logic gate's set is not a
 * resistor's. The Manufacturer Page action appears only when the projection VERIFIED that the URL
 * belongs to the manufacturer; a distributor listing is a different claim by a different party and
 * is never promoted into that slot, however plausible its host looks.
 */
import type { ComponentDossier } from "../../api/dossierTypes";
import { Text, useCopyFormatter, useText } from "../../lib/copy";
import { Button, StatusText } from "../primitives";
import { ExternalIcon } from "../icons";
import { CopyMpnButton } from "./CopyMpnButton";
import { DatasheetButton } from "./DatasheetButton";
import { ManageMenu, type ManageMenuItem } from "./ManageMenu";
import type { DatasheetTarget } from "./datasheetWorkflow";
import {
  cadCondition,
  classificationLine,
  conflictCount,
  DOT,
  joinFacts,
  keyFactText,
  keyFacts,
  lifecycleTone,
  missingCount,
  pinsWord,
  qualitySegments,
  type QualitySegmentKind,
} from "./componentIdentity";

export interface ComponentHeaderProps {
  dossier: ComponentDossier;
  manageItems: ManageMenuItem[];
  /** A quality segment was pressed: take the reader to what it is about. */
  onQualitySegment: (kind: QualitySegmentKind) => void;
  /** Open one document in the viewer. */
  onOpenDatasheet: (target: DatasheetTarget) => void;
  /** No datasheet is on record: open the surface that can go and find one. */
  onFindDatasheet: () => void;
}

export function ComponentHeader({
  dossier,
  manageItems,
  onQualitySegment,
  onOpenDatasheet,
  onFindDatasheet,
}: ComponentHeaderProps) {
  const { identity, qualitySummary, documents } = dossier;
  const description = qualitySummary.description.trim();
  // Each line reads the ones above it, so the four say four different things. A distributor's
  // description is the manufacturer's own words and is never edited to fit - it is line 2 exactly
  // as it arrived - but it routinely CONTAINS the value and the package, so the structured lines
  // below it have to know what it already said. Measured on a 100 nF 0402 capacitor described as
  // "100 nF 16V X7R 0402": `0402` was printed three times and `100 nF` twice, on four consecutive
  // lines, which is one fact wearing four coats rather than four facts.
  const descriptionLine = joinFacts([identity.manufacturer, description]);
  const classification = classificationLine(dossier, pinsWord, descriptionLine);
  const facts = keyFacts(dossier, joinFacts([descriptionLine, classification]));
  const manufacturerPageLabel = useText(
    "component-browser.header-manufacturer-page",
    "Manufacturer Page",
  );
  const mpnTitle = useText("component-browser.header-mpn-title", "Manufacturer part number");
  const page = identity.manufacturerPage;

  return (
    <header
      data-dev-id="component-browser.header"
      // 8px outer padding, and the internal steps are 2px. The hierarchy is doing the separating,
      // so the gaps do not have to.
      className="flex flex-none items-start gap-3 border-b border-line bg-surface px-2 py-2"
    >
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex min-w-0 items-baseline gap-2">
          {/* The subject of the entire screen. One line, never abbreviated for style, and the full
              string in the tooltip for the rare part number that genuinely cannot fit. */}
          <span
            data-dev-id="component-browser.header-mpn"
            title={identity.mpn || mpnTitle}
            className="ui-component-mpn min-w-0 truncate"
          >
            {identity.mpn || identity.displayName}
          </span>
          {identity.lifecycle ? (
            // Aligned separately. Appending it to the MPN would make "SN74LVC1G08DBVR Active" read
            // as a part number, which is a string nobody can search for.
            <StatusText
              data-dev-id="component-browser.header-lifecycle"
              tone={lifecycleTone(identity.lifecycle)}
              className="flex-none"
            >
              {identity.lifecycle}
            </StatusText>
          ) : null}
        </div>

        {description || identity.manufacturer ? (
          <p
            data-dev-id="component-browser.header-description"
            className="ui-component-description mt-0.5 min-w-0 truncate"
            title={descriptionLine}
          >
            {identity.manufacturer ? (
              <span className="font-medium">{identity.manufacturer}</span>
            ) : null}
            {identity.manufacturer && description ? <span>{` ${DOT} `}</span> : null}
            {description}
          </p>
        ) : null}

        {classification ? (
          <p
            data-dev-id="component-browser.header-classification"
            className="ui-component-metadata mt-0.5 min-w-0 truncate"
          >
            {classification}
          </p>
        ) : null}

        {facts.length > 0 ? (
          <p
            data-dev-id="component-browser.header-key-facts"
            className="ui-component-metadata mt-0.5 min-w-0 truncate text-t2"
            title={facts.map((fact) => `${fact.label} ${keyFactText(fact)}`).join(`  ${DOT}  `)}
          >
            {joinFacts(facts.map(keyFactText))}
          </p>
        ) : null}

        <QualitySummary dossier={dossier} onSegment={onQualitySegment} />
      </div>

      <div
        data-dev-id="component-browser.header-actions"
        className="flex flex-none items-center gap-1.5"
      >
        <DatasheetButton
          documents={documents}
          onOpen={onOpenDatasheet}
          onFindDatasheet={onFindDatasheet}
        />
        {/* Only when the projection PROVED the host is the manufacturer's own, or that the
            manufacturer supplied it. An unverified candidate produces no action here at all
            rather than a mislabelled one. */}
        {page.verified && page.url ? (
          <Button
            small
            data-dev-id="component-browser.header-manufacturer-page"
            aria-label={manufacturerPageLabel}
            icon={<ExternalIcon className="h-3.5 w-3.5" />}
            onClick={() => window.open(page.url, "_blank", "noreferrer")}
          >
            <Text id="component-browser.header-manufacturer-page">Manufacturer Page</Text>
          </Button>
        ) : null}
        <CopyMpnButton mpn={identity.mpn} />
        <ManageMenu items={manageItems} />
      </div>
    </header>
  );
}

/**
 * The compact data-quality summary. Every segment is a way IN, not a report.
 *
 * They are buttons rather than statuses on purpose: a status must not look clickable, and these
 * must. They stay at metadata size and take a quiet underline on approach, so they read as text you
 * can follow rather than as three more controls competing with the actions on the right.
 */
function QualitySummary({
  dossier,
  onSegment,
}: {
  dossier: ComponentDossier;
  onSegment: (kind: QualitySegmentKind) => void;
}) {
  const segments = qualitySegments(dossier);
  const missingText = useCopyFormatter(
    "component-browser.quality-missing",
    "{count} Required Values Missing",
  );
  const conflictText = useCopyFormatter("component-browser.quality-conflicts", "{count} Conflicting");
  const cadComplete = useText("component-browser.quality-cad-complete", "CAD Complete");
  const cadIncomplete = useCopyFormatter(
    "component-browser.quality-cad-incomplete",
    "{count} CAD Assets Missing",
  );
  const cadFailed = useText("component-browser.quality-cad-failed", "CAD Failed");
  const cad = cadCondition(dossier.cadAssets.kinds);

  function labelFor(kind: QualitySegmentKind, count: number): string {
    if (kind === "missing") return missingText({ count });
    if (kind === "conflicts") return conflictText({ count });
    if (cad.kind === "complete") return cadComplete;
    if (cad.kind === "failed") return cadFailed;
    return cadIncomplete({ count });
  }

  return (
    <p
      data-dev-id="component-browser.quality-summary"
      data-missing={missingCount(dossier)}
      data-conflicts={conflictCount(dossier)}
      className="mt-1 flex min-w-0 flex-wrap items-baseline gap-x-1.5 gap-y-0.5"
    >
      {segments.map((segment, index) => (
        <span key={segment.kind} className="flex items-baseline gap-1.5">
          {index > 0 ? (
            <span aria-hidden className="ui-component-metadata">
              {DOT}
            </span>
          ) : null}
          <button
            type="button"
            data-dev-id="component-browser.quality-segment"
            data-quality-segment={segment.kind}
            onClick={() => onSegment(segment.kind)}
            className={
              "ui-component-metadata rounded-control underline-offset-2 hover:underline " +
              "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 " +
              "focus-visible:outline-focus " +
              QUALITY_TONE[segment.tone]
            }
          >
            {labelFor(segment.kind, segment.count)}
          </button>
        </span>
      ))}
    </p>
  );
}

const QUALITY_TONE: Record<"warn" | "err" | "neutral" | "ok", string> = {
  warn: "text-warn",
  err: "text-err",
  ok: "text-ok",
  neutral: "text-t3",
};
