import { isApprovedDynamicDevId } from "../lib/componentDevIds";
import type { DevIdEntry } from "../lib/devIds";
import { ICON_BY_ID } from "../lib/iconRegistry";
import { WORKSPACE_PIECE_REGISTRY } from "../layout/workspacePieces";
import {
  ensureDesignIdentities,
  exactDesignTargetAuthority,
  isGeneratedDesignId,
} from "../lib/designIdentity";

export type TargetCoverageIssueCode = "missing-target" | "unregistered-target";

export interface TargetCoverageIssue {
  code: TargetCoverageIssueCode;
  element: Element;
  targetId?: string;
  targetKind?: "dev" | "generated" | "copy" | "icon" | "layout-piece";
}

export interface TargetLayer {
  key: string;
  id: string;
  kind: "dev" | "generated" | "copy" | "icon" | "layout-piece";
  label: string;
  parentKey: string | null;
  depth: number;
  occurrences: number;
  /** Exact persisted address for this concrete row; null means the DOM is structurally ambiguous. */
  overrideId: string | null;
  /** Concrete live occurrence selected by this row. */
  element: Element;
  /** The stable Dev Mode owner selected when a domain-only row is activated. */
  ownerDevId: string | null;
  /** Default Layers stays concise; All Elements reveals every generated wrapper boundary. */
  meaningful: boolean;
}

const STABLE_COPY_ID = /^[A-Za-z][A-Za-z0-9]*(?:[.-][A-Za-z0-9]+)*$/;
const INTERACTIVE_BOUNDARY_SELECTOR = [
  "button",
  "a[href]",
  "input:not([type='hidden'])",
  "select",
  "textarea",
  "[role='button']",
  "[role='dialog']",
  "[role='tab']",
  "[role='menuitem']",
  "[role='option']",
  "[role='slider']",
  "[role='separator'][tabindex]",
  "[data-design-meaningful]",
].join(", ");
const SEMANTIC_LAYOUT_TAGS = new Set(["ARTICLE", "ASIDE", "FOOTER", "HEADER", "MAIN", "NAV", "SECTION"]);
const AUTHORED_TARGET_SELECTOR = "[data-dev-id], [data-copy-id], [data-icon-id], [data-layout-piece]";

const TARGET_IDENTITY_SELECTOR = "[data-dev-id], [data-design-id], [data-copy-id], [data-icon-id], [data-layout-piece]";
function identityOwner(element: Element): Element | null {
  if (element.matches(TARGET_IDENTITY_SELECTOR)) return element;
  return null;
}

function hasDirectVisibleText(element: Element): boolean {
  return Array.from(element.childNodes).some(
    (node) => node.nodeType === Node.TEXT_NODE && Boolean(node.textContent?.trim()),
  );
}

export function isMeaningfulTargetElement(element: Element): boolean {
  return (
    element.matches(INTERACTIVE_BOUNDARY_SELECTOR) ||
    element.localName === "svg" ||
    element.localName === "img" ||
    SEMANTIC_LAYOUT_TAGS.has(element.tagName) ||
    hasDirectVisibleText(element)
  );
}

function isIndependentlyUsefulGeneratedTarget(element: Element): boolean {
  return isMeaningfulTargetElement(element) && !element.matches(AUTHORED_TARGET_SELECTOR);
}

/** Report every Stockroom-owned rendered element that cannot be globally addressed. */
export function coverageIssuesFor(root: ParentNode, registry: DevIdEntry[]): TargetCoverageIssue[] {
  ensureDesignIdentities(root);
  const registeredDevIds = new Set(registry.map((entry) => entry.id));
  const issues: TargetCoverageIssue[] = [];
  for (const element of Array.from(root.querySelectorAll("*"))) {
    if (element.closest('[data-design-technical-content="true"]')) continue;
    if (element.localName !== "svg" && element.closest("svg")) continue;
    const owner = identityOwner(element);
    if (!owner) {
      issues.push({ code: "missing-target", element });
      continue;
    }
    const identities = [
      ["dev", owner.getAttribute("data-dev-id")],
      ["generated", owner.getAttribute("data-design-id")],
      ["copy", owner.getAttribute("data-copy-id")],
      ["icon", owner.getAttribute("data-icon-id")],
      ["layout-piece", owner.getAttribute("data-layout-piece")],
    ] as const;
    const present = identities.filter((entry): entry is readonly [typeof entry[0], string] => Boolean(entry[1]));
    if (present.length === 0) {
      issues.push({ code: "missing-target", element });
      continue;
    }
    for (const [kind, id] of present) {
      const valid = kind === "dev"
        ? registeredDevIds.has(id) || isApprovedDynamicDevId(id)
        : kind === "generated"
          ? isGeneratedDesignId(id)
        : kind === "copy"
          ? STABLE_COPY_ID.test(id)
          : kind === "icon"
            ? ICON_BY_ID.has(id)
            : WORKSPACE_PIECE_REGISTRY.has(id);
      if (!valid) issues.push({ code: "unregistered-target", element, targetId: id, targetKind: kind });
    }
  }
  return issues;
}

/** Build the rendered target tree with keys derived only from stable registry identities. */
export function targetLayersFor(root: ParentNode, registry: DevIdEntry[]): TargetLayer[] {
  ensureDesignIdentities(root);
  const devById = new Map(registry.map((entry) => [entry.id, entry]));
  const layers: TargetLayer[] = [];
  const byKey = new Map<string, TargetLayer>();
  const lastKeyByElement = new Map<Element, string>();
  const ownerDevByElement = new Map<Element, string>();
  const elements = Array.from(root.querySelectorAll(
    "[data-dev-id], [data-design-id], [data-copy-id], [data-icon-id], [data-layout-piece]",
  ));
  const identityTotals = new Map<string, number>();
  for (const element of elements) {
    for (const [kind, id] of [
      ["dev", element.getAttribute("data-dev-id")],
      ["generated", element.getAttribute("data-design-id")],
      ["copy", element.getAttribute("data-copy-id")],
      ["icon", element.getAttribute("data-icon-id")],
      ["layout-piece", element.getAttribute("data-layout-piece")],
    ] as const) {
      if (!id) continue;
      const baseKey = `${kind}:${id}`;
      identityTotals.set(baseKey, (identityTotals.get(baseKey) ?? 0) + 1);
    }
  }
  const seenOccurrences = new Map<string, number>();

  for (const element of elements) {
    const devId = element.getAttribute("data-dev-id");
    const identities = [
      ["dev", devId],
      ["generated", element.getAttribute("data-design-id")],
      ["copy", element.getAttribute("data-copy-id")],
      ["icon", element.getAttribute("data-icon-id")],
      ["layout-piece", element.getAttribute("data-layout-piece")],
    ] as const;
    const authority = exactDesignTargetAuthority(element);
    let ancestor = element.parentElement;
    let parentKey: string | null = null;
    let ownerDevId: string | null = null;
    while (ancestor && (!parentKey || !ownerDevId)) {
      parentKey ??= lastKeyByElement.get(ancestor) ?? null;
      ownerDevId ??= ownerDevByElement.get(ancestor) ?? null;
      ancestor = ancestor.parentElement;
    }
    for (const [kind, id] of identities) {
      if (!id) continue;
      const valid = kind === "dev"
        ? devById.has(id) || isApprovedDynamicDevId(id)
        : kind === "generated"
          ? isGeneratedDesignId(id)
        : kind === "copy"
          ? STABLE_COPY_ID.test(id)
          : kind === "icon"
            ? ICON_BY_ID.has(id)
            : WORKSPACE_PIECE_REGISTRY.has(id);
      if (!valid) continue;
      const baseKey = `${kind}:${id}`;
      const occurrenceTotal = identityTotals.get(baseKey) ?? 1;
      const occurrenceNumber = (seenOccurrences.get(baseKey) ?? 0) + 1;
      seenOccurrences.set(baseKey, occurrenceNumber);
      const key = occurrenceTotal > 1
        ? authority
          ? `${baseKey}@${authority.overrideId}`
          : `${baseKey}@ambiguous`
        : baseKey;
      const existing = byKey.get(key);
      if (existing) {
        existing.occurrences += 1;
        if (kind === "generated") existing.meaningful = false;
      } else {
        const depth = parentKey ? (byKey.get(parentKey)?.depth ?? -1) + 1 : 0;
        const baseLabel = kind === "dev" ? (devById.get(id)?.label ?? id) : `${kind === "layout-piece" ? "Layout Piece" : kind === "generated" ? "Element" : kind[0].toUpperCase() + kind.slice(1)} · ${id}`;
        const label = occurrenceTotal > 1 && authority
          ? `${baseLabel} · ${occurrenceNumber} of ${occurrenceTotal}`
          : occurrenceTotal > 1
            ? `${baseLabel} · Ambiguous (${occurrenceTotal})`
            : baseLabel;
        const layer: TargetLayer = {
          key,
          id,
          kind,
          label,
          parentKey,
          depth,
          occurrences: 1,
          overrideId: authority?.overrideId ?? null,
          element,
          ownerDevId: kind === "dev" || kind === "generated" ? id : ownerDevId,
          meaningful: kind !== "generated"
            || (occurrenceTotal === 1 && isIndependentlyUsefulGeneratedTarget(element)),
        };
        byKey.set(key, layer);
        layers.push(layer);
      }
      parentKey = key;
      if (kind === "dev" || kind === "generated") ownerDevId = id;
    }
    if (parentKey) lastKeyByElement.set(element, parentKey);
    if (ownerDevId) ownerDevByElement.set(element, ownerDevId);
  }
  return layers;
}
