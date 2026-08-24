import { describe, expect, it } from "vitest";
import { committedDevModeDraft } from "../lib/devModeDraft";
import { parseDesignDocument, type DesignDocument } from "./document";
import { serializeDesignHandoff } from "./designHandoff";

describe("Design Studio handoff export", () => {
  it("serializes the complete current document with revision context for a future ChatGPT session", () => {
    const document: DesignDocument = {
      schemaVersion: 2,
      base: committedDevModeDraft(),
      variations: {},
      activeVariationId: "",
      globalTargets: {},
      orphanedEdits: {},
      cadPresentation: {},
    };

    const json = serializeDesignHandoff({
      document,
      theme: "dark",
      activeScenarioId: null,
      appliedRevision: "revision-123",
      exportedAt: "2026-08-23T12:00:00.000Z",
    });
    const handoff = JSON.parse(json) as Record<string, unknown>;

    expect(handoff).toMatchObject({
      schema: "stockroom-design-handoff/1",
      exportedAt: "2026-08-23T12:00:00.000Z",
      theme: "dark",
      appliedRevision: "revision-123",
      instructions: expect.stringContaining("ChatGPT"),
    });
    expect(parseDesignDocument(handoff.document).ok).toBe(true);
  });
});
