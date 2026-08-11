import { act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "../api/client";
import type { DesignDocument } from "./document";
import { createPersonalDesignController } from "./personalDesign";

vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      designStudioGet: vi.fn(),
      designStudioPut: vi.fn(),
      designStudioDelete: vi.fn(),
    },
  };
});

const mockApi = vi.mocked(api);

function fixtureDocument(copy: Record<string, string> = {}): DesignDocument {
  return {
    schemaVersion: 1,
    base: {
      tokens: { root: {}, light: {} },
      copy,
      icons: {},
      elements: {},
      behaviors: {},
      layout: null,
    },
    variations: {},
    activeVariationId: "",
    targetScopes: {},
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

async function settle() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("personal design persistence", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockApi.designStudioGet.mockReset();
    mockApi.designStudioPut.mockReset();
    mockApi.designStudioDelete.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("hydrates only a valid complete document", async () => {
    const initial = fixtureDocument({ "rail.components": "Components" });
    const personal = fixtureDocument({ "rail.components": "My Components" });
    mockApi.designStudioGet.mockResolvedValue({ revision: "r1", document: personal });
    const controller = createPersonalDesignController(initial);
    expect(controller.getSnapshot().personalState).toBe("loading");

    await controller.hydrate();

    expect(controller.getSnapshot()).toMatchObject({
      document: personal,
      lastValidDocument: personal,
      personalState: "ready",
      revision: "r1",
    });
  });

  it("keeps the last valid fallback when hydration returns a malformed document", async () => {
    const initial = fixtureDocument({ "rail.components": "Components" });
    mockApi.designStudioGet.mockResolvedValue({
      revision: "bad-revision",
      document: { schemaVersion: 99, base: {} },
    });
    const controller = createPersonalDesignController(initial);

    await controller.hydrate();

    expect(controller.getSnapshot()).toMatchObject({
      document: initial,
      lastValidDocument: initial,
      personalState: "invalid",
      revision: "bad-revision",
    });
    expect(mockApi.designStudioPut).not.toHaveBeenCalled();
  });

  it("reports an ordinary save failure without replacing the last valid document", async () => {
    const initial = fixtureDocument({ "rail.about": "About" });
    const edited = fixtureDocument({ "rail.about": "Information" });
    mockApi.designStudioGet.mockResolvedValue({ revision: "r1", document: initial });
    mockApi.designStudioPut.mockRejectedValue(new ApiError(503, "unavailable"));
    const controller = createPersonalDesignController(initial);
    await controller.hydrate();

    controller.replaceDocument(edited);
    await vi.advanceTimersByTimeAsync(400);
    await settle();

    expect(controller.getSnapshot()).toMatchObject({
      document: edited,
      lastValidDocument: initial,
      personalState: "error",
      revision: "r1",
    });
  });

  it("debounces a valid replacement for 400 ms and saves with the hydrated revision", async () => {
    const initial = fixtureDocument();
    const edited = fixtureDocument({ "rail.about": "Information" });
    mockApi.designStudioGet.mockResolvedValue({ revision: "r1", document: initial });
    mockApi.designStudioPut.mockResolvedValue({ revision: "r2", document: edited });
    const controller = createPersonalDesignController(initial);
    await controller.hydrate();

    controller.replaceDocument(edited);
    await vi.advanceTimersByTimeAsync(399);
    expect(mockApi.designStudioPut).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(1);
    expect(mockApi.designStudioPut).toHaveBeenCalledWith({
      document: edited,
      expected_revision: "r1",
    });
    await settle();
    expect(controller.getSnapshot()).toMatchObject({
      personalState: "ready",
      revision: "r2",
      lastValidDocument: edited,
    });
  });

  it("keeps one request in flight and coalesces queued edits to the latest document", async () => {
    const initial = fixtureDocument();
    const first = fixtureDocument({ "rail.about": "First" });
    const superseded = fixtureDocument({ "rail.about": "Second" });
    const latest = fixtureDocument({ "rail.about": "Latest" });
    const firstSave = deferred<{ revision: string; document: DesignDocument }>();
    mockApi.designStudioGet.mockResolvedValue({ revision: "r1", document: initial });
    mockApi.designStudioPut
      .mockImplementationOnce(() => firstSave.promise)
      .mockResolvedValueOnce({ revision: "r3", document: latest });
    const controller = createPersonalDesignController(initial);
    await controller.hydrate();

    controller.replaceDocument(first);
    await vi.advanceTimersByTimeAsync(400);
    expect(mockApi.designStudioPut).toHaveBeenCalledTimes(1);
    controller.replaceDocument(superseded);
    controller.replaceDocument(latest);
    await vi.advanceTimersByTimeAsync(400);
    expect(mockApi.designStudioPut).toHaveBeenCalledTimes(1);

    firstSave.resolve({ revision: "r2", document: first });
    await settle();

    expect(mockApi.designStudioPut).toHaveBeenCalledTimes(2);
    expect(mockApi.designStudioPut).toHaveBeenLastCalledWith({
      document: latest,
      expected_revision: "r2",
    });
  });

  it("does not bypass the debounce when an in-flight save finishes after a newer edit", async () => {
    const initial = fixtureDocument();
    const first = fixtureDocument({ "rail.about": "First" });
    const latest = fixtureDocument({ "rail.about": "Latest" });
    const firstSave = deferred<{ revision: string; document: DesignDocument }>();
    mockApi.designStudioGet.mockResolvedValue({ revision: "r1", document: initial });
    mockApi.designStudioPut
      .mockImplementationOnce(() => firstSave.promise)
      .mockResolvedValueOnce({ revision: "r3", document: latest });
    const controller = createPersonalDesignController(initial);
    await controller.hydrate();

    controller.replaceDocument(first);
    await vi.advanceTimersByTimeAsync(400);
    controller.replaceDocument(latest);
    expect(controller.getSnapshot().personalState).toBe("saving");
    await vi.advanceTimersByTimeAsync(10);
    firstSave.resolve({ revision: "r2", document: first });
    await settle();
    expect(mockApi.designStudioPut).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(389);
    expect(mockApi.designStudioPut).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(mockApi.designStudioPut).toHaveBeenCalledTimes(2);
    expect(mockApi.designStudioPut).toHaveBeenLastCalledWith({
      document: latest,
      expected_revision: "r2",
    });
  });

  it("retains the last valid autosave and enters conflict state after a 409", async () => {
    const initial = fixtureDocument({ "rail.about": "About" });
    const edited = fixtureDocument({ "rail.about": "Information" });
    mockApi.designStudioGet.mockResolvedValue({ revision: "r1", document: initial });
    mockApi.designStudioPut.mockRejectedValue(new ApiError(409, "revision conflict"));
    const controller = createPersonalDesignController(initial);
    await controller.hydrate();

    controller.replaceDocument(edited);
    await vi.advanceTimersByTimeAsync(400);
    await settle();

    expect(controller.getSnapshot()).toMatchObject({
      document: edited,
      lastValidDocument: initial,
      personalState: "conflict",
      revision: "r1",
    });
  });

  it("flushes a pending valid replacement when disposed before the debounce expires", async () => {
    const initial = fixtureDocument();
    const edited = fixtureDocument({ "rail.about": "Information" });
    mockApi.designStudioGet.mockResolvedValue({ revision: "r1", document: initial });
    mockApi.designStudioPut.mockResolvedValue({ revision: "r2", document: edited });
    const controller = createPersonalDesignController(initial);
    await controller.hydrate();

    controller.replaceDocument(edited);
    controller.dispose();

    expect(mockApi.designStudioPut).toHaveBeenCalledWith({
      document: edited,
      expected_revision: "r1",
    });
  });
});
