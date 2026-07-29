/**
 * A controlled selector for immutable, validated CAD variants.
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
import { Text } from "../lib/copy";
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
              {retainedCount} Retained
            </Badge>
            {supplementaryCount ? (
              <Badge tone="neutral" size="sm">
                {supplementaryCount} Originals
              </Badge>
            ) : null}
          </div>
          <p className="mt-1 text-2xs text-t2">
            <Text id="detail.cad-variants.help">
              Review every retained provider variant. Activation is available only for an exact
              same-provider, same-download KiCad and Altium pair, and one switch updates both.
            </Text>
          </p>
        </div>
        {activationError ? (
          <p role="alert" className="text-2xs font-medium text-err">
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
      aria-label="Same-Download CAD Pairs"
      className="border-b border-line bg-surface px-3 py-2.5"
    >
      <div className="mb-2 flex min-w-0 items-baseline gap-2">
        <h3 className="text-xs font-semibold text-t1">Same-Download Pairs</h3>
        <span className="text-2xs text-t3">
          One switch updates KiCad and Altium together
        </span>
      </div>
      {ordered.length ? (
        <div className="grid grid-cols-1 gap-2 @xl:grid-cols-2">
          {ordered.map((pair) => {
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
                      Active In Both
                    </Badge>
                  ) : null}
                  <Badge tone="neutral" size="sm">
                    {pair.trustRank === ordered[0]?.trustRank ? "Preferred" : "Fallback"}
                  </Badge>
                </div>
                <div className="mt-2 flex min-w-0 items-center gap-1.5 text-2xs text-t2">
                  <Dot tone="ok" />
                  <span className="font-medium text-ok">{pair.trustLabel}</span>
                  <span className="min-w-0 truncate text-t3" title={pair.trustReason}>
                    {pair.trustReason}
                  </span>
                </div>
                {!active ? (
                  <div className="mt-2 flex justify-end border-t border-line pt-2">
                    <Button
                      type="button"
                      small
                      disabled={switching || activating !== null}
                      aria-busy={switching || undefined}
                      aria-label={`Use ${pair.provider} for KiCad and Altium`}
                      onClick={() =>
                        onActivate({
                          kicadVariantId: pair.kicadVariantId,
                          altiumVariantId: pair.altiumVariantId,
                          expectedActiveKicadVariantId: kicad?.activeVariantId ?? null,
                          expectedActiveAltiumVariantId: altium?.activeVariantId ?? null,
                        })
                      }
                    >
                      {switching ? "Switching Both..." : "Use In Both Tools"}
                    </Button>
                  </div>
                ) : null}
              </article>
            );
          })}
        </div>
      ) : (
        <div className="rounded-card border border-dashed border-line px-3 py-3 text-2xs text-t2">
          No activatable pair is retained. Individual provider variants remain visible below, but
          Stockroom will not combine files from separate downloads or activate one EDA alone.
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
  return (
    <section
      aria-label="Supplementary Retained Artifacts"
      className="border-t border-line bg-surface px-3 py-2.5"
    >
      <div className="mb-2 flex min-w-0 items-baseline gap-2">
        <h3 className="text-xs font-semibold text-t1">
          <Text id="detail.cad-variants.supplementary">Retained Originals</Text>
        </h3>
        <span className="text-2xs text-t3">
          Exact provider files kept for inspection and future processing
        </span>
      </div>
      <div className="grid grid-cols-1 gap-2 @xl:grid-cols-2">
        {evidence.map((manifest) => (
          <article
            key={manifest.id}
            aria-label={`${manifest.provider} retained originals`}
            className="min-w-0 rounded-card border border-line bg-raise px-3 py-2"
          >
            <div className="flex min-w-0 flex-wrap items-center gap-1.5">
              <h4 className="min-w-0 truncate text-xs font-semibold text-t1">
                {manifest.provider}
              </h4>
              <Badge tone="neutral" size="sm">
                Supplementary
              </Badge>
              <Badge tone="neutral" size="sm">
                Not Activatable
              </Badge>
            </div>
            <p className="mt-1 text-2xs text-t2">
              Original files from {manifest.surface}. They do not satisfy Symbol, Footprint, or 3D
              Model coverage until a validated CAD pipeline projects them.
            </p>
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

  return (
    <section
      aria-label={`${toolLabel} CAD Variants`}
      className="min-w-0 bg-surface px-3 py-2.5"
    >
      <div className="mb-2 flex min-w-0 items-baseline gap-2">
        <h3 className="text-xs font-semibold text-t1">{toolLabel}</h3>
        <span className="text-2xs tabular-nums text-t3">
          {variants.length} {variants.length === 1 ? "Variant" : "Variants"}
        </span>
        {activeVariant ? (
          <span className="ml-auto min-w-0 truncate text-2xs text-t2">
            Active: <span className="font-medium text-t1">{activeVariant.provider}</span>
          </span>
        ) : null}
      </div>

      {activeMissing ? (
        <p role="status" className="mb-2 text-2xs font-medium text-warn">
          The active pair's {toolLabel} variant is unavailable. Refresh the retained evidence.
        </p>
      ) : null}
      {unpairedSelection ? (
        <p role="status" className="mb-2 text-2xs font-medium text-warn">
          The stored {toolLabel} selection is not pair-active. Choose a same-download pair above
          to update both tools atomically.
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
          No validated {toolLabel} variants are retained for this part.
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

  return (
    <article
      aria-label={`${variant.provider} ${toolLabel} variant${
        active ? ", active in pair" : storedWithoutPair ? ", stored without pair" : ""
      }`}
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
              Active In Pair
            </Badge>
          ) : null}
          {storedWithoutPair ? (
            <Badge tone="warn" size="sm">
              Stored Only
            </Badge>
          ) : null}
          <Badge tone="neutral" size="sm">
            {preferred ? "Preferred" : "Fallback"}
          </Badge>
        </div>

        <p className="mt-1 truncate text-2xs text-t2" title={variant.format}>
          {variant.format}
        </p>

        <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1.5">
          <div className="min-w-0">
            <dt className={EYEBROW_DENSE}>Files</dt>
            <dd className="mt-0.5 truncate text-2xs text-t1" title={fileSummary || undefined}>
              {artifactSummary || "No Files Recorded"}
            </dd>
          </div>
          <div className="min-w-0">
            <dt className={EYEBROW_DENSE}>Evidence</dt>
            <dd
              className="mt-0.5 truncate font-mono text-2xs text-t1"
              title={variant.evidenceDigest}
            >
              {shortDigest(variant.evidenceDigest) || "Not Recorded"}
            </dd>
          </div>
        </dl>

        <div className="mt-2 flex min-w-0 items-center gap-1.5 text-2xs text-t2">
          <Dot tone="ok" />
          <span className="font-medium text-ok">Validated</span>
          <span aria-hidden className="text-t3">
            ·
          </span>
          <span className="tabular-nums">
            {variant.validationChecks} {variant.validationChecks === 1 ? "Check" : "Checks"}
          </span>
          <span aria-hidden className="text-t3">
            ·
          </span>
          <span className="min-w-0 truncate" title={variant.trustReason}>
            {variant.trustLabel}
          </span>
        </div>
      </div>
    </article>
  );
}
