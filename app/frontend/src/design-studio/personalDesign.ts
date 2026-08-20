import { ApiError, api } from "../api/client";
import {
  parseDesignDocument,
  type DesignDocument,
} from "./document";

export type PersonalDesignState =
  | "loading"
  | "ready"
  | "saving"
  | "conflict"
  | "invalid"
  | "error";

export interface PersonalDesignSnapshot {
  document: DesignDocument;
  lastValidDocument: DesignDocument;
  personalState: PersonalDesignState;
  revision: string | null;
}

export interface PersonalDesignFlushResult {
  persisted: boolean;
  state: PersonalDesignState;
}

export interface PersonalDesignController {
  getSnapshot: () => PersonalDesignSnapshot;
  subscribe: (listener: () => void) => () => void;
  activate: () => void;
  hydrate: () => Promise<void>;
  replaceDocument: (document: unknown) => boolean;
  flush: () => Promise<PersonalDesignFlushResult>;
  flushForPageExit: () => void;
  dispose: () => void;
}

const AUTOSAVE_DELAY_MS = 400;
const PAGE_EXIT_DOCUMENT_BUDGET_BYTES = 28 * 1024;

function pageExitSafe(document: DesignDocument | null): boolean {
  return document === null || new TextEncoder().encode(JSON.stringify(document)).byteLength <= PAGE_EXIT_DOCUMENT_BUDGET_BYTES;
}

function validDocument(value: unknown): DesignDocument | null {
  const parsed = parseDesignDocument(value);
  return parsed.ok ? parsed.document : null;
}

/**
 * Owns the personal-document network lifecycle independently of React rendering.
 * A controller serializes writes and never promotes unparsed server data into its snapshot.
 */
export function createPersonalDesignController(
  initialDocument: DesignDocument,
): PersonalDesignController {
  const parsedInitial = validDocument(initialDocument);
  if (!parsedInitial) throw new Error("Initial personal design document must be valid.");

  let snapshot: PersonalDesignSnapshot = {
    document: parsedInitial,
    lastValidDocument: parsedInitial,
    personalState: "loading",
    revision: null,
  };
  let disposed = false;
  let blockedByConflict = false;
  let debounceTimer: ReturnType<typeof setTimeout> | null = null;
  let pendingDocument: DesignDocument | null = null;
  let pendingGeneration = 0;
  let acknowledgedGeneration = 0;
  let pendingReady = false;
  let inFlight: Promise<void> | null = null;
  let inFlightDocument: DesignDocument | null = null;
  let inFlightGeneration: number | null = null;
  let hydration: Promise<void> | null = null;
  let hydrationSettled = false;
  let flushRequested = false;
  const listeners = new Set<() => void>();

  const publish = (next: PersonalDesignSnapshot) => {
    snapshot = next;
    if (!disposed) listeners.forEach((listener) => listener());
  };

  const savePending = (forPageExit = false): Promise<void> => {
    if (inFlight) return inFlight;
    if (!pendingDocument || blockedByConflict) return Promise.resolve();

    const savingDocument = pendingDocument;
    const savingGeneration = pendingGeneration;
    inFlightDocument = savingDocument;
    inFlightGeneration = savingGeneration;
    pendingReady = false;
    publish({ ...snapshot, personalState: "saving" });

    const request = (forPageExit ? api.designStudioPutForPageExit : api.designStudioPut)({
      document: savingDocument,
      expected_revision: snapshot.revision,
    });
    inFlight = request
      .then((response) => {
        if (savingGeneration <= acknowledgedGeneration) return;
        const savedDocument = validDocument(response.document);
        if (!savedDocument) {
          pendingReady = false;
          publish({ ...snapshot, personalState: "invalid" });
          return;
        }
        acknowledgedGeneration = savingGeneration;
        if (pendingGeneration === savingGeneration) pendingDocument = null;
        publish({
          ...snapshot,
          document: pendingDocument ?? savedDocument,
          lastValidDocument: savedDocument,
          personalState: pendingDocument ? "saving" : "ready",
          revision: response.revision,
        });
      })
      .catch((error: unknown) => {
        if (savingGeneration <= acknowledgedGeneration) return;
        if (error instanceof ApiError && error.status === 409) {
          blockedByConflict = true;
          publish({ ...snapshot, personalState: "conflict" });
          return;
        }
        publish({ ...snapshot, personalState: "error" });
      })
      .finally(() => {
        inFlight = null;
        inFlightDocument = null;
        inFlightGeneration = null;
        if (
          pendingDocument
          && pendingReady
          && pendingGeneration !== savingGeneration
          && !blockedByConflict
        ) void savePending();
      });
    return inFlight;
  };

  const scheduleSave = () => {
    if (debounceTimer) clearTimeout(debounceTimer);
    pendingReady = false;
    debounceTimer = setTimeout(() => {
      debounceTimer = null;
      pendingReady = true;
      void savePending();
    }, AUTOSAVE_DELAY_MS);
  };

  const waitForInFlight = (): Promise<void> => {
    const activeRequest = inFlight;
    return activeRequest ? activeRequest.then(waitForInFlight) : Promise.resolve();
  };

  const releasePendingAfterHydration = () => {
    if (!pendingDocument) return;
    if (flushRequested) {
      pendingReady = true;
      void savePending();
    } else {
      scheduleSave();
    }
  };

  const controller: PersonalDesignController = {
    getSnapshot: () => snapshot,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    activate: () => {
      disposed = false;
      flushRequested = false;
    },
    hydrate: () => {
      if (hydration) return hydration;
      hydration = api
        .designStudioGet()
        .then((response) => {
          hydrationSettled = true;
          if (response.document === null) {
            publish({
              ...snapshot,
              document: pendingDocument ?? snapshot.document,
              personalState: "ready",
              revision: response.revision,
            });
            releasePendingAfterHydration();
            return;
          }
          const hydrated = validDocument(response.document);
          if (!hydrated) {
            publish({
              ...snapshot,
              document: pendingDocument ?? snapshot.document,
              personalState: "invalid",
              revision: response.revision,
            });
            return;
          }
          publish({
            document: pendingDocument ?? hydrated,
            lastValidDocument: hydrated,
            personalState: "ready",
            revision: response.revision,
          });
          releasePendingAfterHydration();
        })
        .catch(() => {
          hydrationSettled = true;
          publish({ ...snapshot, personalState: "error" });
        });
      return hydration;
    },
    replaceDocument: (value) => {
      const document = validDocument(value);
      if (!document) {
        if (debounceTimer) clearTimeout(debounceTimer);
        debounceTimer = null;
        pendingDocument = null;
        pendingReady = false;
        publish({ ...snapshot, personalState: "invalid" });
        return false;
      }
      pendingDocument = document;
      pendingGeneration += 1;
      publish({
        ...snapshot,
        document,
        personalState: !hydrationSettled
          ? "loading"
          : blockedByConflict
            ? "conflict"
            : inFlight
              ? "saving"
              : "ready",
      });
      if (hydrationSettled && !blockedByConflict) {
        if (pageExitSafe(document)) scheduleSave();
        else {
          pendingReady = true;
          void savePending();
        }
      }
      return true;
    },
    flush: async () => {
      flushRequested = true;
      if (!hydrationSettled) await controller.hydrate();
      if (debounceTimer) clearTimeout(debounceTimer);
      debounceTimer = null;
      pendingReady = true;
      await savePending();
      await waitForInFlight();
      return {
        persisted: pendingDocument === null && inFlight === null,
        state: snapshot.personalState,
      };
    },
    flushForPageExit: () => {
      flushRequested = true;
      if (!hydrationSettled) return;
      if (debounceTimer) clearTimeout(debounceTimer);
      debounceTimer = null;
      const closingDocument = pendingDocument ?? inFlightDocument;
      const closingGeneration = pendingDocument ? pendingGeneration : inFlightGeneration;
      if (!closingDocument || closingGeneration === null) return;
      if (!pageExitSafe(closingDocument) || !pageExitSafe(inFlightDocument)) {
        pendingReady = true;
        void savePending();
        return;
      }
      void api.designStudioPutForPageExit({
        document: closingDocument,
        expected_revision: snapshot.revision,
        superseded_document: inFlightDocument,
      }).then((response) => {
        if (closingGeneration <= acknowledgedGeneration) return;
        const savedDocument = validDocument(response.document);
        if (!savedDocument) {
          publish({ ...snapshot, personalState: "invalid" });
          return;
        }
        acknowledgedGeneration = closingGeneration;
        if (pendingGeneration === closingGeneration) pendingDocument = null;
        publish({
          ...snapshot,
          document: pendingDocument ?? savedDocument,
          lastValidDocument: savedDocument,
          personalState: pendingDocument ? "saving" : "ready",
          revision: response.revision,
        });
      }).catch((error: unknown) => {
        if (closingGeneration <= acknowledgedGeneration) return;
        if (error instanceof ApiError && error.status === 409) {
          blockedByConflict = true;
          publish({ ...snapshot, personalState: "conflict" });
          return;
        }
        publish({ ...snapshot, personalState: "error" });
      });
    },
    dispose: () => {
      flushRequested = true;
      if (debounceTimer) clearTimeout(debounceTimer);
      debounceTimer = null;
      pendingReady = true;
      if (hydrationSettled) void savePending();
      disposed = true;
      listeners.clear();
    },
  };

  return controller;
}
