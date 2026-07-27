/**
 * Clear CAD Files, a Settings section: remove every CAD asset the library holds, so a trusted
 * capture pass starts from nothing.
 *
 * Owner, 2026-07-27: *"remove all the current cad files before guided capture"*, against the
 * complaint the whole trust workstream exists for: *"a lot of our symbols, footprints, and 3d
 * models are broken so its not trusted where we've gotten them"*.
 *
 * THIS IS THE MOST DESTRUCTIVE CONTROL IN THE APP, so its design is mostly about being honest
 * before it acts rather than apologetic after:
 *  - The COUNT comes from the real walk (the backend's own dry run), so the number stated is the
 *    number the action will act on. It is not an estimate.
 *  - It says what it will NOT touch, by name. KiCad-stock references (`Device:R`) are counted
 *    separately and kept: they name no file this app holds, and clearing one would empty a
 *    passive permanently because nothing can refill it.
 *  - It confirms, through the app's own `ConfirmDialog` (the design spec forbids OS dialogs), and
 *    the confirm body repeats the exact numbers rather than a generic "are you sure".
 *  - It reports from the job's own result, never from the fact that it was started.
 *
 * PRIOR ART considered and REJECTED: nothing new was built. The read/act split, the `useJob`
 * usage and the primitives are `DerivationSection`'s; the confirm is the existing
 * `ConfirmDialog`, which already carries the danger tone, scrim dismissal and Escape. A bespoke
 * "type the word DELETE" gate was rejected: it is friction theatre next to a git-backed library
 * where the previous state is one revert away, and it is not a pattern this app uses anywhere.
 */
import { useCallback, useState } from "react";
import { api } from "../api/client";
import { useCadInventory } from "../api/queries";
import type { CadInventory } from "../api/types";
import { useJob } from "../lib/useJob";
import { useToast } from "../lib/toast";
import { Badge, Button } from "./primitives";
import { ConfirmDialog } from "./ConfirmDialog";

export function CadClearSection() {
  const inventory = useCadInventory();
  const job = useJob<CadInventory>();
  const { toast } = useToast();
  const [confirming, setConfirming] = useState(false);
  const [report, setReport] = useState<CadInventory | null>(null);

  const onClear = useCallback(async () => {
    setConfirming(false);
    setReport(null);
    let ref: { job_id: string };
    try {
      ref = await api.clearCad({ dryRun: false });
    } catch (err) {
      toast(err instanceof Error ? err.message : "Could not start the clear.", "err");
      return;
    }
    const finished = await job.run(ref.job_id);
    if (finished.status === "error") {
      toast(finished.error ?? "The clear failed.", "err");
      return;
    }
    const result = finished.result;
    if (!result) return;
    setReport(result);
    toast(
      result.cleared
        ? `Removed ${result.cleared} CAD ${result.cleared === 1 ? "file" : "files"}.`
        : "There was no CAD to remove.",
      result.cleared ? "ok" : "neutral",
    );
    inventory.refetch();
  }, [job, toast, inventory]);

  if (inventory.isLoading) {
    return <p className="py-1 text-sm text-t3">Counting the CAD your library holds...</p>;
  }
  if (inventory.isError || !inventory.data) {
    return <p className="py-1 text-sm text-err">Could not read your library.</p>;
  }

  const { cleared, kept_stock: keptStock, items } = inventory.data;
  const parts = items.length;

  return (
    <div className="flex flex-col gap-4">
      <p className="text-base text-t2">
        {cleared === 0 ? (
          "Your library holds no CAD files of its own."
        ) : (
          <>
            Your library holds <span className="tnum font-medium text-t1">{cleared}</span> CAD{" "}
            {cleared === 1 ? "file" : "files"} across{" "}
            <span className="tnum">{parts}</span> {parts === 1 ? "component" : "components"}:
            symbols, footprints and 3D models it downloaded or built.
          </>
        )}
      </p>

      {keptStock > 0 ? (
        <p className="border-l-2 border-line pl-3 text-sm text-t2">
          <span className="tnum">{keptStock}</span>{" "}
          {keptStock === 1 ? "reference points" : "references point"} at KiCad's own built-in
          libraries rather than at a file here, so {keptStock === 1 ? "it stays" : "they stay"}.
          Those are the passives, and removing them would leave nothing to put back.
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-3">
        <Button
          // The page-level TRIGGER is quiet; the loud solid `danger` is reserved for the
          // in-modal confirm, which is the committed action.
          variant="ghost-danger"
          onClick={() => setConfirming(true)}
          disabled={job.status === "running" || cleared === 0}
          data-dev-id="settings.cad-clear.run"
        >
          {job.status === "running" ? "Removing" : "Remove All CAD Files"}
        </Button>
        <p className="text-sm text-t2">
          Lands as one change you can revert. Components, specs, datasheets and the imported
          distributor data all stay; only the CAD goes.
        </p>
      </div>

      {job.status === "error" && job.error ? (
        <p className="text-sm text-err">{job.error}</p>
      ) : null}

      {report ? (
        <div className="flex flex-col gap-2 border-l-2 border-line pl-3 text-sm text-t2">
          <p>
            Removed <span className="tnum text-t1">{report.cleared}</span> CAD{" "}
            {report.cleared === 1 ? "file" : "files"} from{" "}
            <span className="tnum">{report.items.length}</span>{" "}
            {report.items.length === 1 ? "component" : "components"}.
          </p>
          {report.failed.length > 0 ? (
            <div>
              <Badge tone="err" size="sm">
                {report.failed.length === 1
                  ? "1 Component Could Not Be Cleared"
                  : `${report.failed.length} Components Could Not Be Cleared`}
              </Badge>
              <ul className="mt-1 list-disc pl-5">
                {report.failed.map((f) => (
                  <li key={f.id}>
                    <span className="font-medium text-t1">{f.id}</span>: {f.error}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}

      <ConfirmDialog
        open={confirming}
        danger
        title="Remove All CAD Files"
        confirmLabel="Remove Them"
        body={
          <>
            This removes {cleared} CAD {cleared === 1 ? "file" : "files"} from {parts}{" "}
            {parts === 1 ? "component" : "components"}: every symbol, footprint and 3D model your
            library holds. The components themselves, their specs, datasheets and imported
            distributor data are untouched, and{" "}
            {keptStock > 0 ? `the ${keptStock} references to KiCad's own libraries stay. ` : ""}
            it lands as one change you can revert.
          </>
        }
        onConfirm={onClear}
        onCancel={() => setConfirming(false)}
      />
    </div>
  );
}
