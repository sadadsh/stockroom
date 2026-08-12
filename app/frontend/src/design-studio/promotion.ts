import { api, ApiError } from "../api/client";
import type {
  DevPromoteBody,
  DevPromoteResult,
  DevSaveBody,
  DevWorkspaceStatus,
} from "../api/types";
import { isApprovedDynamicDevId } from "../lib/componentDevIds";
import { copyPlaceholderDeclarations } from "../lib/copyPlaceholders";
import { DEV_IDS, DEV_ID_BY_ID } from "../lib/devIds";
import { isApplicableElementOverride } from "../lib/elementLayout";
import { ICON_BY_ID } from "../lib/iconRegistry";
import { ownerAuthoredCopyIds } from "../lib/devModeSave";
import type { Theme } from "../lib/theme";
import { draftThemeTokens } from "../layout/validateContrast";
import { validateDocument } from "../layout/validateDocument";
import type { ValidatorIssue } from "../layout/validatorIssues";
import { WORKSPACE_PIECE_REGISTRY } from "../layout/workspacePieces";
import { resolveDesign, type DesignDocument } from "./document";
import { bootstrapScenarioRegistry } from "./scenarios";
import { routeCoverageIssues } from "./scenarioRegistry";
import { coverageIssuesFor } from "./targetCoverage";

export interface DesignPromotionIssue {
  code: string;
  source: "scenario" | "target" | "layout" | "design";
  targetId?: string;
  validatorIssue?: ValidatorIssue;
}

export type PromotionResult =
  | { state: "success"; message: string; commit: string }
  | { state: "blocked" | "failure"; message: string };

export interface PromotionStatus {
  state: "checking" | "ready" | "running" | "blocked" | "success" | "failure";
  message: string;
}

export class PromotionValidationError extends Error {
  readonly issues: readonly DesignPromotionIssue[];

  constructor(issues: readonly DesignPromotionIssue[]) {
    const noun = issues.length === 1 ? "issue" : "issues";
    super(
      `Resolve ${issues.length} Design Studio ${noun} before making this design the app default.`,
    );
    this.name = "PromotionValidationError";
    this.issues = issues;
  }
}

const COPY_ID = /^[A-Za-z][A-Za-z0-9]*(?:[.-][A-Za-z0-9]+)*$/;

function baseTargetId(id: string): string {
  const separator = id.lastIndexOf("::");
  if (separator === -1) return id;
  const suffix = id.slice(separator + 2);
  return suffix === "text" || suffix === "icon" ? id.slice(0, separator) : id;
}

function isKnownDevTarget(id: string): boolean {
  const base = baseTargetId(id);
  return DEV_ID_BY_ID.has(base) || isApprovedDynamicDevId(base);
}

function targetIssues(document: DesignDocument, theme: Theme): DesignPromotionIssue[] {
  const resolved = resolveDesign(document, document.activeVariationId, theme);
  const issues: DesignPromotionIssue[] = [];
  const add = (code: string, targetId: string) => {
    issues.push({ code, source: "target", targetId });
  };

  for (const id of Object.keys(resolved.elements)) {
    if (!isKnownDevTarget(id)) add("missing-target", id);
    for (const [property, value] of Object.entries(resolved.elements[id])) {
      if (!isApplicableElementOverride(property, value)) {
        add("unsupported-design-value", `${id}:${property}`);
      }
    }
  }
  for (const id of Object.keys(resolved.behaviors)) {
    if (!isKnownDevTarget(id)) add("missing-target", id);
  }
  for (const [id, override] of Object.entries(resolved.icons)) {
    if (!ICON_BY_ID.has(id)) add("missing-target", id);
    if (override.swapToId && !ICON_BY_ID.has(override.swapToId)) {
      add("missing-target", override.swapToId);
    }
  }
  for (const id of Object.keys(resolved.copy)) {
    if (!COPY_ID.test(id)) add("missing-target", id);
  }
  for (const id of Object.keys(document.targetScopes)) {
    if (!isKnownDevTarget(id)) add("missing-target", id);
  }
  return issues;
}

/** Collect every promotion gate before source status, save, or publish is allowed to run. */
export function collectDesignIssues(
  document: DesignDocument,
  theme: Theme = "dark",
  targetRoot: ParentNode | null = typeof window === "undefined" ? null : window.document,
): DesignPromotionIssue[] {
  const issues: DesignPromotionIssue[] = [];
  for (const issue of [
    ...bootstrapScenarioRegistry.issues,
    ...routeCoverageIssues(bootstrapScenarioRegistry),
  ]) {
    issues.push({ code: issue.code, source: "scenario", targetId: issue.scenarioId ?? issue.value });
  }
  issues.push(...targetIssues(document, theme));
  if (targetRoot) {
    const productRoots = targetRoot instanceof Element && targetRoot.matches("[data-design-product-root]")
      ? [targetRoot]
      : Array.from(targetRoot.querySelectorAll("[data-design-product-root]"));
    const coverageRoots: ParentNode[] = productRoots.length > 0
      ? productRoots
      : targetRoot instanceof Element
        ? [targetRoot]
        : [];
    for (const coverageRoot of coverageRoots) {
      for (const issue of coverageIssuesFor(coverageRoot, DEV_IDS)) {
        issues.push({ code: issue.code, source: "target", targetId: issue.targetId });
      }
    }
  }
  const resolved = resolveDesign(document, document.activeVariationId, theme);
  if (resolved.layout) {
    for (const validatorIssue of validateDocument(
      resolved.layout,
      WORKSPACE_PIECE_REGISTRY,
      draftThemeTokens(resolved.tokens),
    )) {
      issues.push({
        code: validatorIssue.code,
        source: validatorIssue.code.startsWith("contrast-") ? "design" : "layout",
        targetId: validatorIssue.subject.id,
        validatorIssue,
      });
    }
  }
  return issues;
}

/** Translate the active resolved personal design into the existing closed source-writer contract. */
export function promotionPlan(
  document: DesignDocument,
  theme: Theme = "dark",
  targetRoot: ParentNode | null = typeof window === "undefined" ? null : window.document,
): DevSaveBody {
  const issues = collectDesignIssues(document, theme, targetRoot);
  if (issues.length > 0) throw new PromotionValidationError(issues);
  const resolved = resolveDesign(document, document.activeVariationId, theme);
  return {
    tokens: structuredClone(resolved.tokens),
    copy: { ...resolved.copy },
    icons: structuredClone(resolved.icons),
    elements: structuredClone(resolved.elements),
    behaviors: structuredClone(resolved.behaviors),
    copyPlaceholders: copyPlaceholderDeclarations(),
    layout: { workspace: resolved.layout ? structuredClone(resolved.layout) : null },
    committedIssues: { workspace: [] },
    ownerAuthoredCopy: ownerAuthoredCopyIds(resolved.copy),
  };
}

/** Preserve the base plus every named variation as independently validated dark/light projections. */
export function promotionTransactionPlan(
  document: DesignDocument,
  message: string,
  activeTheme: Theme = "dark",
  targetRoot: ParentNode | null = typeof window === "undefined" ? null : window.document,
): DevPromoteBody {
  const translated = (variationId: string, theme: Theme): DevSaveBody => promotionPlan(
    { ...document, activeVariationId: variationId },
    theme,
    targetRoot,
  );
  const base = {
    dark: translated("", "dark"),
    light: translated("", "light"),
  };
  const variations = Object.fromEntries(Object.values(document.variations).map((variation) => [
    variation.id,
    {
      title: variation.title,
      extends: variation.extends,
      themes: {
        dark: translated(variation.id, "dark"),
        light: translated(variation.id, "light"),
      },
    },
  ]));
  const activePair = document.activeVariationId
    ? variations[document.activeVariationId]?.themes
    : base;
  if (!activePair) throw new PromotionValidationError([{ code: "unknown-active-variation", source: "design" }]);
  return {
    message,
    source: structuredClone(activePair[activeTheme]),
    translations: { base, variations },
  };
}

export interface PromotionClient {
  devStatus(): Promise<DevWorkspaceStatus>;
  devPromote(body: DevPromoteBody): Promise<DevPromoteResult>;
}

export interface RunPromotionOptions {
  document: DesignDocument;
  activeScenarioId: string | null;
  theme: Theme;
  message: string;
  client?: PromotionClient;
  targetRoot?: ParentNode | null;
}

function preSaveStatusBlocker(status: DevWorkspaceStatus): string | null {
  if (!status.available) return status.publish_blocker;
  if (status.can_publish || status.publish_blocker.startsWith("Save a Dev Mode change")) return null;
  return status.publish_blocker || "This source checkout cannot publish a design.";
}

function failureMessage(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return "Could not make this design the app default.";
}

/** Real Data-only status -> save -> publish orchestration. It never mutates the personal document. */
export async function runPersonalDesignPromotion({
  document,
  activeScenarioId,
  theme,
  message,
  client = api,
  targetRoot = typeof window === "undefined" ? null : window.document,
}: RunPromotionOptions): Promise<PromotionResult> {
  if (activeScenarioId !== null) {
    return {
      state: "blocked",
      message: "Return to Real Data before making this design the app default.",
    };
  }

  let body: DevPromoteBody;
  try {
    body = promotionTransactionPlan(document, message, theme, targetRoot);
  } catch (error) {
    return { state: "blocked", message: failureMessage(error) };
  }

  try {
    const status = await client.devStatus();
    const blocker = preSaveStatusBlocker(status);
    if (blocker) return { state: "blocked", message: blocker };
    const published = await client.devPromote(body);
    return {
      state: "success",
      message: `Promoted personal design at ${published.commit}.`,
      commit: published.commit,
    };
  } catch (error) {
    return { state: "failure", message: failureMessage(error) };
  }
}

export async function sourcePromotionStatus(
  client: Pick<PromotionClient, "devStatus"> = api,
): Promise<PromotionStatus> {
  try {
    const status = await client.devStatus();
    const blocker = preSaveStatusBlocker(status);
    return blocker
      ? { state: "blocked", message: blocker }
      : { state: "ready", message: "Ready to make this design the app default." };
  } catch (error) {
    return { state: "failure", message: failureMessage(error) };
  }
}
