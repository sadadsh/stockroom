/**
 * Guided capture (rebuild of useCadDownload): resolve a part's Ultra Librarian /
 * SnapEDA page, open it in the host's guided window, and auto-attach BOTH its KiCad
 * and its Altium assets as each file lands, driving a live per-requirement checklist.
 *
 * Fixes the old flow's infinite wait (B1): a watchdog arms whenever we are waiting
 * for a capture and transitions to an honest "timed-out" state if nothing lands, so
 * the button can never hang forever. Guards against wrong-part misattribution (B4):
 * a capture forward carrying a session token is ignored unless it matches this
 * session's token.
 *
 * Whichever host tier wins (WebView2 download-intercept or the widened Downloads
 * watch) forwards through the SAME global, window.__STOCKROOM_CAD_DOWNLOAD__(payload).
 * The payload is either a bare path string (legacy) or a CaptureForward object
 * carrying the session token, the requirements the file satisfies, and any loose
 * Altium paths extracted from a captured zip. submitPaths stays exposed so the manual
 * "Browse For Files" fallback reaches the same KiCad inspect -> commit pipeline.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import type { Requirement, StagingCandidate } from "../api/types";
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

// The host forwards a captured asset (or a timeout signal) as this payload.
export interface CaptureForward {
  path?: string;
  token?: string;
  requirements?: Requirement[];
  // Loose Altium library paths the host extracted from a captured zip, ready to
  // post straight to the Altium attach route.
  altiumPaths?: string[];
  signal?: "timeout";
}

const KICAD_REQS: Requirement[] = ["kicad_symbol", "kicad_footprint", "kicad_model"];
const ALTIUM_REQS: Requirement[] = ["altium_symbol", "altium_footprint"];
// If nothing lands within this window we stop waiting and offer retry/browse/guidance,
// instead of the old flow's unbounded "waiting" hang.
const WATCHDOG_MS = 180_000;

type Received = Partial<Record<Requirement, boolean>>;

interface State {
  status: GuidedStatus;
  message: string | null;
  url: string | null;
  vendor: string | null;
  needs: Requirement[];
  received: Received;
}

const IDLE: State = {
  status: "idle",
  message: null,
  url: null,
  vendor: null,
  needs: [],
  received: {},
};

function errMsg(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

function subsetComplete(needs: Requirement[], received: Received, subset: Requirement[]): boolean {
  return needs.filter((n) => subset.includes(n)).every((n) => received[n]);
}

// The host bridge is looked up ad hoc (matching the old idiom): only pywebview.api's
// own methods vary per flow, so we do not model them all in one global type.
function hostOpenCadDownload():
  | ((url: string, needs?: Requirement[]) => Promise<string | void> | string | void)
  | undefined {
  return (
    window as unknown as {
      pywebview?: {
        api?: {
          open_cad_download?: (
            url: string,
            needs?: Requirement[],
          ) => Promise<string | void> | string | void;
        };
      };
    }
  ).pywebview?.api?.open_cad_download;
}

export function useGuidedCapture(partId: string, needs: Requirement[] = []) {
  const [state, setState] = useState<State>(IDLE);
  const qc = useQueryClient();
  const tokenRef = useRef<string | null>(null);
  const needsRef = useRef<Requirement[]>(needs);
  const receivedRef = useRef<Received>({});
  const watchdogRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handlerRef = useRef<((payload: CaptureForward | string) => void) | null>(null);

  // The needs are owned by the caller's cad-source query, so needsRef is populated
  // even before start() runs. Without this, the manual "Browse For Files" path would
  // mark nothing (needsRef empty) and falsely report "done".
  const needsKey = needs.join(",");
  useEffect(() => {
    needsRef.current = needs;
    setState((s) => ({ ...s, needs }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [needsKey]);

  const invalidate = useCallback(() => {
    qc.invalidateQueries({ queryKey: ["parts"] });
    qc.invalidateQueries({ queryKey: ["facets"] });
    qc.invalidateQueries({ queryKey: ["duplicates"] });
    qc.invalidateQueries({ queryKey: ["part", partId] });
    qc.invalidateQueries({ queryKey: ["part-history", partId] });
    qc.invalidateQueries({ queryKey: ["cad-source", partId] });
  }, [qc, partId]);

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

  // Inspect a captured/picked KiCad path into a candidate, then commit the first onto
  // the part. The exact inspect -> commit tail the old hook used.
  const attachKicad = useCallback(
    async (paths: string[]) => {
      const { job_id: jobId } = await api.assetsInspect(partId, paths);
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
      await api.assetsCommit(partId, candidates[0]);
    },
    [partId],
  );

  const attachAltium = useCallback(
    async (paths: string[]) => {
      if (paths.length === 0) throw new Error("No Altium library files were captured.");
      await api.altiumAttach(partId, paths);
    },
    [partId],
  );

  const markReceived = useCallback((reqs: Requirement[]) => {
    const next = { ...receivedRef.current };
    reqs.forEach((r) => {
      if (needsRef.current.includes(r)) next[r] = true;
    });
    receivedRef.current = next;
    setState((s) => ({ ...s, received: next }));
  }, []);

  const allReceived = useCallback(
    () => needsRef.current.every((n) => receivedRef.current[n]),
    [],
  );

  // Re-register the one-shot global + arm the watchdog for the next capture.
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
      // Wrong-part guard (B4): a token'd forward from a stale session is ignored.
      if (tokenRef.current && p.token && p.token !== tokenRef.current) return;
      clearWatchdog();
      setState((s) => ({ ...s, status: "attaching", message: "Attaching the files to the part..." }));
      const reqs = p.requirements ?? [];
      const kicadReqs = reqs.filter((r) => KICAD_REQS.includes(r));
      const altiumReqs = reqs.filter((r) => ALTIUM_REQS.includes(r));
      // No classification (legacy bare path): treat it as a KiCad bundle.
      const wantKicad = kicadReqs.length > 0 || (reqs.length === 0 && !!p.path);
      try {
        if (wantKicad && p.path) {
          await attachKicad([p.path]);
          markReceived(kicadReqs.length ? kicadReqs : KICAD_REQS);
        }
        if (altiumReqs.length > 0) {
          await attachAltium(p.altiumPaths ?? (p.path ? [p.path] : []));
          markReceived(altiumReqs);
        }
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

  // onCapture re-arms itself after a partial capture; keep a stable ref so the
  // re-armed handler always points at the latest closure.
  const onCaptureRef = useRef(onCapture);
  useEffect(() => {
    onCaptureRef.current = onCapture;
  }, [onCapture]);

  const start = useCallback(async () => {
    clearWatchdog();
    clearHandler();
    receivedRef.current = {};
    tokenRef.current = null;
    // Keep the caller-owned needs (from the cad-source query) across the reset.
    setState({ ...IDLE, status: "resolving", message: "Looking up the download page...", needs: needsRef.current });
    let source: { url: string | null; vendor: string; needs: Requirement[] };
    try {
      source = await api.partCadSource(partId);
    } catch (err) {
      setState((s) => ({ ...s, status: "error", message: errMsg(err, "Could not resolve a CAD source.") }));
      return;
    }
    if (!source.url) {
      setState((s) => ({ ...s, status: "unavailable", message: "No CAD source page for this part." }));
      return;
    }
    setState((s) => ({ ...s, url: source.url, vendor: source.vendor, received: {} }));
    const open = hostOpenCadDownload();
    if (!open) {
      // A plain browser (no host bridge): guidance-only. The user opens the page,
      // downloads, then browses for the files. Still armed so a manual forward works.
      armCapture(onCaptureRef.current);
      setState((s) => ({
        ...s,
        status: "window-open",
        message: "Open the page, download the files, then pick them below.",
      }));
      return;
    }
    try {
      const returned = await open(source.url, needsRef.current);
      tokenRef.current = typeof returned === "string" && returned ? returned : null;
    } catch {
      // best-effort; the host may not echo a token, and the widened watch still fires.
    }
    armCapture(onCaptureRef.current);
    setState((s) => ({
      ...s,
      status: "receiving",
      message: "Waiting for the files. Follow the guidance in the window.",
    }));
  }, [partId, clearWatchdog, clearHandler, armCapture]);

  // Manual "Browse For Files" fallback: run the KiCad inspect -> commit tail on the
  // picked paths (the Altium half is served by the Altium panel's own picker).
  const submitPaths = useCallback(
    async (paths: string[]) => {
      if (paths.length === 0) return;
      clearWatchdog();
      setState((s) => ({ ...s, status: "attaching", message: "Attaching the files to the part..." }));
      try {
        await attachKicad(paths);
        markReceived(KICAD_REQS);
        invalidate();
        if (allReceived()) {
          clearHandler();
          setState((s) => ({ ...s, status: "done", message: "All files received and attached." }));
        } else {
          // Re-arm the watchdog so the remaining files can never hang forever (B1).
          armCapture(onCaptureRef.current);
          setState((s) => ({
            ...s,
            status: "receiving",
            message: "Received. Waiting for the remaining files...",
          }));
        }
      } catch (err) {
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
    tokenRef.current = null;
    receivedRef.current = {};
    // needs are caller-owned (synced from the cad-source query), so keep them.
    setState({ ...IDLE, needs: needsRef.current });
  }, [clearWatchdog, clearHandler]);

  return {
    ...state,
    kicadComplete: subsetComplete(state.needs, state.received, KICAD_REQS),
    altiumComplete: subsetComplete(state.needs, state.received, ALTIUM_REQS),
    start,
    submitPaths,
    reset,
  };
}
