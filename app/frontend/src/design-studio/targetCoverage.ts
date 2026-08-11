import { isApprovedDynamicDevId } from "../lib/componentDevIds";
import type { DevIdEntry } from "../lib/devIds";
import { ICON_BY_ID } from "../lib/iconRegistry";
import { WORKSPACE_PIECE_REGISTRY } from "../layout/workspacePieces";

export type TargetCoverageIssueCode = "missing-target" | "unregistered-target";

export interface TargetCoverageIssue {
  code: TargetCoverageIssueCode;
  element: Element;
  targetId?: string;
  targetKind?: "dev" | "copy" | "icon" | "layout-piece";
}

export interface TargetLayer {
  key: string;
  id: string;
  kind: "dev" | "copy" | "icon" | "layout-piece";
  label: string;
  parentKey: string | null;
  depth: number;
  occurrences: number;
  /** The stable Dev Mode owner selected when a domain-only row is activated. */
  ownerDevId: string | null;
}

const STABLE_COPY_ID = /^[A-Za-z][A-Za-z0-9]*(?:[.-][A-Za-z0-9]+)*$/;

/** Report explicitly meaningful boundaries that cannot be addressed by a production registry. */
export function coverageIssuesFor(root: ParentNode, registry: DevIdEntry[]): TargetCoverageIssue[] {
  const registeredDevIds = new Set(registry.map((entry) => entry.id));
  const issues: TargetCoverageIssue[] = [];
  for (const element of root.querySelectorAll("[data-design-meaningful]")) {
    const identities = [
      ["dev", element.getAttribute("data-dev-id")],
      ["copy", element.getAttribute("data-copy-id")],
      ["icon", element.getAttribute("data-icon-id")],
      ["layout-piece", element.getAttribute("data-layout-piece")],
    ] as const;
    const present = identities.filter((entry): entry is readonly [typeof entry[0], string] => Boolean(entry[1]));
    if (present.length === 0) {
      issues.push({ code: "missing-target", element });
      continue;
    }
    for (const [kind, id] of present) {
      const valid = kind === "dev"
        ? registeredDevIds.has(id) || isApprovedDynamicDevId(id)
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
  const devById = new Map(registry.map((entry) => [entry.id, entry]));
  const layers: TargetLayer[] = [];
  const byKey = new Map<string, TargetLayer>();
  const lastKeyByElement = new Map<Element, string>();
  const ownerDevByElement = new Map<Element, string>();
  const elements = root.querySelectorAll(
    "[data-dev-id], [data-copy-id], [data-icon-id], [data-layout-piece]",
  );

  for (const element of elements) {
    const devId = element.getAttribute("data-dev-id");
    const identities = [
      ["dev", devId],
      ["copy", element.getAttribute("data-copy-id")],
      ["icon", element.getAttribute("data-icon-id")],
      ["layout-piece", element.getAttribute("data-layout-piece")],
    ] as const;
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
        : kind === "copy"
          ? STABLE_COPY_ID.test(id)
          : kind === "icon"
            ? ICON_BY_ID.has(id)
            : WORKSPACE_PIECE_REGISTRY.has(id);
      if (!valid) continue;
      const key = `${kind}:${id}`;
      const existing = byKey.get(key);
      if (existing) {
        existing.occurrences += 1;
      } else {
        const depth = parentKey ? (byKey.get(parentKey)?.depth ?? -1) + 1 : 0;
        const label = kind === "dev" ? (devById.get(id)?.label ?? id) : `${kind === "layout-piece" ? "Layout Piece" : kind[0].toUpperCase() + kind.slice(1)} · ${id}`;
        const layer: TargetLayer = {
          key,
          id,
          kind,
          label,
          parentKey,
          depth,
          occurrences: 1,
          ownerDevId: kind === "dev" ? id : ownerDevId,
        };
        byKey.set(key, layer);
        layers.push(layer);
      }
      parentKey = key;
      if (kind === "dev") ownerDevId = id;
    }
    if (parentKey) lastKeyByElement.set(element, parentKey);
    if (ownerDevId) ownerDevByElement.set(element, ownerDevId);
  }
  return layers;
}
