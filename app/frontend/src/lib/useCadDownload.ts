/**
 * Get CAD Files From DigiKey (Phase-2 asset download, spec section 5): resolve a part's
 * DigiKey product page from its MPN, open it in the host's dedicated CAD-download
 * window, and auto-attach whatever symbol/footprint/3D the captured ZIP yields onto the
 * part - the SAME inspect -> commit pipeline the manual Add-A-Part ZIP drop already uses
 * (`/api/parts/{id}/assets/{inspect,commit}`), so a part that landed identity-only picks
 * up its CAD assets with one click instead of a manual ZIP hunt.
 *
 * Mirrors useRescan's SSE plumbing (api.openJobStream + streamEvents, the same
 * open-failure / mid-stream-error / abnormal-EOF handling) for the inspect job, and
 * IngestPage's inspect -> commit sequencing for the candidate.
 *
 * Convergence point: whichever tier of the host's download capture wins (WebView2
 * download-intercept or the Downloads-folder watch), it calls the SAME global,
 * window.__STOCKROOM_CAD_DOWNLOAD__(path) - registered here as a ONE-SHOT handler for
 * the lifetime of a single start() call, mirroring how AppShell registers
 * window.__STOCKROOM_NATIVE_DROP__ for native drag-drop. submitPaths is exposed
 * separately so the SAME pipeline also serves the manual-pick fallback (a plain
 * browser with no window.pywebview, or a host whose capture never fires): the caller
 * feeds it a path from window.pywebview.api.pick_ingest_files() instead.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import type { StagingCandidate } from "../api/types";
import { streamEvents } from "./sse";

export type CadDownloadStatus =
  | "idle"
  | "waiting"
  | "inspecting"
  | "committing"
  | "done"
  | "unavailable"
  | "error";

interface CadDownloadState {
  status: CadDownloadStatus;
  message: string | null;
  // The resolved DigiKey product page, kept around so the control can offer an
  // explicit "open it again" / manual link even after the host's own window opened
  // (or in a plain browser, where nothing opened it automatically at all).
  url: string | null;
}

const IDLE_STATE: CadDownloadState = { status: "idle", message: null, url: null };

function errMsg(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

// The host bridge is looked up ad hoc (matching IngestPage's browseForZip idiom)
// rather than typed globally: only pywebview.api's OWN methods vary per flow, and a
// blanket Window.pywebview type would have to model every host method in one place.
function hostOpenCadDownload(): ((url: string) => void) | undefined {
  return (
    window as unknown as {
      pywebview?: { api?: { open_cad_download?: (url: string) => void } };
    }
  ).pywebview?.api?.open_cad_download;
}

export function useCadDownload(partId: string) {
  const [state, setState] = useState<CadDownloadState>(IDLE_STATE);
  const qc = useQueryClient();
  // The one-shot global handler registered for exactly one in-flight start() call.
  // Cleared on fire, on a fresh start(), and on unmount, so a stale handler from an
  // abandoned attempt can never fire onto an unmounted hook or collide with a second
  // attempt's own handler.
  const cleanupRef = useRef<(() => void) | null>(null);

  const clearHandler = useCallback(() => {
    cleanupRef.current?.();
    cleanupRef.current = null;
  }, []);

  useEffect(() => clearHandler, [clearHandler]);

  // A write changed the part's assets: invalidate exactly the caches any other
  // part-mutation invalidates (mirrors useInvalidateAfterWrite in api/queries.ts),
  // plus the cad-source gate query so a now-complete part's control can re-decide
  // whether it still has anything to offer.
  const invalidate = useCallback(() => {
    qc.invalidateQueries({ queryKey: ["parts"] });
    qc.invalidateQueries({ queryKey: ["facets"] });
    qc.invalidateQueries({ queryKey: ["duplicates"] });
    qc.invalidateQueries({ queryKey: ["part", partId] });
    qc.invalidateQueries({ queryKey: ["part-history", partId] });
    qc.invalidateQueries({ queryKey: ["cad-source", partId] });
  }, [qc, partId]);

  // The shared tail: inspect the captured/picked ZIP path(s) into a candidate, then
  // commit the first one onto the part. Used by BOTH the host's captured-download
  // callback and the manual-pick fallback, so a plain browser (or a host whose
  // capture never fires) still reaches the exact same outcome through the existing
  // picker.
  const submitPaths = useCallback(
    async (paths: string[]) => {
      if (paths.length === 0) return;
      setState((s) => ({
        status: "inspecting",
        message: "Inspecting the download...",
        url: s.url,
      }));
      let jobId: string;
      try {
        ({ job_id: jobId } = await api.assetsInspect(partId, paths));
      } catch (err) {
        setState((s) => ({
          status: "error",
          message: errMsg(err, "Could not inspect the download."),
          url: s.url,
        }));
        return;
      }
      let body: ReadableStream<Uint8Array>;
      try {
        body = await api.openJobStream(jobId);
      } catch (err) {
        setState((s) => ({
          status: "error",
          message: errMsg(err, "Could not open the inspect stream."),
          url: s.url,
        }));
        return;
      }
      let candidates: StagingCandidate[] | null = null;
      let streamError: string | null = null;
      try {
        for await (const ev of streamEvents(body)) {
          if (ev.event === "result") {
            candidates = (ev.data as { result: StagingCandidate[] }).result;
          } else if (ev.event === "error") {
            streamError = (ev.data as { detail?: string }).detail ?? "The inspect failed.";
          } else if (ev.event === "done") {
            break;
          }
        }
      } catch (err) {
        setState((s) => ({
          status: "error",
          message: errMsg(err, "The inspect stream broke."),
          url: s.url,
        }));
        return;
      }
      if (streamError) {
        setState((s) => ({ status: "error", message: streamError, url: s.url }));
        return;
      }
      if (!candidates || candidates.length === 0) {
        setState((s) => ({
          status: "error",
          message: "No usable symbol, footprint, or 3D model found in the download.",
          url: s.url,
        }));
        return;
      }
      setState((s) => ({
        status: "committing",
        message: "Attaching the files to the part...",
        url: s.url,
      }));
      try {
        await api.assetsCommit(partId, candidates[0]);
      } catch (err) {
        setState((s) => ({
          status: "error",
          message:
            err instanceof ApiError ? err.message : errMsg(err, "Could not attach the files."),
          url: s.url,
        }));
        return;
      }
      invalidate();
      setState((s) => ({
        status: "done",
        message: "Symbol, footprint, and 3D model attached.",
        url: s.url,
      }));
    },
    [partId, invalidate],
  );

  const start = useCallback(async () => {
    clearHandler();
    setState({ status: "waiting", message: "Looking up the DigiKey page...", url: null });
    let source: { url: string | null };
    try {
      source = await api.partCadSource(partId);
    } catch (err) {
      setState({
        status: "error",
        message: errMsg(err, "Could not resolve the DigiKey page."),
        url: null,
      });
      return;
    }
    if (!source.url) {
      setState({
        status: "unavailable",
        message: "No DigiKey CAD source for this part.",
        url: null,
      });
      return;
    }
    const url = source.url;
    const openCadDownload = hostOpenCadDownload();
    if (openCadDownload) {
      setState({ status: "waiting", message: "Waiting for the download...", url });
      let fired = false;
      const handler = (path: string) => {
        if (fired) return;
        fired = true;
        clearHandler();
        void submitPaths([path]);
      };
      window.__STOCKROOM_CAD_DOWNLOAD__ = handler;
      cleanupRef.current = () => {
        if (window.__STOCKROOM_CAD_DOWNLOAD__ === handler) {
          delete window.__STOCKROOM_CAD_DOWNLOAD__;
        }
      };
      try {
        openCadDownload(url);
      } catch {
        // best-effort open; the waiting state (and the manual pick fallback the
        // control offers) still lets the owner recover without a crash.
      }
    } else {
      // A plain browser (no window.pywebview at all): nothing can auto-open the page
      // or capture a download, but this must degrade honestly, never throw. The
      // resolved url is still surfaced so the control can offer it as a manual link;
      // the manual ZIP picker also depends on a host bridge, so in a truly bare
      // browser there is nothing further to do but wait for the owner to bring a
      // path some other way.
      setState({
        status: "waiting",
        message: "Open the DigiKey page and download the CAD ZIP, then pick it below.",
        url,
      });
    }
  }, [partId, clearHandler, submitPaths]);

  const reset = useCallback(() => {
    clearHandler();
    setState(IDLE_STATE);
  }, [clearHandler]);

  return { ...state, start, submitPaths, reset };
}
