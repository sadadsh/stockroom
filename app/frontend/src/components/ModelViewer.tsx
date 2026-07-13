/**
 * The 3D model preview (M6d). Fetches the GLB (converted from the part's STEP/WRL by the
 * backend) and mounts it with three.js. Every non-happy path is honest: while the model
 * loads it says so; a 502 (no conversion tooling installed on this machine) or a WebGL
 * failure degrades to a plain message instead of a blank canvas or a crash. The heavy
 * three.js code is import()ed lazily so it only loads when a 3D preview is actually opened.
 */
import { useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";
import { usePreviewGlb } from "../api/queries";

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-full w-full items-center justify-center px-6 text-center text-sm text-t3">
      {children}
    </div>
  );
}

export function ModelViewer({ partId }: { partId: string }) {
  const query = usePreviewGlb(partId, true);
  const mountRef = useRef<HTMLDivElement>(null);
  const [renderError, setRenderError] = useState(false);

  useEffect(() => {
    const container = mountRef.current;
    if (!query.data || !container) return;
    let disposed = false;
    let dispose = () => {};
    void (async () => {
      try {
        const { mountModelScene } = await import("../lib/threeScene");
        if (disposed || !mountRef.current) return;
        dispose = mountModelScene(mountRef.current, query.data as ArrayBuffer);
      } catch {
        // no WebGL context (or three failed to load): degrade honestly.
        if (!disposed) setRenderError(true);
      }
    })();
    return () => {
      disposed = true;
      dispose();
    };
  }, [query.data]);

  if (query.isLoading) {
    return <Centered>Loading 3D model...</Centered>;
  }
  if (query.isError) {
    const status = query.error instanceof ApiError ? query.error.status : 0;
    return (
      <Centered>
        {status === 502
          ? "3D preview is unavailable: the model conversion tooling is not installed on this machine."
          : "Could not load the 3D model."}
      </Centered>
    );
  }
  if (renderError) {
    return <Centered>This device could not render the 3D preview.</Centered>;
  }
  return <div ref={mountRef} className="h-full w-full" data-testid="model-canvas" />;
}
