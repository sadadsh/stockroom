/**
 * Library Health, a Settings section (was the Doctor page's health half, moved
 * here in D3). Reads GET /api/doctor/scan and shows honestly what a one-click
 * repair CAN fix (drift toward the JSON source of truth, non-portable 3D-model
 * links rewritten to ${SR_LIB}, stray files committed) versus what it CANNOT (a
 * missing file is never fabricated, a broken reference is never silently deleted).
 * Repair runs the atomic POST /api/doctor/repair and the surface refreshes itself.
 */
import { ApiError } from "../api/client";
import { useDoctorScan, useRepairLibrary } from "../api/queries";
import type { DoctorScan, RepairAction, RepairFinding, RepairResult } from "../api/types";
import { useToast } from "../lib/toast";
import { statusTone } from "../lib/statusTone";
import { Text } from "../lib/copy";
import { Badge, Button, Dot } from "./primitives";

function errMsg(err: unknown): string {
  return err instanceof ApiError ? err.message : "Something went wrong.";
}

const ACTION_LABEL: Record<RepairAction["kind"], string> = {
  drift: "Drift",
  model_path: "Model Path",
};

const FINDING_LABEL: Record<RepairFinding["kind"], string> = {
  missing_symbol: "Missing Symbol",
  dangling_model: "Missing 3D Model",
  dangling_datasheet: "Missing Datasheet",
  dangling_model_link: "Broken Model Link",
  unparseable_file: "Corrupt File",
};

function summarize(r: RepairResult): string {
  const bits: string[] = [];
  if (r.healed_drift)
    bits.push(`${r.healed_drift} drift ${r.healed_drift === 1 ? "mismatch" : "mismatches"} healed`);
  if (r.fixed_paths)
    bits.push(`${r.fixed_paths} model ${r.fixed_paths === 1 ? "link" : "links"} repaired`);
  if (r.committed_files)
    bits.push(`${r.committed_files} ${r.committed_files === 1 ? "file" : "files"} committed`);
  return bits.length ? `Repaired: ${bits.join(", ")}.` : "Nothing needed repair.";
}

export function LibraryHealthSection() {
  const scan = useDoctorScan();
  const repair = useRepairLibrary();
  const { toast } = useToast();

  function onRepair() {
    repair.mutate(undefined, {
      onSuccess: (result) => toast(summarize(result), "ok"),
      onError: (e) => toast(errMsg(e), "err"),
    });
  }

  return (
    <>
        {scan.isLoading ? (
          <p className="py-1 text-sm text-t3">
            <Text id="library.health.loading">Scanning the components...</Text>
          </p>
        ) : scan.isError ? (
          <p className="py-1 text-sm text-err-text">
            <Text id="library.health.error">Could not scan the components.</Text>
          </p>
        ) : scan.data ? (
          <HealthBody data={scan.data} onRepair={onRepair} repairing={repair.isPending} />
        ) : null}
    </>
  );
}

function HealthBody({
  data,
  onRepair,
  repairing,
}: {
  data: DoctorScan;
  onRepair: () => void;
  repairing: boolean;
}) {
  if (data.healthy) {
    return (
      <div className="flex items-center gap-2.5 py-1" data-testid="doctor-healthy">
        <Dot tone="ok" />
        <span className="text-sm text-t2">
          <Text id="library.health.healthy">
            Your components are sound. Each part matches its record and each file is committed.
          </Text>
        </span>
      </div>
    );
  }

  const fixableCount = data.fixable.length + data.uncommitted.length;
  return (
    <div className="flex flex-col gap-4">
      {data.fixable.length > 0 ? (
        <div className="flex flex-col gap-2">
          <div className="text-xs font-semibold text-t2">
            <Text id="library.health.fixable-heading">Can Be Repaired</Text>
          </div>
          {/* kind + part + detail IS the action's identity: `detail` names the exact field or
              file, so two actions can never collide without being the same action. Keying on the
              position reassigned rows every time a repair shortened the list. */}
          {data.fixable.map((action) => (
            <ActionRow
              key={`${action.kind}:${action.part_id}:${action.detail}`}
              action={action}
            />
          ))}
        </div>
      ) : null}

      {data.uncommitted.length > 0 ? (
        <div className="text-xs text-t3" data-testid="doctor-uncommitted">
          <span className={`font-semibold ${statusTone("uncommitted").text}`}>
            {data.uncommitted.length}{" "}
            {data.uncommitted.length === 1 ? "uncommitted change" : "uncommitted changes"}
          </span>{" "}
          <Text id="library.health.uncommitted-note">
            in the working tree will be committed as part of the repair.
          </Text>
        </div>
      ) : null}

      {fixableCount > 0 ? (
        <div>
          <Button variant="accent" onClick={onRepair} disabled={repairing} data-dev-id="settings.health-repair">
            {repairing ? (
              <Text id="library.health.repair-busy">Repairing...</Text>
            ) : (
              <Text id="library.health.repair">Commit Safe Catalog Repairs</Text>
            )}
          </Button>
        </div>
      ) : null}

      {data.manual.length > 0 ? (
        <div className="flex flex-col gap-2 border-t border-line pt-3">
          <div className="text-xs font-semibold text-t2">
            <Text id="library.health.manual-heading">Needs Attention</Text>
          </div>
          <p className="text-xs text-t3">
            <Text id="library.health.manual-note">No automatic repair can fix these. A missing file is never fabricated and a broken reference is never removed in silence.</Text>
          </p>
          {data.manual.map((finding) => (
            <FindingRow
              key={`${finding.kind}:${finding.part_id}:${finding.detail}`}
              finding={finding}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ActionRow({ action }: { action: RepairAction }) {
  return (
    <div
      data-testid={`doctor-fixable-${action.part_id}`}
      className="flex flex-col gap-1 rounded-control border border-line bg-raise2 p-3"
    >
      <div className="flex items-center gap-2">
        <Badge tone="warn">{ACTION_LABEL[action.kind]}</Badge>
        <span className="min-w-0 truncate font-mono text-xs text-t2">{action.part_id}</span>
      </div>
      <div className="text-sm text-t1">{action.detail}</div>
      <div className="flex flex-wrap items-center gap-2 font-mono text-xs">
        <span className="text-t3 line-through">{action.before || "(empty)"}</span>
        <span className="text-ok-text">{action.after}</span>
      </div>
    </div>
  );
}

function FindingRow({ finding }: { finding: RepairFinding }) {
  return (
    <div
      data-testid={`doctor-manual-${finding.part_id}`}
      className="flex flex-col gap-1 rounded-control border border-line bg-raise2 p-3"
    >
      <div className="flex items-center gap-2">
        <Badge tone="err">{FINDING_LABEL[finding.kind]}</Badge>
        <span className="min-w-0 truncate font-mono text-xs text-t2">{finding.part_id}</span>
      </div>
      <div className="text-sm text-t1">{finding.detail}</div>
      <div className="text-xs text-t3">Fix: {finding.how_to_fix}</div>
    </div>
  );
}
