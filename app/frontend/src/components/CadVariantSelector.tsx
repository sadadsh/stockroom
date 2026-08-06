/**
 * A controlled selector for immutable, reverified CAD variants.
 *
 * Every provider variant remains visible, while only an exact same-download cross-EDA pair can be
 * activated. Switching the pair never deletes retained evidence or fetches it again.
 */
import { useId } from "react";
import type {
  CadVariant,
  CadVariantArtifact,
  CadVariantArtifactKind,
  CadVariantInventory,
  CadVariantPair,
  CadVariantPairActivation,
  CadVariantTool,
  SupplementaryCadEvidence,
} from "../api/cadVariantClient";
import { Text, useCopyFormatter, useText } from "../lib/copy";
import { Badge, Button, Card, Dot, EYEBROW_DENSE } from "./primitives";

export type {
  CadVariant,
  CadVariantArtifact,
  CadVariantArtifactKind,
  CadVariantInventory,
  CadVariantPair,
  CadVariantPairActivation,
  CadVariantTool,
  SupplementaryCadEvidence,
} from "../api/cadVariantClient";

interface Props {
  inventories: readonly CadVariantInventory[];
  pairs: readonly CadVariantPair[];
  supplementary: readonly SupplementaryCadEvidence[];
  onActivatePair: (activation: CadVariantPairActivation) => void;
  activatingPair?: Pick<
    CadVariantPairActivation,
    "kicadVariantId" | "altiumVariantId"
  > | null;
  activationError?: string | null;
}

const TOOL_ORDER: readonly CadVariantTool[] = ["kicad", "altium"];
const TOOL_LABELS: Record<CadVariantTool, string> = {
  kicad: "KiCad",
  altium: "Altium",
};
const ARTIFACT_LABELS: Record<CadVariantArtifactKind, string> = {
  symbol: "Symbol",
  footprint: "Footprint",
  model: "3D Model",
};
const ARTIFACT_ORDER: Record<CadVariantArtifactKind, number> = {
  symbol: 0,
  footprint: 1,
  model: 2,
};

function orderedVariants(variants: readonly CadVariant[]): CadVariant[] {
  return [...variants].sort(
    (left, right) =>
      left.trustRank - right.trustRank ||
      left.provider.localeCompare(right.provider) ||
      left.format.localeCompare(right.format) ||
      left.id.localeCompare(right.id),
  );
}

function orderedArtifacts(artifacts: readonly CadVariantArtifact[]): CadVariantArtifact[] {
  return [...artifacts].sort(
    (left, right) =>
      ARTIFACT_ORDER[left.kind] - ARTIFACT_ORDER[right.kind] ||
      left.fileName.localeCompare(right.fileName),
  );
}

function inventoryVariant(
  inventories: readonly CadVariantInventory[],
  tool: CadVariantTool,
  variantId: string,
): CadVariant | null {
  return (
    inventories
      .find((inventory) => inventory.tool === tool)
      ?.variants.find((variant) => variant.id === variantId) ?? null
  );
}

function shortDigest(value: string): string {
  const digest = value.trim();
  return digest.length > 12 ? `${digest.slice(0, 12)}...` : digest;
}

export function CadVariantSelector({
  inventories,
  pairs,
  supplementary,
  onActivatePair,
  activatingPair = null,
  activationError = null,
}: Props) {
  const headingId = useId();
  const inventoryByTool = new Map(inventories.map((inventory) => [inventory.tool, inventory]));
  const activePair = pairs.find(
    (pair) =>
      pair.kicadVariantId === inventoryByTool.get("kicad")?.activeVariantId &&
      pair.altiumVariantId === inventoryByTool.get("altium")?.activeVariantId,
  );
  const retainedCount = TOOL_ORDER.reduce(
    (count, tool) => count + (inventoryByTool.get(tool)?.variants.length ?? 0),
    0,
  );
  const supplementaryCount = supplementary.reduce(
    (count, evidence) => count + evidence.artifacts.length,
    0,
  );

  return (
    <Card
      role="region"
      aria-labelledby={headingId}
      className="@container overflow-hidden bg-surface"
    >
      <header className="flex flex-col gap-1 border-b border-line bg-band px-3 py-2 @sm:flex-row @sm:items-start @sm:gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h2 id={headingId} className={EYEBROW_DENSE}>
              <Text id="detail.cad-variants.title">CAD Variants</Text>
            </h2>
            <Badge tone="neutral" size="sm">
              <Text id="cad.variant.selector.retained-count" values={{ count: retainedCount }}>
                {"{count} Retained"}
              </Text>
            </Badge>
            {supplementaryCount ? (
              <Badge tone="neutral" size="sm">
                <Text
                  id="cad.variant.selector.originals-count"
                  values={{ count: supplementaryCount }}
                >
                  {"{count} Originals"}
                </Text>
              </Badge>
            ) : null}
          </div>
          <p className="mt-1 text-2xs text-t2">
            <Text id="detail.cad-variants.help">Review each retained provider variant. Activation is available just when both sides of an exact same-provider, same-download KiCad and Altium pair are revalidated, and one switch updates both.</Text>
          </p>
        </div>
        {activationError ? (
          <p role="alert" className="text-2xs font-medium text-err-text">
            {activationError}
          </p>
        ) : null}
      </header>

      <PairInventory
        inventories={inventories}
        pairs={pairs}
        activating={activatingPair}
        onActivate={onActivatePair}
      />

      <div className="grid grid-cols-1 gap-px bg-line @xl:grid-cols-2">
        {TOOL_ORDER.map((tool) => {
          const inventory = inventoryByTool.get(tool) ?? {
            tool,
            activeVariantId: null,
            variants: [],
          };
          return (
            <ToolInventory
              key={tool}
              inventory={inventory}
              activePairVariantId={
                activePair
                  ? tool === "kicad"
                    ? activePair.kicadVariantId
                    : activePair.altiumVariantId
                  : null
              }
            />
          );
        })}
      </div>
      {supplementary.length ? (
        <SupplementaryInventory evidence={supplementary} />
      ) : null}
    </Card>
  );
}

function PairInventory({
  inventories,
  pairs,
  activating,
  onActivate,
}: {
  inventories: readonly CadVariantInventory[];
  pairs: readonly CadVariantPair[];
  activating: Pick<
    CadVariantPairActivation,
    "kicadVariantId" | "altiumVariantId"
  > | null;
  onActivate: (activation: CadVariantPairActivation) => void;
}) {
  const sectionLabel = useText(
    "cad.variant.selector.pairs-aria",
    "Same-Download CAD Pairs",
  );
  // The accessible name of a row's one control, resolved above the map that renders the rows: it is
  // the only text a screen reader has for a button whose visible label says just "Both Tools".
  const pairActivateLabel = useCopyFormatter(
    "cad.variant.selector.pair-activate-aria",
    "Use {provider} for KiCad and Altium",
  );
  const kicad = inventories.find((inventory) => inventory.tool === "kicad");
  const altium = inventories.find((inventory) => inventory.tool === "altium");
  const ordered = [...pairs].sort(
    (left, right) =>
      left.trustRank - right.trustRank ||
      left.provider.localeCompare(right.provider) ||
      left.kicadVariantId.localeCompare(right.kicadVariantId) ||
      left.altiumVariantId.localeCompare(right.altiumVariantId),
  );

  return (
    <section
      aria-label={sectionLabel}
      className="border-b border-line bg-surface px-3 py-2.5"
    >
      <div className="mb-2 flex min-w-0 items-baseline gap-2">
        <h3 className="text-xs font-semibold text-t1">
          <Text id="cad.variant.selector.pairs-title">Same-Download Pairs</Text>
        </h3>
        <span className="text-2xs text-t3">
          <Text id="cad.variant.selector.pairs-help">
            One switch updates KiCad and Altium together
          </Text>
        </span>
      </div>
      {ordered.length ? (
        <div className="grid grid-cols-1 gap-2 @xl:grid-cols-2">
          {ordered.map((pair) => {
            const kicadVariant = inventoryVariant(
              inventories,
              "kicad",
              pair.kicadVariantId,
            );
            const altiumVariant = inventoryVariant(
              inventories,
              "altium",
              pair.altiumVariantId,
            );
            const pairReverified =
              pair.verificationState === "reverified" &&
              kicadVariant?.verificationState === "reverified" &&
              altiumVariant?.verificationState === "reverified";
            const active =
              pair.kicadVariantId === kicad?.activeVariantId &&
              pair.altiumVariantId === altium?.activeVariantId;
            const switching =
              pair.kicadVariantId === activating?.kicadVariantId &&
              pair.altiumVariantId === activating?.altiumVariantId;
            return (
              <article
                key={`${pair.kicadVariantId}:${pair.altiumVariantId}`}
                aria-current={active ? "true" : undefined}
                className={`relative overflow-hidden rounded-card border bg-raise px-3 py-2 ${
                  active ? "border-line2" : "border-line"
                }`}
              >
                {active ? (
                  <span aria-hidden className="absolute inset-y-0 left-0 w-0.5 bg-acc-strong" />
                ) : null}
                <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                  <h4 className="min-w-0 flex-1 truncate text-xs font-semibold text-t1">
                    {pair.provider}
                  </h4>
                  {active ? (
                    <Badge tone="ok" size="sm">
                      <Text id="cad.variant.selector.pair-active">Active In Both</Text>
                    </Badge>
                  ) : null}
                  <Badge tone="neutral" size="sm">
                    {pair.trustRank === ordered[0]?.trustRank ? (
                      <Text id="cad.variant.selector.pair-preferred">Preferred</Text>
                    ) : (
                      <Text id="cad.variant.selector.pair-fallback">Fallback</Text>
                    )}
                  </Badge>
                </div>
                <div className="mt-2 flex min-w-0 items-center gap-1.5 text-2xs text-t2">
                  <Dot tone={pairReverified ? "ok" : "warn"} />
                  <span
                    className={
                      "font-medium " + (pairReverified ? "text-ok-text" : "text-warn")
                    }
                  >
                    {pairReverified ? (
                      <Text id="cad.variant.selector.pair-reverified">
                        Reverified Same-Download Pair
                      </Text>
                    ) : (
                      <Text id="cad.variant.selector.pair-evidence-missing">
                        Verification Evidence Missing
                      </Text>
                    )}
                  </span>
                </div>
                {!active ? (
                  <div className="mt-2 flex justify-end border-t border-line pt-2">
                    <Button
                      type="button"
                      small
                      disabled={!pairReverified || switching || activating !== null}
                      aria-busy={switching || undefined}
                      aria-label={pairActivateLabel({ provider: pair.provider })}
                      onClick={() =>
                        onActivate({
                          kicadVariantId: pair.kicadVariantId,
                          altiumVariantId: pair.altiumVariantId,
                          expectedActiveKicadVariantId: kicad?.activeVariantId ?? null,
                          expectedActiveAltiumVariantId: altium?.activeVariantId ?? null,
                        })
                      }
                    >
                      {switching ? (
                        <Text id="cad.variant.selector.pair-switching">Switching Both...</Text>
                      ) : (
                        <Text id="cad.variant.selector.pair-activate">Use In Both Tools</Text>
                      )}
                    </Button>
                  </div>
                ) : null}
              </article>
            );
          })}
        </div>
      ) : (
        <div className="rounded-card border border-dashed border-line px-3 py-3 text-2xs text-t2">
          <Text id="cad.variant.selector.no-pairs">
            No activatable pair is retained. Individual provider variants remain visible below, but
            Stockroom will not combine files from separate downloads or activate one EDA alone.
          </Text>
        </div>
      )}
    </section>
  );
}

function readableBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function SupplementaryInventory({
  evidence,
}: {
  evidence: readonly SupplementaryCadEvidence[];
}) {
  const sectionLabel = useText(
    "cad.variant.selector.supplementary-aria",
    "Additional Retained Artifacts",
  );
  // Resolved above the map for the same reason as the pair rows: a hook cannot run in the callback.
  const cardLabel = useCopyFormatter(
    "cad.variant.selector.supplementary-card-aria",
    "{provider} retained originals",
  );
  const cardNote = useCopyFormatter(
    "cad.variant.selector.supplementary-note",
    "Original files from {surface}. These do not meet Symbol, Footprint or 3D Model coverage until a reverified CAD pipeline projects them.",
  );
  return (
    <section
      aria-label={sectionLabel}
      className="border-t border-line bg-surface px-3 py-2.5"
    >
      <div className="mb-2 flex min-w-0 items-baseline gap-2">
        <h3 className="text-xs font-semibold text-t1">
          <Text id="detail.cad-variants.supplementary">Retained Originals</Text>
        </h3>
        <span className="text-2xs text-t3">
          <Text id="cad.variant.selector.supplementary-help">
            Exact provider files kept for inspection and future processing
          </Text>
        </span>
      </div>
      <div className="grid grid-cols-1 gap-2 @xl:grid-cols-2">
        {evidence.map((manifest) => (
          <article
            key={manifest.id}
            aria-label={cardLabel({ provider: manifest.provider })}
            className="min-w-0 rounded-card border border-line bg-raise px-3 py-2"
          >
            <div className="flex min-w-0 flex-wrap items-center gap-1.5">
              <h4 className="min-w-0 truncate text-xs font-semibold text-t1">
                {manifest.provider}
              </h4>
              <Badge tone="neutral" size="sm">
                <Text id="cad.variant.selector.supplementary-badge">Additional</Text>
              </Badge>
              <Badge tone="neutral" size="sm">
                <Text id="cad.variant.selector.not-activatable">Not Activatable</Text>
              </Badge>
            </div>
            <p className="mt-1 text-2xs text-t2">{cardNote({ surface: manifest.surface })}</p>
            <ul className="mt-2 divide-y divide-line border-t border-line">
              {manifest.artifacts.map((artifact) => (
                <li
                  key={`${artifact.id}:${artifact.fileName}`}
                  className="flex min-w-0 items-center gap-2 py-1.5 text-2xs"
                >
                  <span className="min-w-0 flex-1 truncate font-medium text-t1">
                    {artifact.fileName}
                  </span>
                  <span className="shrink-0 tabular-nums text-t3">
                    {readableBytes(artifact.sizeBytes)}
                  </span>
                  <span
                    className="shrink-0 font-mono text-t3"
                    title={artifact.evidenceDigest}
                  >
                    {shortDigest(artifact.evidenceDigest)}
                  </span>
                </li>
              ))}
            </ul>
          </article>
        ))}
      </div>
    </section>
  );
}

function ToolInventory({
  inventory,
  activePairVariantId,
}: {
  inventory: CadVariantInventory;
  activePairVariantId: string | null;
}) {
  const toolLabel = TOOL_LABELS[inventory.tool];
  const variants = orderedVariants(inventory.variants);
  const preferredRank = variants[0]?.trustRank;
  const activeVariant = variants.find((variant) => variant.id === activePairVariantId);
  const activeMissing = activePairVariantId !== null && !activeVariant;
  const unpairedSelection =
    inventory.activeVariantId !== null && activePairVariantId === null;
  const sectionLabel = useCopyFormatter(
    "cad.variant.selector.tool-aria",
    "{tool} CAD Variants",
  );
  const missingActive = useCopyFormatter(
    "cad.variant.selector.active-missing",
    "The active pair's {tool} variant is unavailable. Refresh the retained evidence.",
  );
  const unpaired = useCopyFormatter(
    "cad.variant.selector.unpaired",
    "The stored {tool} selection is not pair-active. Choose a same-download pair above to update both tools in one atomic switch.",
  );
  const noneRetained = useCopyFormatter(
    "cad.variant.selector.none-retained",
    "No reverified {tool} variants are retained for this part.",
  );

  return (
    <section
      aria-label={sectionLabel({ tool: toolLabel })}
      className="min-w-0 bg-surface px-3 py-2.5"
    >
      <div className="mb-2 flex min-w-0 items-baseline gap-2">
        <h3 className="text-xs font-semibold text-t1">{toolLabel}</h3>
        <span className="text-2xs tabular-nums text-t3">
          {variants.length} {variants.length === 1 ? "Variant" : "Variants"}
        </span>
        {activeVariant ? (
          <span className="ml-auto min-w-0 truncate text-2xs text-t2">
            <Text id="cad.variant.selector.active-label">Active:</Text>{" "}
            <span className="font-medium text-t1">{activeVariant.provider}</span>
          </span>
        ) : null}
      </div>

      {activeMissing ? (
        <p role="status" className="mb-2 text-2xs font-medium text-warn">
          {missingActive({ tool: toolLabel })}
        </p>
      ) : null}
      {unpairedSelection ? (
        <p role="status" className="mb-2 text-2xs font-medium text-warn">
          {unpaired({ tool: toolLabel })}
        </p>
      ) : null}

      {variants.length ? (
        <div className="flex flex-col gap-2">
          {variants.map((variant) => {
            const active = variant.id === activePairVariantId;
            return (
              <VariantRow
                key={variant.id}
                tool={inventory.tool}
                variant={variant}
                active={active}
                storedWithoutPair={
                  unpairedSelection && variant.id === inventory.activeVariantId
                }
                preferred={variant.trustRank === preferredRank}
              />
            );
          })}
        </div>
      ) : (
        <div className="rounded-card border border-dashed border-line px-3 py-3 text-2xs text-t2">
          {noneRetained({ tool: toolLabel })}
        </div>
      )}
    </section>
  );
}

function VariantRow({
  tool,
  variant,
  active,
  storedWithoutPair,
  preferred,
}: {
  tool: CadVariantTool;
  variant: CadVariant;
  active: boolean;
  storedWithoutPair: boolean;
  preferred: boolean;
}) {
  const toolLabel = TOOL_LABELS[tool];
  const artifacts = orderedArtifacts(variant.artifacts);
  const artifactSummary = [
    ...new Set(artifacts.map((artifact) => ARTIFACT_LABELS[artifact.kind])),
  ].join(", ");
  const fileSummary = artifacts.map((artifact) => artifact.fileName).join(", ");
  const reverified = variant.verificationState === "reverified";
  // One id per state rather than one sentence with a spliced-in clause: the pair state is part of
  // what a screen reader announces for this row, so it is reworded with the name it belongs to.
  const rowActive = useCopyFormatter(
    "cad.variant.selector.row-aria-active",
    "{provider} {tool} variant, active in pair",
  );
  const rowStored = useCopyFormatter(
    "cad.variant.selector.row-aria-stored",
    "{provider} {tool} variant, stored without pair",
  );
  const rowPlain = useCopyFormatter(
    "cad.variant.selector.row-aria",
    "{provider} {tool} variant",
  );

  return (
    <article
      aria-label={(active ? rowActive : storedWithoutPair ? rowStored : rowPlain)({
        provider: variant.provider,
        tool: toolLabel,
      })}
      aria-current={active ? "true" : undefined}
      className={`relative overflow-hidden rounded-card border bg-raise ${
        active ? "border-line2" : "border-line"
      }`}
    >
      {active ? (
        <span aria-hidden className="absolute inset-y-0 left-0 w-0.5 bg-acc-strong" />
      ) : null}
      <div className="min-w-0 px-3 py-2">
        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
          <h4 className="min-w-0 truncate text-xs font-semibold text-t1">
            {variant.provider}
          </h4>
          {active ? (
            <Badge tone="ok" size="sm">
              <Text id="cad.variant.selector.variant-active">Active In Pair</Text>
            </Badge>
          ) : null}
          {storedWithoutPair ? (
            <Badge tone="warn" size="sm">
              <Text id="cad.variant.selector.variant-stored-only">Stored, Not Active</Text>
            </Badge>
          ) : null}
          <Badge tone="neutral" size="sm">
            {preferred ? (
              <Text id="cad.variant.selector.variant-preferred">Preferred</Text>
            ) : (
              <Text id="cad.variant.selector.variant-fallback">Fallback</Text>
            )}
          </Badge>
        </div>

        <p className="mt-1 truncate text-2xs text-t2" title={variant.format}>
          {variant.format}
        </p>

        <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1.5">
          <div className="min-w-0">
            <dt className={EYEBROW_DENSE}>
              <Text id="cad.variant.selector.files-label">Files</Text>
            </dt>
            <dd className="mt-0.5 truncate text-2xs text-t1" title={fileSummary || undefined}>
              {artifactSummary || "No Files Recorded"}
            </dd>
          </div>
          <div className="min-w-0">
            <dt className={EYEBROW_DENSE}>
              <Text id="cad.variant.selector.evidence-label">Evidence</Text>
            </dt>
            <dd
              className="mt-0.5 truncate font-mono text-2xs text-t1"
              title={variant.evidenceDigest}
            >
              {shortDigest(variant.evidenceDigest) || "Not Recorded"}
            </dd>
          </div>
        </dl>

        <div className="mt-2 flex min-w-0 items-center gap-1.5 text-2xs text-t2">
          <Dot tone={reverified ? "ok" : "warn"} />
          <span className={"font-medium " + (reverified ? "text-ok-text" : "text-warn")}>
            {reverified ? (
              <Text id="cad.variant.selector.variant-reverified">Reverified</Text>
            ) : (
              <Text id="cad.variant.selector.variant-evidence-missing">
                Verification Evidence Missing
              </Text>
            )}
          </span>
          <span aria-hidden className="text-t3">
            ·
          </span>
          <span
            className="min-w-0 truncate font-mono"
            title={variant.evidenceDigest}
          >
            {shortDigest(variant.evidenceDigest) || "Manifest Not Recorded"}
          </span>
        </div>
      </div>
    </article>
  );
}
