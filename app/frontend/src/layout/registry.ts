/**
 * THE PIECE REGISTRY: what can be placed, and everything a placer needs to know about it.
 *
 * A layout document is a tree of references; this is what they refer to. Every placeable unit -
 * the identity header's description line, the preferred-source toolbar, the Documents section -
 * registers one manifest, and the manifest is the whole contract. It states what the piece is
 * called (as a copy id and as the dev ids it renders, never as prose), what data it reads, what
 * actions it exposes, how small it can be, whether it owns a scroll axis, and where a new build
 * should put it if it arrives into a layout that has never seen it.
 *
 * WHAT IS DELIBERATELY NOT HERE: the component. A manifest never holds a render function, a
 * `ReactNode` or an import. The binding from piece id to renderer is a separate table owned by the
 * rendering layer, which is why this module can be read by the commit pipeline, by a test and by a
 * validator without any of them mounting React.
 *
 * The action ids are STRINGS, and only strings, until the action registry exists (plan 1.3). A
 * manifest declaring `component-browser.refresh-offers` is declaring the name of a command, not
 * defining one; when the action registry lands, these are the ids it has to answer for.
 */

/** Which axis a piece scrolls, when it is the one that scrolls. */
export type PieceScrollAxis = "vertical" | "horizontal";

export interface PieceScroll {
  /** True when this piece owns a scroll container of its own. */
  owns: boolean;
  /** The axis it owns. Absent when it owns nothing. */
  axis?: PieceScrollAxis;
}

/**
 * Where a piece belongs when nobody has placed it.
 *
 * Read by auto-placement (plan decision 6): a section shipped into an already-redesigned layout is
 * placed from its own hints and the placement is recorded in the issues list, rather than the
 * update being held behind a tray nobody empties. `siblingGroup` is what keeps a new sourcing
 * section among the sourcing sections instead of merely somewhere in that column.
 */
export interface PieceHome {
  regionId: string;
  siblingGroup: string;
}

export interface PieceManifest {
  /** Stable, dot-namespaced, lowercase-kebab per segment - the `lib/devIds` convention. */
  id: string;
  /**
   * The piece's display name, as a COPY ID.
   *
   * Interface text lives in the copy layer and nowhere else, so a manifest names the id and the
   * copy layer resolves it. Absent where the piece has no heading of its own in the current
   * arrangement (a line in the identity header is not titled); such a piece is named in a
   * catalogue by its dev ids below, which already carry labels in `lib/devIds`.
   */
  nameCopyId?: string;
  /**
   * The `data-dev-id`s this piece renders, its own first.
   *
   * This is the join between the layout system and the id system that already exists: the piece
   * partition is a coarsening of the dev-id partition, and stating it makes that checkable rather
   * than asserted.
   */
  devIds: readonly string[];
  /**
   * What this piece reads: dossier paths and query keys, as strings.
   *
   * `dossier.<path>` is a path into the one read model the opened component renders from;
   * `query.<key>` is a TanStack query key the piece mounts a fetch for. Read off the current
   * component's own props and hooks, never guessed - a piece that claims data it does not read
   * would make the field picker offer bindings that change nothing.
   */
  dataNeeds: readonly string[];
  /** Action ids this piece exposes. Declared names; the action registry is a later phase. */
  actions: readonly string[];
  /** Pixels, and only where the current source states a number. Absent beats invented. */
  minWidth?: number;
  minHeight?: number;
  preferredWidth?: number;
  preferredHeight?: number;
  scroll: PieceScroll;
  home: PieceHome;
  /** The module this manifest transcribes, so the granularity decision can be re-read. */
  source: string;
}

export type RegistryIssueCode = "duplicate-piece";

export interface RegistryIssue {
  code: RegistryIssueCode;
  pieceId: string;
  detail?: Readonly<Record<string, string>>;
}

export interface PieceRegistry {
  /**
   * Add a manifest. Returns the issue a duplicate id produced, or `null`.
   *
   * A duplicate is REPORTED and the first registration stands. Throwing would take down whatever
   * module happened to import second, and silently replacing would make the winner depend on
   * import order - which is how one build places a piece and the next places a different one.
   */
  register(manifest: PieceManifest): RegistryIssue | null;
  has(id: string): boolean;
  get(id: string): PieceManifest | undefined;
  /** Registration order, which is the order manifests were declared in source. */
  list(): readonly PieceManifest[];
}

export function createPieceRegistry(): PieceRegistry {
  const byId = new Map<string, PieceManifest>();
  const order: PieceManifest[] = [];

  return {
    register(manifest: PieceManifest): RegistryIssue | null {
      const existing = byId.get(manifest.id);
      if (existing) {
        return {
          code: "duplicate-piece",
          pieceId: manifest.id,
          detail: { kept: existing.source, rejected: manifest.source },
        };
      }
      byId.set(manifest.id, manifest);
      order.push(manifest);
      return null;
    },
    has(id: string): boolean {
      return byId.has(id);
    },
    get(id: string): PieceManifest | undefined {
      return byId.get(id);
    },
    list(): readonly PieceManifest[] {
      return order;
    },
  };
}

/** Build a registry from a list, keeping every duplicate report rather than the last one. */
export function registerPieces(manifests: readonly PieceManifest[]): {
  registry: PieceRegistry;
  issues: RegistryIssue[];
} {
  const registry = createPieceRegistry();
  const issues: RegistryIssue[] = [];
  for (const manifest of manifests) {
    const issue = registry.register(manifest);
    if (issue) issues.push(issue);
  }
  return { registry, issues };
}
