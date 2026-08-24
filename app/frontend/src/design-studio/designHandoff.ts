import type { Theme } from "../lib/theme";
import { downloadBlob } from "../lib/download";
import type { DesignDocument } from "./document";

export interface DesignHandoffInput {
  document: DesignDocument;
  theme: Theme;
  activeScenarioId: string | null;
  appliedRevision: string | null;
  exportedAt?: string;
}

export function serializeDesignHandoff(input: DesignHandoffInput): string {
  return JSON.stringify({
    schema: "stockroom-design-handoff/1",
    exportedAt: input.exportedAt ?? new Date().toISOString(),
    theme: input.theme,
    activeScenarioId: input.activeScenarioId,
    appliedRevision: input.appliedRevision,
    instructions: "Give this file to ChatGPT with the Stockroom repository and describe the revision. Preserve the complete document and schema when returning changes.",
    document: input.document,
  }, null, 2);
}

export function downloadDesignHandoff(input: DesignHandoffInput): void {
  const exportedAt = input.exportedAt ?? new Date().toISOString();
  downloadBlob(
    `stockroom-design-${exportedAt.slice(0, 10)}.json`,
    new Blob([serializeDesignHandoff({ ...input, exportedAt })], { type: "application/json" }),
  );
}
