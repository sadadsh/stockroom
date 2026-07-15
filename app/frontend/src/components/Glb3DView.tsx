/**
 * The three.js GLB canvas, decoupled from where the GLB came from (a committed part or a
 * stock lib_id). Given the fetched GLB bytes plus the query's loading/error state, it
 * mounts the auto-rotating scene and degrades honestly: a 502 (no conversion tooling on
 * this machine) or a WebGL failure shows a plain message, never a blank canvas or a crash.
 * The heavy three.js code is import()ed lazily so it only loads when a 3D view is open.
 */
import { useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-full w-full items-center justify-center px-6 text-center text-sm text-t3">
      {children}
    </div>
  );
}

export function Glb3DView({
  data,
  isLoading,
  isError,
  error,
}: {
  data: ArrayBuffer | undefined;
  isLoading: boolean;
  isError: boolean;
  error?: unknown;
}) {
  const mountRef = useRef<HTMLDivElement>(null);
  const [renderError, setRenderError] = useState(false);

  useEffect(() => {
    const container = mountRef.current;
    if (!data || !container) return;
    let disposed = false;
    let dispose = () => {};
    void (async () => {
      try {
        const { mountModelScene } = await import("../lib/threeScene");
        if (disposed || !mountRef.current) return;
        dispose = mountModelScene(mountRef.current, data, () => {
          // GLTFLoader rejected the GLB asynchronously: show an honest message rather
          // than a blank canvas.
          if (!disposed) setRenderError(true);
        });
      } catch {
        // no WebGL context (or three failed to load): degrade honestly.
        if (!disposed) setRenderError(true);
      }
    })();
    return () => {
      disposed = true;
      dispose();
    };
  }, [data]);

  if (isLoading) {
    return <Centered>Loading 3D model...</Centered>;
  }
  if (isError) {
    const err = error instanceof ApiError ? error : null;
    // A 502 carries an honest, specific reason from the backend (tooling not installed,
    // or a WRL model that is not convertible yet) — show it rather than a single guess.
    const message =
      err?.status === 502 && err.message ? err.message : "Could not load the 3D model.";
    return <Centered>{message}</Centered>;
  }
  if (renderError) {
    return <Centered>This device could not render the 3D preview.</Centered>;
  }
  return <div ref={mountRef} className="h-full w-full" data-testid="model-canvas" />;
}
