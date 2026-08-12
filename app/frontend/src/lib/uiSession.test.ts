import { api } from "../api/client";
import {
  MAX_OPEN_COMPONENTS,
  UI_SESSION_VERSION,
  closeComponentInSession,
  componentView,
  defaultComponentView,
  defaultUiSession,
  flushUiSession,
  migrateUiSession,
  openComponentInSession,
  parseUiSession,
  pruneOpenComponents,
  readUiSession,
  resetUiSessionForTests,
  setComponentViewInSession,
  setPendingIntakeDraft,
  updateUiSession,
  type IntakeDraftBodyV1,
  type UiSessionSnapshotV2,
} from "./uiSession";

const DRAFT_ID = "4f204a7e-e610-4a75-b575-569bca2b3470";

/** A persisted v1 snapshot: the current shape minus everything v2 added, at version 1. */
function v1Snapshot(): Record<string, unknown> {
  const {
    open_components: _open,
    active_component: _active,
    component_views: _views,
    ...rest
  } = defaultUiSession();
  return { ...rest, version: 1 };
}

function v2Snapshot(componentId = "part-42"): Record<string, unknown> {
  const snapshot = defaultUiSession() as unknown as Record<string, unknown>;
  snapshot.version = 2;
  snapshot.open_components = [componentId];
  snapshot.active_component = componentId;
  const view = { ...defaultComponentView() } as Record<string, unknown>;
  delete view.cad_view;
  snapshot.component_views = { [componentId]: view };
  return snapshot;
}

/** Open `count` components in order, so the bound and the eviction order are exercised honestly. */
function withOpen(count: number): UiSessionSnapshotV2 {
  let snapshot = defaultUiSession();
  for (let index = 0; index < count; index += 1) {
    snapshot = openComponentInSession(snapshot, `part-${index}`);
  }
  return snapshot;
}

function draft(): IntakeDraftBodyV1 {
  const networkInput = { kind: "mpn", value: "TPD6E05U06RVZR" } as const;
  return {
    network_input: networkInput,
    review: {
      lookup_input: networkInput,
      enrichment_result: null,
      candidates: [],
    },
  };
}

describe("durable UI session", () => {
  beforeEach(() => {
    resetUiSessionForTests();
    vi.restoreAllMocks();
  });

  it("accepts the exact bounded v2 contract and rejects unknown or hostile fields", () => {
    const valid = defaultUiSession();
    valid.route = "settings";
    valid.selected_ids.component = "component-1";
    valid.selected_ids.workflow_batch = "batch-9";
    valid.search_filters.options = [{ key: "package", values: ["SOT-23"] }];
    valid.search_filters.ranges = [{ key: "voltage", min: 1, max: 5 }];
    valid.search_sort = {
      kind: "spec",
      key: "voltage",
      numeric: true,
      direction: "desc",
    };
    valid.intake_draft_ref = { draft_id: DRAFT_ID, revision: 3 };

    expect(parseUiSession(valid)).toEqual(valid);
    expect(parseUiSession({ ...valid, bearer_token: "do-not-store" })).toBeNull();
    expect(
      parseUiSession({
        ...valid,
        component_filters: { ...valid.component_filters, query: "x".repeat(2_049) },
      }),
    ).toBeNull();
    expect(
      parseUiSession({
        ...valid,
        search_filters: {
          ...valid.search_filters,
          ranges: [{ key: "voltage", min: Number.NaN, max: 5 }],
        },
      }),
    ).toBeNull();
    expect(
      parseUiSession({
        ...valid,
        intake_draft_ref: { draft_id: "../../secret", revision: 1 },
      }),
    ).toBeNull();
  });

  it("exports the last synchronous state and keeps raw intake content outside the snapshot", () => {
    updateUiSession((current) => ({
      ...current,
      route: "components",
      selected_ids: { ...current.selected_ids, component: "part-17" },
      open_surface: "add_part",
    }));
    setPendingIntakeDraft(draft());

    const exported = window.__STOCKROOM_EXPORT_UI_SESSION__?.();
    expect(exported?.snapshot.selected_ids.component).toBe("part-17");
    expect(exported?.snapshot.open_surface).toBe("add_part");
    expect(exported?.snapshot).not.toHaveProperty("network_input");
    expect(exported?.intake_draft?.network_input.value).toBe("TPD6E05U06RVZR");
    expect(exported?.intake_draft).toEqual(
      expect.objectContaining({ draft_id: null, revision: 0 }),
    );
  });

  it("stages a draft before persisting the snapshot reference", async () => {
    const create = vi.spyOn(api, "createIntakeDraft").mockImplementation(async (body) => ({
      schema: "stockroom.intake-draft",
      version: 1,
      ...(body as object),
      draft_id: DRAFT_ID,
      revision: 1,
    }));
    const put = vi.spyOn(api, "putUiSession").mockImplementation(async (body) => body);
    setPendingIntakeDraft(draft());
    updateUiSession((current) => ({ ...current, open_surface: "add_part" }));

    await flushUiSession();

    expect(create).toHaveBeenCalledTimes(1);
    expect(put).toHaveBeenCalledWith(
      expect.objectContaining({
        intake_draft_ref: { draft_id: DRAFT_ID, revision: 1 },
        open_surface: "add_part",
      }),
    );
    expect(readUiSession().intake_draft_ref).toEqual({
      draft_id: DRAFT_ID,
      revision: 1,
    });
  });

  it("restores selection, filters, scroll, open surface, and event cursor as one snapshot", () => {
    const restored = defaultUiSession();
    restored.route = "components";
    restored.selected_ids.component = "part-42";
    restored.selected_ids.workflow_batch = "batch-42";
    restored.component_filters = {
      query: "usb",
      category: "Connectors",
      complete_only: true,
      duplicates_only: false,
    };
    restored.component_list_anchor = { part_id: "part-40", offset_px: 18 };
    restored.search_filters = {
      query: "usb c",
      category: "Connectors",
      in_stock: true,
      options: [{ key: "mount", values: ["SMD"] }],
      ranges: [],
    };
    restored.search_results = {
      active_part_id: "part-42",
      anchor_part_id: "part-39",
      offset_px: 12,
    };
    restored.detail_tab = "handoff";
    restored.open_surface = "search";
    restored.event_sequence = 917;

    resetUiSessionForTests(restored);

    expect(readUiSession()).toEqual(restored);
    expect(window.__STOCKROOM_EXPORT_UI_SESSION__?.().snapshot).toEqual(restored);
  });
});

describe("UI session migrations", () => {
  beforeEach(() => {
    resetUiSessionForTests();
  });

  it("upgrades a persisted v1 snapshot instead of failing closed to defaults", () => {
    const stored = v1Snapshot();
    stored.route = "components";
    stored.selected_ids = {
      ...(stored.selected_ids as object),
      component: "part-42",
    };
    stored.component_filters = {
      query: "usb",
      category: "Connectors",
      complete_only: true,
      duplicates_only: false,
    };
    stored.component_list_anchor = { part_id: "part-40", offset_px: 18 };
    stored.event_sequence = 917;

    const parsed = parseUiSession(stored);

    // Everything a v1 install had is still here. Losing the filters and the anchor on a version
    // bump is exactly the failure the migration exists to prevent.
    expect(parsed?.component_filters.query).toBe("usb");
    expect(parsed?.component_list_anchor).toEqual({ part_id: "part-40", offset_px: 18 });
    expect(parsed?.event_sequence).toBe(917);
    expect(parsed?.version).toBe(3);
    // The one component a v1 snapshot could describe becomes the one open tab, and the picker
    // selection that named it is KEPT: it still drives the highlighted row.
    expect(parsed?.selected_ids.component).toBe("part-42");
    expect(parsed?.open_components).toEqual(["part-42"]);
    expect(parsed?.active_component).toBe("part-42");
    expect(parsed?.component_views).toEqual({});
  });

  it("adds the Models CAD view when upgrading an exact v2 component workspace", () => {
    const parsed = parseUiSession(v2Snapshot());

    expect(parsed?.version).toBe(3);
    expect(parsed?.component_views["part-42"]?.cad_view).toBe("models");
  });

  it("keeps Manage Models scoped to one open component", () => {
    const snapshot = defaultUiSession();
    snapshot.open_components = ["a", "b"];
    snapshot.active_component = "a";
    snapshot.component_views = {
      a: { ...defaultComponentView(), cad_view: "manage-models" },
      b: { ...defaultComponentView(), cad_view: "models" },
    };

    expect(parseUiSession(snapshot)?.component_views).toEqual(snapshot.component_views);
  });

  it("rejects a component CAD view outside the closed vocabulary", () => {
    const snapshot = defaultUiSession();
    snapshot.open_components = ["a"];
    snapshot.component_views = {
      a: { ...defaultComponentView(), cad_view: "downloads" as "models" },
    };

    expect(parseUiSession(snapshot)).toBeNull();
  });

  it("migrates a v1 snapshot with no selection to an empty strip", () => {
    const parsed = parseUiSession(v1Snapshot());
    expect(parsed?.open_components).toEqual([]);
    expect(parsed?.active_component).toBeNull();
  });

  it("gains a v1 payload nothing by being old: it still faces the v2 validation", () => {
    expect(parseUiSession({ ...v1Snapshot(), bearer_token: "do-not-store" })).toBeNull();
  });

  it("falls back to defaults for an unknown or newer version", () => {
    expect(parseUiSession({ ...defaultUiSession(), version: 4 })).toBeNull();
    expect(parseUiSession({ ...v1Snapshot(), version: 0 })).toBeNull();
    // A payload that is not this schema at all is passed through untouched, then rejected.
    const foreign = { ...defaultUiSession(), schema: "something.else" };
    expect(migrateUiSession(foreign)).toBe(foreign);
    expect(parseUiSession(foreign)).toBeNull();
  });
});

describe("opened components", () => {
  beforeEach(() => {
    resetUiSessionForTests();
  });

  it("folds a duplicated open component into one tab", () => {
    const snapshot = defaultUiSession();
    snapshot.open_components = ["a", "b", "a"];
    snapshot.active_component = "b";
    expect(parseUiSession(snapshot)?.open_components).toEqual(["a", "b"]);
  });

  it("never opens the same component twice and never reorders the strip", () => {
    let snapshot = openComponentInSession(defaultUiSession(), "a");
    snapshot = openComponentInSession(snapshot, "b");
    snapshot = openComponentInSession(snapshot, "a");
    expect(snapshot.open_components).toEqual(["a", "b"]);
    expect(snapshot.active_component).toBe("a");
  });

  it("holds the bound by evicting the least recently used tab that is not being activated", () => {
    let snapshot = withOpen(MAX_OPEN_COMPONENTS);
    expect(snapshot.open_components).toHaveLength(MAX_OPEN_COMPONENTS);
    // Touch the oldest tab so it is no longer the least recently used one.
    snapshot = openComponentInSession(snapshot, "part-0");
    snapshot = openComponentInSession(snapshot, "overflow");

    expect(snapshot.open_components).toHaveLength(MAX_OPEN_COMPONENTS);
    expect(snapshot.open_components).toContain("overflow");
    expect(snapshot.open_components).toContain("part-0");
    // part-1 was the least recently activated survivor, so it is the one that went.
    expect(snapshot.open_components).not.toContain("part-1");
    expect(snapshot.component_views["part-1"]).toBeUndefined();
    expect(snapshot.active_component).toBe("overflow");
    expect(parseUiSession(snapshot)).not.toBeNull();
  });

  it("rejects a stored strip that is over the bound", () => {
    const snapshot = defaultUiSession();
    snapshot.open_components = Array.from(
      { length: MAX_OPEN_COMPONENTS + 1 },
      (_, index) => `part-${index}`,
    );
    expect(parseUiSession(snapshot)).toBeNull();
  });

  it("drops an active component that is not open", () => {
    const closed = defaultUiSession();
    closed.open_components = ["a"];
    closed.active_component = "b";
    expect(parseUiSession(closed)?.active_component).toBeNull();

    const absent = defaultUiSession();
    absent.active_component = "ghost";
    expect(parseUiSession(absent)?.active_component).toBeNull();
  });

  it("prunes view state for components that are not open", () => {
    const snapshot = defaultUiSession();
    snapshot.open_components = ["a"];
    snapshot.active_component = "a";
    snapshot.component_views = {
      a: defaultComponentView(),
      b: defaultComponentView(),
    };
    expect(Object.keys(parseUiSession(snapshot)?.component_views ?? {})).toEqual(["a"]);
  });

  it("closing a tab keeps the component and hands activation to a neighbour", () => {
    let snapshot = withOpen(3);
    snapshot = openComponentInSession(snapshot, "part-1");
    snapshot = closeComponentInSession(snapshot, "part-1");
    expect(snapshot.open_components).toEqual(["part-0", "part-2"]);
    expect(snapshot.active_component).toBe("part-2");
    expect(snapshot.component_views["part-1"]).toBeUndefined();
    // Closing the last one leaves nothing active rather than an id pointing at no tab.
    snapshot = closeComponentInSession(snapshot, "part-0");
    snapshot = closeComponentInSession(snapshot, "part-2");
    expect(snapshot.open_components).toEqual([]);
    expect(snapshot.active_component).toBeNull();
  });

  it("drops tabs whose component left the library, and never on an empty list", () => {
    const snapshot = withOpen(3);
    const pruned = pruneOpenComponents(snapshot, new Set(["part-0", "part-2"]));
    expect(pruned.open_components).toEqual(["part-0", "part-2"]);
    expect(pruned.active_component).toBe("part-2");
    // Nothing known yet is not the same as nothing left: an unloaded list must not wipe the strip.
    expect(pruneOpenComponents(snapshot, new Set())).toBe(snapshot);
  });

  it("stores per-component view state and round-trips it unchanged", () => {
    let snapshot = openComponentInSession(defaultUiSession(), "a");
    snapshot = setComponentViewInSession(snapshot, "a", {
      info_tab: "sourcing",
      representation_layout: "footprint",
      representation_tool: { footprint: "altium" },
    });
    const parsed = parseUiSession(snapshot);
    expect(parsed).toEqual(snapshot);
    expect(componentView(parsed!, "a")).toEqual({
      info_tab: "sourcing",
      cad_view: "models",
      representation_layout: "footprint",
      representation_tool: { symbol: "", footprint: "altium", model: "" },
    });
    // A second parse of the parsed value is identical: no field drifts on the way through.
    expect(parseUiSession(parsed)).toEqual(parsed);
    // A component that is not open has no view to write.
    expect(setComponentViewInSession(snapshot, "ghost", { info_tab: "sources" })).toBe(snapshot);
  });

  it("rejects an off-vocabulary view state", () => {
    const snapshot = openComponentInSession(defaultUiSession(), "a");
    expect(
      parseUiSession({
        ...snapshot,
        component_views: { a: { ...defaultComponentView(), info_tab: "handoff" } },
      }),
    ).toBeNull();
    expect(
      parseUiSession({
        ...snapshot,
        component_views: {
          a: { ...defaultComponentView(), representation_layout: "everything" },
        },
      }),
    ).toBeNull();
  });

  it("keeps the tab strip through a real session update", () => {
    updateUiSession((current) => openComponentInSession(current, "part-7"));
    expect(readUiSession().open_components).toEqual(["part-7"]);
    expect(readUiSession().active_component).toBe("part-7");
    expect(window.__STOCKROOM_EXPORT_UI_SESSION__?.().snapshot.active_component).toBe("part-7");
  });

  it("posts the whole tab strip to the durable store so it survives a restart", async () => {
    // The tab strip lives in the server-owned document, not only in the same-origin mirror:
    // a restart on a machine whose browser storage was cleared must still reopen the same
    // components. The store validates the same exact key set at the same version, so the
    // snapshot goes out verbatim and the echo parses without being re-joined locally.
    const put = vi.spyOn(api, "putUiSession").mockImplementation(async (body) => body);
    let snapshot = openComponentInSession(defaultUiSession(), "part-1");
    snapshot = openComponentInSession(snapshot, "part-2");
    snapshot.selected_ids.component = "part-1";
    updateUiSession(() => snapshot);

    await flushUiSession();

    const posted = put.mock.calls[0][0] as Record<string, unknown>;
    expect(posted.version).toBe(UI_SESSION_VERSION);
    expect(posted.open_components).toEqual(["part-1", "part-2"]);
    expect(posted.active_component).toBe("part-2");
    expect(posted).toHaveProperty("component_views");
    expect(readUiSession().open_components).toEqual(["part-1", "part-2"]);
    expect(readUiSession().active_component).toBe("part-2");
  });
});
