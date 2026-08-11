import {
  PreviewMutationError,
  classifyPreviewRequest,
  guardPreviewRequest,
} from "./mutationGuard";

describe("preview mutation guard", () => {
  it("blocks unmatched product mutations but permits studio persistence", () => {
    expect(
      classifyPreviewRequest({ method: "POST", path: "/api/parts", params: {}, body: {} }),
    ).toBe("block");
    expect(
      classifyPreviewRequest({
        method: "PUT",
        path: "/api/design-studio/personal",
        params: {},
        body: {},
      }),
    ).toBe("studio-live");
  });

  it("allows only read-only dev status from the source-owned dev API", () => {
    expect(
      classifyPreviewRequest({
        method: "GET",
        path: "/api/dev/status",
        params: {},
        body: undefined,
      }),
    ).toBe("studio-live");
    expect(
      classifyPreviewRequest({ method: "POST", path: "/api/dev/save", params: {}, body: {} }),
    ).toBe("block");
    expect(
      classifyPreviewRequest({ method: "POST", path: "/api/dev/publish", params: {}, body: {} }),
    ).toBe("block");
  });

  it("throws an actionable typed error for every unmatched product write", () => {
    const descriptor = {
      method: "DELETE",
      path: "/api/library/parts/lm358",
      params: {},
      body: undefined,
    };

    expect(() => guardPreviewRequest(descriptor)).toThrowError(PreviewMutationError);
    expect(() => guardPreviewRequest(descriptor)).toThrow(
      "Exit fixture preview and return to Real Data",
    );
  });

  it("treats product reads as fixture-only instead of live requests", () => {
    expect(
      classifyPreviewRequest({
        method: "GET",
        path: "/api/library/parts",
        params: {},
        body: undefined,
      }),
    ).toBe("fixture-only");
  });
});
