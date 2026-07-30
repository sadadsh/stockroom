import { api } from "../api/client";
import {
  defaultUiSession,
  flushUiSession,
  parseUiSession,
  readUiSession,
  resetUiSessionForTests,
  setPendingIntakeDraft,
  updateUiSession,
  type IntakeDraftBodyV1,
} from "./uiSession";

const DRAFT_ID = "4f204a7e-e610-4a75-b575-569bca2b3470";

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

  it("accepts the exact bounded v1 contract and rejects unknown or hostile fields", () => {
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
