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
import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useBuildStmIndex, useStmStatus } from "../../api/stmQueries";
import { useSettings, useUpdateSettings } from "../../api/queries";
import { pickHostFolder } from "../../lib/hostFolderPicker";
import { Button, Card, Eyebrow } from "../primitives";
import { Text, useText } from "../../lib/copy";

export function BuildIndexGate() {
  const build = useBuildStmIndex();
  const status = useStmStatus();
  const qc = useQueryClient();
  const settings = useSettings();
  const updateSettings = useUpdateSettings();
  const [pickerError, setPickerError] = useState("");
  const startingLabel = useText("stm.index.starting", "Starting the build...");
  const needsSourceLabel = useText(
    "stm.index.needs-source",
    "Choose the STM32CubeMX data folder to build the index.",
  );
  const saveFailedLabel = useText("stm.index.save-failed", "Could not save the CubeMX folder.");
  const checkingLabel = useText("stm.index.action.checking", "Checking Source...");
  const buildingLabel = useText("stm.index.action.building", "Building...");
  const savingLabel = useText("stm.index.action.saving", "Saving...");
  const chooseFolderLabel = useText("stm.index.action.choose-source", "Choose CubeMX Folder");
  const retryLabel = useText("stm.index.action.retry", "Rerun");
  const buildLabel = useText("stm.index.action.build", "Build the Index");

  useEffect(() => {
    if (build.status === "done") {
      qc.invalidateQueries({ queryKey: ["stm-status"] });
      qc.invalidateQueries({ queryKey: ["stm-mcus"] });
      qc.invalidateQueries({ queryKey: ["stm-families"] });
    }
  }, [build.status, qc]);

  const running = build.status === "running";
  const checkingSource = status.isLoading && !status.data;
  const needsSource =
    status.data?.source_present === false ||
    (build.status === "error" && /cubemx|source configured|source folder/i.test(build.error ?? ""));
  const pct =
    build.progress?.pct != null ? Math.min(100, Math.round(build.progress.pct)) : null;

  async function chooseSourceAndBuild() {
    setPickerError("");
    try {
      const source = await pickHostFolder("stm-cubemx");
      if (!source) return;
      await updateSettings.mutateAsync({ stm_cubemx_source: source });
      build.start();
    } catch (error) {
      setPickerError(error instanceof Error ? error.message : saveFailedLabel);
    }
  }

  return (
    <div className="flex flex-1 items-center justify-center px-6 py-10">
      <Card className="w-full max-w-[440px] px-6 py-6">
        <Eyebrow className="mb-2">
          <Text id="stm.index.eyebrow">STM Index</Text>
        </Eyebrow>
        <h2 className="mb-1.5 text-lg font-semibold text-t1">
          <Text id="stm.index.title">Build the Index</Text>
        </h2>
        <p className="mb-4 text-sm text-t2">
          <Text id="stm.index.body">The STM32 spec matrix and pinout maps are served from a derived index built from the CubeMX source. It has not been built on this machine. Building runs once and takes a moment.</Text>
        </p>

        {running ? (
          <div className="mb-4 flex flex-col gap-2" data-testid="stm-build-running">
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-raise2">
              <div
                className="h-full rounded-full bg-acc transition-[width]"
                style={{ width: pct != null ? `${pct}%` : "35%" }}
              />
            </div>
            <p className="text-xs text-t3">{build.progress?.message ?? startingLabel}</p>
          </div>
        ) : null}

        {build.status === "error" ? (
          <p className="mb-4 text-sm text-err-text" data-testid="stm-build-error">
            {needsSource ? needsSourceLabel : build.error}
          </p>
        ) : null}

        {pickerError ? <p className="mb-4 text-sm text-err-text">{pickerError}</p> : null}

        {settings.data?.stm_cubemx_source ? (
          <p
            className="mb-4 truncate font-mono text-xs text-t3"
            title={settings.data.stm_cubemx_source}
          >
            {settings.data.stm_cubemx_source}
          </p>
        ) : null}

        <Button
          variant="accent"
          onClick={needsSource ? chooseSourceAndBuild : () => build.start()}
          disabled={running || checkingSource || updateSettings.isPending}
        >
          {checkingSource
            ? checkingLabel
            : running
            ? buildingLabel
            : updateSettings.isPending
              ? savingLabel
              : needsSource
                ? chooseFolderLabel
                : build.status === "error"
                  ? retryLabel
                  : buildLabel}
        </Button>
      </Card>
    </div>
  );
}
