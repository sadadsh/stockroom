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

export interface PersonalDesignController {
  getSnapshot: () => PersonalDesignSnapshot;
  subscribe: (listener: () => void) => () => void;
  activate: () => void;
  hydrate: () => Promise<void>;
  replaceDocument: (document: unknown) => boolean;
  flush: () => Promise<void>;
  dispose: () => void;
}

const AUTOSAVE_DELAY_MS = 400;

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
  let pendingReady = false;
  let inFlight: Promise<void> | null = null;
  let hydration: Promise<void> | null = null;
  const listeners = new Set<() => void>();

  const publish = (next: PersonalDesignSnapshot) => {
    snapshot = next;
    if (!disposed) listeners.forEach((listener) => listener());
  };

  const savePending = (): Promise<void> => {
    if (inFlight) return inFlight;
    if (!pendingDocument || blockedByConflict) return Promise.resolve();

    const savingDocument = pendingDocument;
    pendingDocument = null;
    pendingReady = false;
    publish({ ...snapshot, personalState: "saving" });

    const request = api.designStudioPut({
      document: savingDocument,
      expected_revision: snapshot.revision,
    });
    inFlight = request
      .then((response) => {
        const savedDocument = validDocument(response.document);
        if (!savedDocument) {
          publish({ ...snapshot, personalState: "invalid" });
          pendingDocument = null;
          return;
        }
        publish({
          ...snapshot,
          document: pendingDocument ?? savedDocument,
          lastValidDocument: savedDocument,
          personalState: pendingDocument ? "saving" : "ready",
          revision: response.revision,
        });
      })
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 409) {
          blockedByConflict = true;
          publish({ ...snapshot, personalState: "conflict" });
          return;
        }
        publish({ ...snapshot, personalState: "error" });
      })
      .finally(() => {
        inFlight = null;
        if (pendingDocument && pendingReady && !blockedByConflict) void savePending();
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

  const controller: PersonalDesignController = {
    getSnapshot: () => snapshot,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    activate: () => {
      disposed = false;
    },
    hydrate: () => {
      if (hydration) return hydration;
      hydration = api
        .designStudioGet()
        .then((response) => {
          if (response.document === null) {
            publish({ ...snapshot, personalState: "ready", revision: response.revision });
            return;
          }
          const hydrated = validDocument(response.document);
          if (!hydrated) {
            publish({ ...snapshot, personalState: "invalid", revision: response.revision });
            return;
          }
          publish({
            document: hydrated,
            lastValidDocument: hydrated,
            personalState: "ready",
            revision: response.revision,
          });
        })
        .catch(() => {
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
      publish({
        ...snapshot,
        document,
        personalState: blockedByConflict ? "conflict" : inFlight ? "saving" : "ready",
      });
      if (!blockedByConflict) scheduleSave();
      return true;
    },
    flush: async () => {
      if (debounceTimer) clearTimeout(debounceTimer);
      debounceTimer = null;
      pendingReady = true;
      await savePending();
      while (inFlight) await inFlight;
    },
    dispose: () => {
      if (debounceTimer) clearTimeout(debounceTimer);
      debounceTimer = null;
      pendingReady = true;
      void savePending();
      disposed = true;
      listeners.clear();
    },
  };

  return controller;
}
