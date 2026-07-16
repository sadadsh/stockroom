/**
 * Doctor (M6f): keep the library healthy and wired into KiCad.
 *
 *  - Library Health reads GET /api/doctor/scan and shows, honestly, what a one-click
 *    repair CAN fix (drift toward the JSON source of truth, non-portable 3D-model
 *    links rewritten to ${SR_LIB}, stray files committed) versus what it CANNOT (a
 *    missing file is never fabricated, and a broken reference is never silently
 *    deleted — those are shown with how to resolve them by hand). Repair runs the
 *    atomic POST /api/doctor/repair and the surface refreshes itself.
 *  - KiCad Wiring surfaces the existing wire-kicad job: register the active profile
 *    into KiCad's library tables, honestly reporting when a restart is needed.
 *
 * Every defect is surfaced or explained; nothing is hidden behind a green light.
 */
import { useState, type ReactNode } from "react";
import { ApiError } from "../api/client";
import { api } from "../api/client";
import { useDoctorScan, useRepairLibrary, useSystemInfo } from "../api/queries";
import type {
  DoctorScan,
  RepairAction,
  RepairFinding,
  RepairResult,
  WiringReport,
} from "../api/types";
import { useJob } from "../lib/useJob";
import { useToast } from "../lib/toast";
import { Badge, Button, Card, Dot, Eyebrow } from "../components/primitives";

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

function Section({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <section className="mb-7">
      <Eyebrow className="mb-2">{title}</Eyebrow>
      {hint ? <p className="mb-2.5 text-xs text-t3">{hint}</p> : null}
      <Card className="px-4 py-3.5">{children}</Card>
    </section>
  );
}

export function DoctorPage() {
  return (
    <>
      <div className="min-h-0 flex-1 overflow-y-auto px-[30px] pt-[22px]">
        <div className="max-w-[760px] pb-12">
          <HealthSection />
          <WiringSection />
        </div>
      </div>
    </>
  );
}

function HealthSection() {
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
    <Section
      title="Component Health"
      hint="Reconcile every part with its record and every file with the repository. Repair heals what it safely can and lists what needs your hand."
    >
      {scan.isLoading ? (
        <p className="py-1 text-sm text-t3">Scanning your components...</p>
      ) : scan.isError ? (
        <p className="py-1 text-sm text-err">Could not scan your components.</p>
      ) : scan.data ? (
        <HealthBody data={scan.data} onRepair={onRepair} repairing={repair.isPending} />
      ) : null}
    </Section>
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
          Your components are healthy. Every part matches its record and every file is committed.
        </span>
      </div>
    );
  }

  const fixableCount = data.fixable.length + data.uncommitted.length;
  return (
    <div className="flex flex-col gap-4">
      {data.fixable.length > 0 ? (
        <div className="flex flex-col gap-2">
          <div className="text-xs font-semibold text-t2">Can Be Repaired</div>
          {data.fixable.map((action, i) => (
            <ActionRow key={`${action.kind}-${action.part_id}-${i}`} action={action} />
          ))}
        </div>
      ) : null}

      {data.uncommitted.length > 0 ? (
        <div className="text-xs text-t3" data-testid="doctor-uncommitted">
          {data.uncommitted.length}{" "}
          {data.uncommitted.length === 1 ? "uncommitted change" : "uncommitted changes"} in the
          working tree will be committed by the repair.
        </div>
      ) : null}

      {fixableCount > 0 ? (
        <div>
          <Button variant="accent" onClick={onRepair} disabled={repairing}>
            {repairing ? "Repairing..." : "Repair Components"}
          </Button>
        </div>
      ) : null}

      {data.manual.length > 0 ? (
        <div className="flex flex-col gap-2 border-t border-line pt-3">
          <div className="text-xs font-semibold text-t2">Needs Attention</div>
          <p className="text-xs text-t3">
            These cannot be fixed automatically. A missing file is never fabricated and a broken
            reference is never silently removed.
          </p>
          {data.manual.map((finding, i) => (
            <FindingRow key={`${finding.kind}-${finding.part_id}-${i}`} finding={finding} />
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
        <span className="text-ok">{action.after}</span>
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

function WiringSection() {
  const sys = useSystemInfo();
  const job = useJob<WiringReport>();
  const { toast } = useToast();
  const [starting, setStarting] = useState(false);

  async function onWire() {
    setStarting(true);
    try {
      const { job_id } = await api.wireKicad();
      job.run(job_id);
    } catch (e) {
      toast(errMsg(e), "err");
    } finally {
      setStarting(false);
    }
  }

  const busy = starting || job.status === "running";
  const report = job.status === "done" ? job.result : null;

  return (
    <Section
      title="KiCad Wiring"
      hint="Register the active profile's symbols and footprints in KiCad so it resolves every part. Safe to re-run; existing rows are left untouched."
    >
      <div className="flex flex-col gap-3">
        {sys.data ? (
          <div className="flex items-center gap-2 text-xs text-t3">
            <Dot tone={sys.data.kicad_cli_available ? "ok" : "warn"} />
            <span>
              {sys.data.kicad_cli_available
                ? `KiCad CLI found at ${sys.data.kicad_cli_path}.`
                : "KiCad CLI was not found; wiring still writes the KiCad tables."}
            </span>
          </div>
        ) : null}

        <div>
          <Button onClick={onWire} disabled={busy}>
            {busy ? "Wiring..." : "Wire KiCad"}
          </Button>
        </div>

        {job.status === "running" && job.progress?.message ? (
          <p className="text-xs text-t3">{job.progress.message}...</p>
        ) : null}

        {job.status === "error" ? (
          <p className="text-sm text-err">{job.error ?? "Wiring failed."}</p>
        ) : null}

        {report ? (
          <div className="flex flex-col gap-1.5 rounded-control border border-line bg-raise2 p-3 text-xs">
            <div className="text-t2">
              Registered {report.categories_registered.length}{" "}
              {report.categories_registered.length === 1 ? "category" : "categories"}: added{" "}
              {report.symbol_rows_added} symbol and {report.footprint_rows_added} footprint{" "}
              {report.footprint_rows_added === 1 ? "row" : "rows"}.
            </div>
            {report.restart_needed ? (
              <div className="flex items-center gap-2 text-warn">
                <Dot tone="warn" />
                <span>Restart KiCad to load the updated tables.</span>
              </div>
            ) : (
              <div className="flex items-center gap-2 text-ok">
                <Dot tone="ok" />
                <span>KiCad is wired and ready.</span>
              </div>
            )}
          </div>
        ) : null}
      </div>
    </Section>
  );
}
