/**
 * The honest "index not built" call to action (CONTEXT decision 9): the STM32 spec matrix, pinout
 * maps, and compatibility workbench are all served from a derived index that runs once per machine.
 * When the backend reports it is not built (HTTP 409), every STM surface routes here rather than a
 * raw error or an infinite spinner. Extracted from StmViewerPage so the page gate AND the workbench's
 * own 409 safety net render the SAME state, never a second invented one.
 *
 * It drives the build job's live progress over the existing SSE (mirroring the library RescanSection
 * running/done/error flow); on success it re-queries the STM surface so the gate clears to the real
 * content.
 */
import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useBuildStmIndex } from "../../api/stmQueries";
import { Button, Card, Eyebrow } from "../primitives";

export function BuildIndexGate() {
  const build = useBuildStmIndex();
  const qc = useQueryClient();

  useEffect(() => {
    if (build.status === "done") {
      qc.invalidateQueries({ queryKey: ["stm-status"] });
      qc.invalidateQueries({ queryKey: ["stm-mcus"] });
      qc.invalidateQueries({ queryKey: ["stm-families"] });
    }
  }, [build.status, qc]);

  const running = build.status === "running";
  const pct =
    build.progress?.pct != null ? Math.min(100, Math.round(build.progress.pct)) : null;

  return (
    <div className="flex flex-1 items-center justify-center px-6 py-10">
      <Card className="w-full max-w-[440px] px-6 py-6">
        <Eyebrow className="mb-2">STM Index</Eyebrow>
        <h2 className="mb-1.5 text-lg font-semibold text-t1">Build the Index</h2>
        <p className="mb-4 text-sm text-t2">
          The STM32 spec matrix and pinout maps are served from a derived index built from your
          CubeMX source. It has not been built yet on this machine. Building runs once and takes a
          moment.
        </p>

        {running ? (
          <div className="mb-4 flex flex-col gap-2" data-testid="stm-build-running">
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-raise2">
              <div
                className="h-full rounded-full bg-acc transition-[width]"
                style={{ width: pct != null ? `${pct}%` : "35%" }}
              />
            </div>
            <p className="text-xs text-t3">{build.progress?.message ?? "Starting the build..."}</p>
          </div>
        ) : null}

        {build.status === "error" ? (
          <p className="mb-4 text-sm text-err" data-testid="stm-build-error">
            {build.error}
          </p>
        ) : null}

        <Button variant="accent" onClick={() => build.start()} disabled={running}>
          {running ? "Building..." : build.status === "error" ? "Try Again" : "Build the Index"}
        </Button>
      </Card>
    </div>
  );
}
