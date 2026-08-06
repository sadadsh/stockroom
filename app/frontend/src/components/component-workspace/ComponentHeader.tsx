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
 *
 * THE BAND IS SIX PIECES NOW (plan Phase 1), not one component. The five lines and the action group
 * are placed by the layout document, so a redesign can drop the classification line or move the
 * actions without editing this file. What holds them together is `HeaderBandChrome`: the four lines
 * READ EACH OTHER - a description that already said `0402` must stop the classification line saying
 * it again - so the derivation is done ONCE for the band and handed to the lines, and the three
 * conditions the document names ("is there a description", "is there a classification", "are there
 * key facts") are answered from the same derivation rather than recomputed per piece. Two
 * derivations would be two answers, and the second one would be the one on screen.
 */
import { createContext, useContext, useMemo } from "react";
import { Text, useCopyFormatter, useText } from "../../lib/copy";
import { Button, StatusText } from "../primitives";
import { ExternalIcon } from "../icons";
import { LayoutRuntimeScope, type RegionChromeProps } from "../../layout/LayoutRenderer";
import { WORKSPACE_CONDITION } from "../../layout/defaultWorkspaceLayout";
import { useWorkspaceRender } from "../../layout/workspaceRenderContext";
import { CopyMpnButton } from "./CopyMpnButton";
import { DatasheetButton } from "./DatasheetButton";
import { ManageMenu } from "./ManageMenu";
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

/** The three lines the band derived once, so no line repeats what the line above it already said. */
interface HeaderLines {
  descriptionLine: string;
  classification: string;
  facts: ReturnType<typeof keyFacts>;
}

const EMPTY_LINES: HeaderLines = { descriptionLine: "", classification: "", facts: [] };

const HeaderLinesContext = createContext<HeaderLines>(EMPTY_LINES);

/**
 * The header band: the element, the shared derivation, and the answers to its own conditions.
 *
 * 8px outer padding, and the internal steps are 2px. The hierarchy is doing the separating, so the
 * gaps do not have to.
 */
export function HeaderBandChrome({ children }: RegionChromeProps) {
  const workspace = useWorkspaceRender();
  const dossier = workspace?.dossier;
  const lines = useMemo<HeaderLines>(() => {
    if (!dossier) return EMPTY_LINES;
    const description = dossier.qualitySummary.description.trim();
    // Each line reads the ones above it, so the four say four different things. A distributor's
    // description is the manufacturer's own words and is never edited to fit - it is line 2 exactly
    // as it arrived - but it routinely CONTAINS the value and the package, so the structured lines
    // below it have to know what it already said. Measured on a 100 nF 0402 capacitor described as
    // "100 nF 16V X7R 0402": `0402` was printed three times and `100 nF` twice, on four consecutive
    // lines, which is one fact wearing four coats rather than four facts.
    const descriptionLine = joinFacts([dossier.identity.manufacturer, description]);
    const classification = classificationLine(dossier, pinsWord, descriptionLine);
    return {
      descriptionLine,
      classification,
      facts: keyFacts(dossier, joinFacts([descriptionLine, classification])),
    };
  }, [dossier]);

  const conditions = useMemo(
    () => ({
      [WORKSPACE_CONDITION.headerDescription]: Boolean(
        dossier && (dossier.qualitySummary.description.trim() || dossier.identity.manufacturer),
      ),
      [WORKSPACE_CONDITION.headerClassification]: lines.classification !== "",
      [WORKSPACE_CONDITION.headerKeyFacts]: lines.facts.length > 0,
    }),
    [dossier, lines],
  );

  if (!workspace) return null;
  return (
    <header
      data-dev-id="component-browser.header"
      className="flex flex-none items-start gap-3 border-b border-line bg-surface px-2 py-2"
    >
      <HeaderLinesContext.Provider value={lines}>
        <LayoutRuntimeScope conditions={conditions}>{children}</LayoutRuntimeScope>
      </HeaderLinesContext.Provider>
    </header>
  );
}

/** The stack of identity lines. `flex-1` so the action group takes only what it needs. */
export function HeaderLinesChrome({ children }: RegionChromeProps) {
  return <div className="flex min-w-0 flex-1 flex-col">{children}</div>;
}

/**
 * Line 1: the subject of the entire screen, and the state beside it.
 *
 * One line, never abbreviated for style, and the full string in the tooltip for the rare part
 * number that genuinely cannot fit. The lifecycle is aligned separately: appending it to the MPN
 * would make "SN74LVC1G08DBVR Active" read as a part number, which is a string nobody can search
 * for.
 */
export function HeaderIdentityPart() {
  const workspace = useWorkspaceRender();
  const mpnTitle = useText("component-browser.header-mpn-title", "Manufacturer part number");
  if (!workspace) return null;
  const { identity } = workspace.dossier;
  return (
    <div className="flex min-w-0 items-baseline gap-2">
      <span
        data-dev-id="component-browser.header-mpn"
        title={identity.mpn || mpnTitle}
        className="ui-component-mpn min-w-0 truncate"
      >
        {identity.mpn || identity.displayName}
      </span>
      {identity.lifecycle ? (
        <StatusText
          data-dev-id="component-browser.header-lifecycle"
          tone={lifecycleTone(identity.lifecycle)}
          className="flex-none"
        >
          {identity.lifecycle}
        </StatusText>
      ) : null}
    </div>
  );
}

/** Line 2: the manufacturer's own words, at body weight, never edited to fit. */
export function HeaderDescriptionPart() {
  const workspace = useWorkspaceRender();
  const { descriptionLine } = useContext(HeaderLinesContext);
  if (!workspace) return null;
  const { identity, qualitySummary } = workspace.dossier;
  const description = qualitySummary.description.trim();
  return (
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
  );
}

/** Line 3: category, package and pin count, each dropped where line 2 already said it. */
export function HeaderClassificationPart() {
  const { classification } = useContext(HeaderLinesContext);
  return (
    <p
      data-dev-id="component-browser.header-classification"
      className="ui-component-metadata mt-0.5 min-w-0 truncate"
    >
      {classification}
    </p>
  );
}

/** Line 4: the category schema's own key set, never re-scanned from the groups. */
export function HeaderKeyFactsPart() {
  const { facts } = useContext(HeaderLinesContext);
  return (
    <p
      data-dev-id="component-browser.header-key-facts"
      className="ui-component-metadata mt-0.5 min-w-0 truncate text-t2"
      title={facts.map((fact) => `${fact.label} ${keyFactText(fact)}`).join(`  ${DOT}  `)}
    >
      {joinFacts(facts.map(keyFactText))}
    </p>
  );
}

/**
 * The compact data-quality summary. Every segment is a way IN, not a report.
 *
 * They are buttons rather than statuses on purpose: a status must not look clickable, and these
 * must. They stay at metadata size and take a quiet underline on approach, so they read as text you
 * can follow rather than as three more controls competing with the actions on the right.
 */
export function HeaderQualitySummaryPart() {
  const workspace = useWorkspaceRender();
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
  if (!workspace) return null;
  const { dossier, header } = workspace;
  const segments = qualitySegments(dossier);
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
            onClick={() => header.onQualitySegment(segment.kind)}
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

/**
 * The right-hand action group: Datasheet, Manufacturer Page, Copy MPN, and Manage.
 *
 * ONE piece, because the group is a single right-aligned cluster whose entries appear and disappear
 * with what the machine and the component can do.
 */
export function HeaderActionsPart() {
  const workspace = useWorkspaceRender();
  const manufacturerPageLabel = useText(
    "component-browser.header-manufacturer-page",
    "Manufacturer Page",
  );
  if (!workspace) return null;
  const { dossier, header } = workspace;
  const page = dossier.identity.manufacturerPage;
  return (
    <div
      data-dev-id="component-browser.header-actions"
      className="flex flex-none items-center gap-1.5"
    >
      <DatasheetButton
        documents={dossier.documents}
        onOpen={header.onOpenDatasheet}
        onFindDatasheet={header.onFindDatasheet}
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
      <CopyMpnButton mpn={dossier.identity.mpn} />
      <ManageMenu items={header.manageItems} />
    </div>
  );
}

const QUALITY_TONE: Record<"warn" | "err" | "neutral" | "ok", string> = {
  warn: "text-warn",
  err: "text-err-text",
  ok: "text-ok-text",
  neutral: "text-t3",
};
