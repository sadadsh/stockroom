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
import { Text } from "../lib/copy";
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
        ? `Removed ${result.cleared} CAD ${result.cleared === 1 ? "asset" : "assets"}.`
        : "There was no CAD to remove.",
      result.cleared ? "ok" : "neutral",
    );
    inventory.refetch();
  }, [job, toast, inventory]);

  if (inventory.isLoading) {
    return (
      <p className="py-1 text-sm text-t3">
        <Text id="cad.clear.loading">Counting the CAD your library holds...</Text>
      </p>
    );
  }
  if (inventory.isError || !inventory.data) {
    return (
      <p className="py-1 text-sm text-err">
        <Text id="cad.clear.error">Could not read your library.</Text>
      </p>
    );
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
            {/* "assets", not "files": a KiCad symbol is an ENTRY inside a shared
                `SR-<Category>.kicad_sym`, and an Altium 3D body lives INSIDE its `.PcbLib`, so
                the 184 things being removed are not 184 files. Saying "files" over-counts by
                roughly a third and is the count-does-not-agree-with-its-noun defect this repo
                already gates on the backend. The trailing clause names what they are. */}
            Your library holds <span className="tnum font-medium text-t1">{cleared}</span> CAD{" "}
            {cleared === 1 ? "asset" : "assets"} across{" "}
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

      {/* With nothing to remove, the action is not merely disabled -- it is ABSENT. A
          destructive-looking control at 50% opacity still reads as available, and the sentence
          beside it would be describing something that cannot happen. The "holds no CAD files"
          line above is the whole answer in that state. */}
      {cleared > 0 ? (
        <div className="flex flex-wrap items-center gap-3">
          <Button
            // The page-level TRIGGER is quiet; the loud solid `danger` is reserved for the
            // in-modal confirm, which is the committed action.
            variant="ghost-danger"
            onClick={() => setConfirming(true)}
            disabled={job.status === "running"}
            data-dev-id="settings.cad-clear.run"
          >
            {job.status === "running" ? "Removing" : "Remove All CAD Files"}
          </Button>
          {/* Says what the disclosure's hint does NOT: that it is atomic and revertible. Repeating
              the hint's "components and specs all stay" here is the same duplication caught in
              DerivationSection, 230px apart on the same screen. */}
          <p className="text-sm text-t2">
            <Text id="cad.clear.revertible">Lands as one change you can revert.</Text>
          </p>
        </div>
      ) : null}

      {job.status === "error" && job.error ? (
        <p className="text-sm text-err">{job.error}</p>
      ) : null}

      {report ? (
        <div className="flex flex-col gap-2 border-l-2 border-line pl-3 text-sm text-t2">
          <p>
            <Text id="cad.clear.report-removed">Removed</Text>{" "}
            <span className="tnum text-t1">{report.cleared}</span> CAD{" "}
            {report.cleared === 1 ? "asset" : "assets"} from{" "}
            <span className="tnum">{report.items.length}</span>{" "}
            {report.items.length === 1 ? "component" : "components"}.
          </p>
          {report.missing_files.length > 0 ? (
            <div>
              <p>
                <span className="tnum">{report.missing_files.length}</span>{" "}
                {report.missing_files.length === 1 ? "reference" : "references"} pointed at a file
                that was not there. The {report.missing_files.length === 1 ? "reference is" : "references are"}{" "}
                cleared either way, and the {report.missing_files.length === 1 ? "path is" : "paths are"} listed
                so nothing is quietly counted as deleted.
              </p>
              <ul className="mt-1 list-disc pl-5">
                {report.missing_files.slice(0, 10).map((m) => (
                  <li key={`${m.part_id}:${m.asset}`}>
                    <span className="font-medium text-t1">{m.part_id}</span> {m.asset}:{" "}
                    <span className="font-mono">{m.expected}</span>
                  </li>
                ))}
              </ul>
              {report.missing_files.length > 10 ? (
                <p className="mt-1 tnum">
                  <Text
                    id="cad.clear.more-missing"
                    values={{ count: report.missing_files.length - 10 }}
                  >{"and {count} more."}</Text>
                </p>
              ) : null}
            </div>
          ) : null}
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
            This removes {cleared} CAD {cleared === 1 ? "asset" : "assets"} from {parts}{" "}
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
