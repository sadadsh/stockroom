/**
 * A controlled selector for immutable, validated CAD variants.
 *
 * Variants and the active pointer are deliberately separate in the prop contract. Switching the
 * pointer never implies deleting a retained download or fetching it again, and the expected active
 * id gives the eventual API seam enough information to reject a stale concurrent switch.
 */
import { useId } from "react";
import { Text } from "../lib/copy";
import { Badge, Button, Card, Dot, EYEBROW_DENSE } from "./primitives";

export type CadVariantTool = "kicad" | "altium";
export type CadVariantArtifactKind = "symbol" | "footprint" | "model";

export interface CadVariantArtifact {
  kind: CadVariantArtifactKind;
  fileName: string;
}

export interface CadVariant {
  id: string;
  provider: string;
  format: string;
  artifacts: readonly CadVariantArtifact[];
  evidenceDigest: string;
  validationChecks: number;
  /**
   * Lower is more trusted. The policy stays outside the component, so Ultra Librarian can be
   * preferred today without hard-coding a provider name into presentation logic.
   */
  trustRank: number;
  trustLabel: string;
  trustReason?: string;
}

export interface CadVariantInventory {
  tool: CadVariantTool;
  activeVariantId: string | null;
  variants: readonly CadVariant[];
}

export interface CadVariantActivation {
  tool: CadVariantTool;
  variantId: string;
  expectedActiveVariantId: string | null;
}

interface Props {
  inventories: readonly CadVariantInventory[];
  onActivate: (activation: CadVariantActivation) => void;
  activating?: Pick<CadVariantActivation, "tool" | "variantId"> | null;
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
  onActivate,
  activating = null,
  activationError = null,
}: Props) {
  const headingId = useId();
  const inventoryByTool = new Map(inventories.map((inventory) => [inventory.tool, inventory]));
  const retainedCount = TOOL_ORDER.reduce(
    (count, tool) => count + (inventoryByTool.get(tool)?.variants.length ?? 0),
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
          </div>
          <p className="mt-1 text-2xs text-t2">
            <Text id="detail.cad-variants.help">
              Choose the validated bundle each design tool uses. Switching keeps every downloaded
              variant and its evidence.
            </Text>
          </p>
        </div>
        {activationError ? (
          <p role="alert" className="text-2xs font-medium text-err">
            {activationError}
          </p>
        ) : null}
      </header>

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
              activating={activating}
              onActivate={onActivate}
            />
          );
        })}
      </div>
    </Card>
  );
}

function ToolInventory({
  inventory,
  activating,
  onActivate,
}: {
  inventory: CadVariantInventory;
  activating: Pick<CadVariantActivation, "tool" | "variantId"> | null;
  onActivate: (activation: CadVariantActivation) => void;
}) {
  const toolLabel = TOOL_LABELS[inventory.tool];
  const variants = orderedVariants(inventory.variants);
  const preferredRank = variants[0]?.trustRank;
  const activeVariant = variants.find((variant) => variant.id === inventory.activeVariantId);
  const activeMissing = inventory.activeVariantId !== null && !activeVariant;

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
          The active {toolLabel} variant is unavailable. Choose a retained variant.
        </p>
      ) : null}

      {variants.length ? (
        <div className="flex flex-col gap-2">
          {variants.map((variant) => {
            const active = variant.id === inventory.activeVariantId;
            return (
              <VariantRow
                key={variant.id}
                tool={inventory.tool}
                variant={variant}
                active={active}
                preferred={variant.trustRank === preferredRank}
                activating={activating}
                expectedActiveVariantId={inventory.activeVariantId}
                onActivate={onActivate}
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
  preferred,
  activating,
  expectedActiveVariantId,
  onActivate,
}: {
  tool: CadVariantTool;
  variant: CadVariant;
  active: boolean;
  preferred: boolean;
  activating: Pick<CadVariantActivation, "tool" | "variantId"> | null;
  expectedActiveVariantId: string | null;
  onActivate: (activation: CadVariantActivation) => void;
}) {
  const toolLabel = TOOL_LABELS[tool];
  const switching = activating?.tool === tool && activating.variantId === variant.id;
  const anotherSwitchRunning = activating !== null && !switching;
  const artifacts = orderedArtifacts(variant.artifacts);
  const artifactSummary = [
    ...new Set(artifacts.map((artifact) => ARTIFACT_LABELS[artifact.kind])),
  ].join(", ");
  const fileSummary = artifacts.map((artifact) => artifact.fileName).join(", ");

  return (
    <article
      aria-label={`${variant.provider} ${toolLabel} variant${active ? ", active" : ""}`}
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
              Active
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

        {!active ? (
          <div className="mt-2 flex justify-end border-t border-line pt-2">
            <Button
              type="button"
              small
              disabled={switching || anotherSwitchRunning}
              aria-busy={switching || undefined}
              aria-label={`Use ${variant.provider} variant for ${toolLabel}`}
              onClick={() =>
                onActivate({
                  tool,
                  variantId: variant.id,
                  expectedActiveVariantId,
                })
              }
            >
              {switching ? (
                <Text id="detail.cad-variants.switching">Switching...</Text>
              ) : (
                <Text id="detail.cad-variants.use">Use This Variant</Text>
              )}
            </Button>
          </div>
        ) : null}
      </div>
    </article>
  );
}
