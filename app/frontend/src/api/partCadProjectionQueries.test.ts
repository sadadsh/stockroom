import { QueryClient } from "@tanstack/react-query";
import { invalidatePartCadProjection } from "./partCadProjectionQueries";

describe("part CAD projection invalidation", () => {
  it("invalidates the exact part, the parts list, and catalog-build status after attachment", async () => {
    const queryClient = new QueryClient();
    const keys = [
      ["part-workspace", "part-1"],
      ["part-workspace", "part-2"],
      ["parts", {}],
      ["catalog-build-status"],
    ] as const;
    keys.forEach((key) => queryClient.setQueryData(key, { current: true }));

    await invalidatePartCadProjection(queryClient, "part-1");

    expect(queryClient.getQueryState(["part-workspace", "part-1"])?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(["part-workspace", "part-2"])?.isInvalidated).toBe(false);
    expect(queryClient.getQueryState(["parts", {}])?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(["catalog-build-status"])?.isInvalidated).toBe(true);
  });
});
