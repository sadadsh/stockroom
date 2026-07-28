/**
 * Global guided-capture store. Capture used to live inside the Complete-Part modal, so
 * closing the modal dropped it. This provider lifts the ONE active capture out of the modal:
 * both the modal (scoped to its part) and the persistent CaptureStatusPill (global) read it,
 * so a capture keeps running while the user works elsewhere and a "Keep Working" hand-off is
 * possible. One capture is active at a time; starting a new one replaces the prior (mirrors the
 * host's single-session model and never opens two vendor windows).
 *
 * The watchdog (B1), the session-token gate (B4), and the both-format attach machinery are the
 * same as the old useGuidedCapture, moved here verbatim in behavior; `useGuidedCapture` is now a
 * thin adapter (useGuidedCapture.ts) that projects this store scoped to a partId.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import type {
  CadSourceResponse,
  CompletionResult,
  Requirement,
  StagingCandidate,
} from "../api/types";
import { streamEvents } from "./sse";

export type { Requirement };

export type GuidedStatus =
  | "idle"
  | "resolving"
  | "window-open"
  | "receiving"
  | "attaching"
  | "done"
  | "timed-out"
  | "unavailable"
  | "error";

export interface CaptureForward {
  path?: string;
  token?: string;
  requirements?: Requirement[];
  altiumPaths?: string[];
  signal?: "timeout" | "done";
}

export const KICAD_REQS: Requirement[] = ["kicad_symbol", "kicad_footprint", "kicad_model"];
export const ALTIUM_REQS: Requirement[] = ["altium_symbol", "altium_footprint"];

// Human labels for the honest not-all-attached message (the 3D model is tool-neutral:
// never "KiCad 3D Model").
export const REQ_LABELS: Record<Requirement, string> = {
  kicad_symbol: "KiCad Symbol",
  kicad_footprint: "KiCad Footprint",
  kicad_model: "3D Model",
  altium_symbol: "Altium Symbol",
  altium_footprint: "Altium Footprint",
};
const WATCHDOG_MS = 180_000;

type Received = Partial<Record<Requirement, boolean>>;

export interface CaptureState {
  partId: string | null;
  partName: string | null;
  status: GuidedStatus;
  message: string | null;
  url: string | null;
  vendor: string | null;
  needs: Requirement[];
  received: Received;
  backgrounded: boolean;
}

const IDLE: CaptureState = {
  partId: null,
  partName: null,
  status: "idle",
  message: null,
  url: null,
  vendor: null,
  needs: [],
  received: {},
  backgrounded: false,
};

function errMsg(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

export function subsetComplete(needs: Requirement[], received: Received, subset: Requirement[]): boolean {
  return needs.filter((n) => subset.includes(n)).every((n) => received[n]);
}

// `hostOpenCadDownload` lived here: it read `window.pywebview.api.open_cad_download`, which exists
// ONLY on Windows. Off Windows the whole guided flow degraded to "pick the files yourself", so
// nothing below the URL layer was verifiable and every claim about capture was made from an
// adjacent layer. Capture now goes through `api.runCapture` - one route, one engine, identical on
// both platforms - so this is DELETED rather than kept as a fallback that would drift.

export interface CaptureApi {
  active: CaptureState;
  // `sourceKey` picks WHICH vendor page to open ("ultralibrarian", "samacsys", ...). Omitted
  // means the first source the backend returns, which is its trust order's head.
  start: (partId: string, partName: string, needs: Requirement[], sourceKey?: string) => Promise<void>;
  submitPaths: (partId: string, partName: string, needs: Requirement[], paths: string[]) => Promise<void>;
  reset: () => void;
  keepWorking: () => void;
  // The pill asks to reopen its part's modal; the Components surface honors the intent.
  reopenPartId: string | null;
  requestReopen: () => void;
  // Route to ANY part's Complete Part window (the Add flow's "added, now get its
  // files" continuation): Components selects the part and the detail opens the window.
  requestOpenFor: (partId: string) => void;
  clearReopen: () => void;
}

const CaptureContext = createContext<CaptureApi | null>(null);

export function CaptureProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<CaptureState>(IDLE);
  const [reopenPartId, setReopenPartId] = useState<string | null>(null);
  const qc = useQueryClient();
  const partIdRef = useRef<string | null>(null);
  const tokenRef = useRef<string | null>(null);
  const needsRef = useRef<Requirement[]>([]);
  const receivedRef = useRef<Received>({});
  const watchdogRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handlerRef = useRef<((payload: CaptureForward | string) => void) | null>(null);

  const invalidate = useCallback(() => {
    const pid = partIdRef.current;
    qc.invalidateQueries({ queryKey: ["parts"] });
    qc.invalidateQueries({ queryKey: ["facets"] });
    qc.invalidateQueries({ queryKey: ["duplicates"] });
    if (pid) {
      qc.invalidateQueries({ queryKey: ["part", pid] });
      qc.invalidateQueries({ queryKey: ["part-history", pid] });
      qc.invalidateQueries({ queryKey: ["cad-source", pid] });
    }
  }, [qc]);

  const clearWatchdog = useCallback(() => {
    if (watchdogRef.current) {
      clearTimeout(watchdogRef.current);
      watchdogRef.current = null;
    }
  }, []);

  const clearHandler = useCallback(() => {
    if (handlerRef.current && window.__STOCKROOM_CAD_DOWNLOAD__ === handlerRef.current) {
      delete window.__STOCKROOM_CAD_DOWNLOAD__;
    }
    handlerRef.current = null;
  }, []);

  useEffect(
    () => () => {
      clearWatchdog();
      clearHandler();
    },
    [clearWatchdog, clearHandler],
  );

  const attachKicad = useCallback(async (paths: string[]) => {
    const pid = partIdRef.current;
    if (!pid) throw new Error("No active part for the capture.");
    const { job_id: jobId } = await api.assetsInspect(pid, paths);
    const body = await api.openJobStream(jobId);
    let candidates: StagingCandidate[] | null = null;
    let streamError: string | null = null;
    for await (const ev of streamEvents(body)) {
      if (ev.event === "result") {
        candidates = (ev.data as { result: StagingCandidate[] }).result;
      } else if (ev.event === "error") {
        streamError = (ev.data as { detail?: string }).detail ?? "The inspect failed.";
      } else if (ev.event === "done") {
        break;
      }
    }
    if (streamError) throw new Error(streamError);
    if (!candidates || candidates.length === 0) {
      throw new Error("No usable KiCad symbol, footprint, or 3D model found in the download.");
    }
    // The vendor + page this capture actually opened, so the attached files record where they
    // came from. Read from a ref rather than from `state`, because this callback is created once
    // and would otherwise close over the state as it was at mount.
    const src = originRef.current;
    await api.assetsCommit(pid, candidates[0], src ?? undefined);
  }, []);

  const attachAltium = useCallback(async (paths: string[]) => {
    const pid = partIdRef.current;
    if (!pid) throw new Error("No active part for the capture.");
    if (paths.length === 0) throw new Error("No Altium library files were captured.");
    await api.altiumAttach(pid, paths);
    // The library must be placeable from Altium without a separate visit to the Altium
    // window: refresh the DbLib data source right after the attach. Best-effort - a
    // regenerate hiccup must not fail a capture whose files are already attached (the
    // Altium window still offers a manual regenerate).
    try {
      await api.altiumRegenerate();
    } catch {
      // Attached fine; the DbLib refresh can be re-run from the Altium window.
    }
  }, []);

  const markReceived = useCallback((reqs: Requirement[]) => {
    const next = { ...receivedRef.current };
    reqs.forEach((r) => {
      if (needsRef.current.includes(r)) next[r] = true;
    });
    receivedRef.current = next;
    setState((s) => ({ ...s, received: next }));
  }, []);

  const allReceived = useCallback(() => needsRef.current.every((n) => receivedRef.current[n]), []);

  const armCapture = useCallback(
    (onCapture: (payload: CaptureForward | string) => void) => {
      clearHandler();
      handlerRef.current = onCapture;
      window.__STOCKROOM_CAD_DOWNLOAD__ = onCapture;
      clearWatchdog();
      watchdogRef.current = setTimeout(() => {
        setState((s) =>
          s.status === "done"
            ? s
            : {
                ...s,
                status: "timed-out",
                message:
                  "Nothing was received yet. Retry, browse for the file, or follow the guidance.",
              },
        );
      }, WATCHDOG_MS);
    },
    [clearHandler, clearWatchdog],
  );

  const onCapture = useCallback(
    async (payload: CaptureForward | string) => {
      const p: CaptureForward = typeof payload === "string" ? { path: payload } : payload;
      if (p.signal === "timeout") {
        clearWatchdog();
        clearHandler();
        setState((s) => ({
          ...s,
          status: "timed-out",
          message:
            "Nothing was received yet. Retry, browse for the file, or follow the guidance.",
        }));
        return;
      }
      if (tokenRef.current && p.token && p.token !== tokenRef.current) return; // B4 guard
      if (p.signal === "done") {
        // The host finished the capture and closed the vendor window. "Done" from the
        // host means DOWNLOADED - it may only become "attached" here when every need
        // actually attached (live 2026-07-24: the altium set downloaded, never attached,
        // and the old unconditional done buried it). Anything still missing lands as an
        // honest, actionable state instead; the handler stays armed so a late forward
        // or Browse For Files can still complete it. Placed AFTER the B4 guard so a
        // stale done cannot mark a replaced part complete; idempotent when already done.
        clearWatchdog();
        if (allReceived()) {
          clearHandler();
          setState((s) =>
            s.status === "done"
              ? s
              : { ...s, status: "done", message: "All files received and attached." },
          );
        } else {
          const missing = needsRef.current
            .filter((r) => !receivedRef.current[r])
            .map((r) => REQ_LABELS[r] ?? r);
          setState((s) =>
            s.status === "done"
              ? s
              : {
                  ...s,
                  status: "receiving",
                  message: `The vendor window finished, but not everything attached yet: ${missing.join(", ")}. Browse for the files or retry.`,
                },
          );
        }
        return;
      }
      // Scope this forward to the part that was active when it arrived: if the user replaces the
      // capture (starts another part) while this one's attach is in flight, bail rather than mark
      // the new part's checklist. (The attach itself is already safe - attachKicad/attachAltium
      // capture the part id at call time - so this only guards the received-map UI.)
      const pid = partIdRef.current;
      clearWatchdog();
      setState((s) => ({ ...s, status: "attaching", message: "Attaching the files to the part..." }));
      const reqs = p.requirements ?? [];
      const kicadReqs = reqs.filter((r) => KICAD_REQS.includes(r));
      const altiumReqs = reqs.filter((r) => ALTIUM_REQS.includes(r));
      const wantKicad = kicadReqs.length > 0 || (reqs.length === 0 && !!p.path);
      try {
        if (wantKicad && p.path) {
          await attachKicad([p.path]);
          if (partIdRef.current !== pid) return;
          markReceived(kicadReqs.length ? kicadReqs : KICAD_REQS);
        }
        if (altiumReqs.length > 0) {
          await attachAltium(p.altiumPaths ?? (p.path ? [p.path] : []));
          if (partIdRef.current !== pid) return;
          markReceived(altiumReqs);
        }
        if (partIdRef.current !== pid) return;
        invalidate();
        if (allReceived()) {
          clearHandler();
          setState((s) => ({ ...s, status: "done", message: "All files received and attached." }));
        } else {
          armCapture(onCaptureRef.current!);
          setState((s) => ({
            ...s,
            status: "receiving",
            message: "Received. Waiting for the remaining files...",
          }));
        }
      } catch (err) {
        if (partIdRef.current !== pid) return; // replaced mid-attach; leave the new capture alone
        clearHandler();
        setState((s) => ({
          ...s,
          status: "error",
          message: err instanceof ApiError ? err.message : errMsg(err, "Attach failed."),
        }));
      }
    },
    [attachKicad, attachAltium, markReceived, allReceived, invalidate, clearWatchdog, clearHandler, armCapture],
  );

  // WHERE the active capture is downloading from, for provenance on whatever it attaches.
  const originRef = useRef<{ vendor: string; url: string } | null>(null);

  const onCaptureRef = useRef(onCapture);
  useEffect(() => {
    onCaptureRef.current = onCapture;
  }, [onCapture]);

  const start = useCallback(
    async (partId: string, partName: string, needs: Requirement[], sourceKey?: string) => {
      clearWatchdog();
      clearHandler();
      partIdRef.current = partId;
      needsRef.current = needs;
      tokenRef.current = null;
      receivedRef.current = {};
      setState({
        ...IDLE,
        partId,
        partName,
        needs,
        status: "resolving",
        message: "Looking up the download page...",
      });
      let source: CadSourceResponse;
      try {
        source = await api.partCadSource(partId);
      } catch (err) {
        setState((s) => ({ ...s, status: "error", message: errMsg(err, "Could not resolve a CAD source.") }));
        return;
      }
      // The CHOSEN vendor, or the head of the backend's trust order. A key that resolves to
      // nothing falls back to the head rather than opening nowhere -- the list the caller picked
      // from came from this same endpoint, so a miss means the part changed under them.
      const picked =
        (sourceKey ? source.sources.find((v) => v.key === sourceKey) : undefined) ??
        source.sources[0];
      if (!picked?.url) {
        setState((s) => ({ ...s, status: "unavailable", message: "No CAD source page for this part." }));
        return;
      }
      originRef.current = { vendor: picked.key, url: picked.url };
      setState((s) => ({ ...s, url: picked.url, vendor: picked.label, received: {} }));
      // THE capture path, identical on Windows and Linux. The backend opens a real browser, drives
      // the vendor page, catches the download, classifies it and attaches it with provenance - one
      // job, and testable off Windows.
      //
      // This replaced `window.pywebview.api.open_cad_download`, which existed ONLY on Windows: off
      // it the flow silently degraded to "pick the files yourself", so nothing below the URL layer
      // could be verified and every claim about capture came from an adjacent layer.
      try {
        const { job_id } = await api.runCapture({ partIds: [partId], vendor: picked.key });
        setState((s) => ({
          ...s,
          status: "receiving",
          message: "Working through the vendor page. Sign in there if it asks; it is remembered.",
        }));
        const body = await api.openJobStream(job_id);
        let failure: string | null = null;
        let result: CompletionResult | null = null;
        for await (const ev of streamEvents(body)) {
          if (ev.event === "progress") {
            const message = (ev.data as { message?: string }).message;
            if (message) setState((s) => (s.status === "done" ? s : { ...s, message }));
          } else if (ev.event === "error") {
            failure = (ev.data as { detail?: string }).detail ?? "The capture failed.";
          } else if (ev.event === "result") {
            result = (ev.data as { result?: CompletionResult }).result ?? null;
          } else if (ev.event === "done") {
            break;
          }
        }
        if (failure) throw new Error(failure);
        if (partIdRef.current !== partId) return;
        if (!result) {
          throw new Error("The capture ended without a verified completion report.");
        }
        const item = result.items.find((candidate) => candidate.part_id === partId);
        if (!item) {
          throw new Error("The capture report did not contain the requested part.");
        }
        const complete =
          (item.status === "completed" || item.status === "already-complete") &&
          item.remaining.length === 0;
        if (complete) {
          markReceived(needs);
        } else {
          markReceived(
            item.satisfied.filter((value): value is Requirement =>
              needs.includes(value as Requirement),
            ),
          );
        }
        // Re-read server state after the result has proved what happened. The report decides
        // success; a terminal SSE `done` frame only says the worker stopped emitting events.
        invalidate();
        setState((s) => ({
          ...s,
          status: complete ? "done" : "error",
          message: complete
            ? "All network files were verified and attached."
            : item.error ||
              `Capture finished incomplete. Still missing: ${item.remaining
                .map((requirement) => REQ_LABELS[requirement as Requirement] ?? requirement)
                .join(", ") || "required CAD files"}.`,
        }));
      } catch (err) {
        if (partIdRef.current !== partId) return;
        setState((s) => ({
          ...s,
          status: "error",
          message: err instanceof ApiError ? err.message : errMsg(err, "Capture failed."),
        }));
      }
    },
    [clearWatchdog, clearHandler, invalidate, markReceived],
  );

  const submitPaths = useCallback(
    async (partId: string, partName: string, needs: Requirement[], paths: string[]) => {
      if (paths.length === 0) return;
      // The manual "Browse For Files" path can run without a prior start(): make sure the
      // active capture is this part (with its needs) so the KiCad rows mark correctly and the
      // remaining rows keep receiving.
      if (partIdRef.current !== partId) {
        clearWatchdog();
        clearHandler();
        partIdRef.current = partId;
        tokenRef.current = null;
        receivedRef.current = {};
        needsRef.current = needs;
        setState({ ...IDLE, partId, partName, needs, received: {} });
      } else {
        needsRef.current = needs;
      }
      clearWatchdog();
      setState((s) => ({ ...s, status: "attaching", message: "Attaching the files to the part..." }));
      try {
        await attachKicad(paths);
        if (partIdRef.current !== partId) return; // replaced mid-attach; leave the new capture alone
        markReceived(KICAD_REQS);
        invalidate();
        if (allReceived()) {
          clearHandler();
          setState((s) => ({ ...s, status: "done", message: "All files received and attached." }));
        } else {
          armCapture(onCaptureRef.current);
          setState((s) => ({
            ...s,
            status: "receiving",
            message: "Received. Waiting for the remaining files...",
          }));
        }
      } catch (err) {
        if (partIdRef.current !== partId) return;
        setState((s) => ({
          ...s,
          status: "error",
          message: err instanceof ApiError ? err.message : errMsg(err, "Attach failed."),
        }));
      }
    },
    [attachKicad, markReceived, invalidate, allReceived, clearWatchdog, clearHandler, armCapture],
  );

  const reset = useCallback(() => {
    clearWatchdog();
    clearHandler();
    partIdRef.current = null;
    tokenRef.current = null;
    receivedRef.current = {};
    setState(IDLE);
  }, [clearWatchdog, clearHandler]);

  const keepWorking = useCallback(() => {
    setState((s) => ({ ...s, backgrounded: true }));
  }, []);

  const requestReopen = useCallback(() => {
    setReopenPartId(partIdRef.current);
    setState((s) => ({ ...s, backgrounded: false }));
  }, []);

  const requestOpenFor = useCallback((partId: string) => setReopenPartId(partId), []);

  const clearReopen = useCallback(() => setReopenPartId(null), []);

  return (
    <CaptureContext.Provider
      value={{ active: state, start, submitPaths, reset, keepWorking, reopenPartId, requestReopen, requestOpenFor, clearReopen }}
    >
      {children}
    </CaptureContext.Provider>
  );
}

export function useCapture(): CaptureApi {
  const ctx = useContext(CaptureContext);
  if (!ctx) throw new Error("useCapture must be used within a CaptureProvider");
  return ctx;
}
