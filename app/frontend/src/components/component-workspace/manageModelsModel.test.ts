import type { ProviderCoverageRow } from "../../api/dossierTypes";
import { bestCompleteProvider, orderedManageModelsProviders } from "./manageModelsModel";

function row(id: string, complete: boolean, order: number): ProviderCoverageRow {
  const status = complete ? "available" : "not_available";
  return {
    id,
    label: id,
    order,
    url: `https://${id}.example`,
    urlKind: "evidence",
    instruction: "",
    needsLogin: false,
    aggregator: false,
    distributor: false,
    statusCounts: { unknown: 0, available: complete ? 3 : 2, not_available: complete ? 0 : 1, downloaded: 0, validated: 0 },
    complete,
    symbol: { status: "available", origin: "official_api", userAssertion: null },
    footprint: { status: "available", origin: "official_api", userAssertion: null },
    model: { status, origin: "official_api", userAssertion: null },
    kicad: { count: 0, total: 3, summary: "0/3", complete: false, supported: true },
    altium: { count: 0, total: 3, summary: "0/3", complete: false, supported: true },
  };
}

describe("Manage Models provider policy", () => {
  it("keeps all providers while stably putting complete sets first", () => {
    const providers = orderedManageModelsProviders({
      artifacts: ["symbol", "footprint", "model"],
      statuses: ["unknown", "available", "not_available", "downloaded", "validated"],
      tools: [],
      completeProviders: ["complete-b", "complete-c"],
      rows: [row("partial-a", false, 1), row("complete-b", true, 2), row("complete-c", true, 3), row("partial-d", false, 4)],
    });

    expect(providers.map((provider) => provider.row.id)).toEqual([
      "complete-b",
      "complete-c",
      "partial-a",
      "partial-d",
    ]);
    expect(bestCompleteProvider(providers)?.row.id).toBe("complete-b");
  });

  it("never promotes a partial provider and names its missing role", () => {
    const providers = orderedManageModelsProviders({
      artifacts: ["symbol", "footprint", "model"], statuses: [], tools: [], completeProviders: [],
      rows: [row("partial", false, 1)],
    });

    expect(bestCompleteProvider(providers)).toBeNull();
    expect(providers[0]?.missing).toEqual(["model"]);
    expect(providers[0]?.complete).toBe(false);
  });

  it("never auto-opens a complete provider without a reachable route", () => {
    const unavailable = row("unavailable", true, 1);
    unavailable.url = "";
    const providers = orderedManageModelsProviders({
      artifacts: ["symbol", "footprint", "model"], statuses: [], tools: [], completeProviders: [],
      rows: [unavailable],
    });

    expect(providers[0]?.complete).toBe(true);
    expect(providers[0]?.reachable).toBe(false);
    expect(bestCompleteProvider(providers)).toBeNull();
  });
});
