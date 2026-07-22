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

export interface CaptureForward {
  path?: string;
  token?: string;
  requirements?: Requirement[];
  altiumPaths?: string[];
  signal?: "timeout";
}

export const KICAD_REQS: Requirement[] = ["kicad_symbol", "kicad_footprint", "kicad_model"];
export const ALTIUM_REQS: Requirement[] = ["altium_symbol", "altium_footprint"];
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

export interface CaptureApi {
  active: CaptureState;
  start: (partId: string, partName: string, needs: Requirement[]) => Promise<void>;
  submitPaths: (partId: string, partName: string, needs: Requirement[], paths: string[]) => Promise<void>;
  reset: () => void;
  keepWorking: () => void;
  // The pill asks to reopen its part's modal; the Components surface honors the intent.
  reopenPartId: string | null;
  requestReopen: () => void;
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
    await api.assetsCommit(pid, candidates[0]);
  }, []);

  const attachAltium = useCallback(async (paths: string[]) => {
    const pid = partIdRef.current;
    if (!pid) throw new Error("No active part for the capture.");
    if (paths.length === 0) throw new Error("No Altium library files were captured.");
    await api.altiumAttach(pid, paths);
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
      clearWatchdog();
      setState((s) => ({ ...s, status: "attaching", message: "Attaching the files to the part..." }));
      const reqs = p.requirements ?? [];
      const kicadReqs = reqs.filter((r) => KICAD_REQS.includes(r));
      const altiumReqs = reqs.filter((r) => ALTIUM_REQS.includes(r));
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

  const onCaptureRef = useRef(onCapture);
  useEffect(() => {
    onCaptureRef.current = onCapture;
  }, [onCapture]);

  const start = useCallback(
    async (partId: string, partName: string, needs: Requirement[]) => {
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
    },
    [clearWatchdog, clearHandler, armCapture],
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

  const clearReopen = useCallback(() => setReopenPartId(null), []);

  return (
    <CaptureContext.Provider
      value={{ active: state, start, submitPaths, reset, keepWorking, reopenPartId, requestReopen, clearReopen }}
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
