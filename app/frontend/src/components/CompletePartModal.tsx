/**
 * The Complete Part window: ONE place to add everything a landed part still needs - its files
 * (symbol, footprint, 3D model) and its data (datasheet, MPN, manufacturer, value) - instead of a
 * button per asset tile plus a separate DigiKey card plus inline field edits. A single "Complete
 * Part" action on the detail opens it; each requirement is a row that shows a check when satisfied
 * or the exact input to satisfy it when not, and a one-click DigiKey pull fills all three CAD files
 * at once. Applying a row routes to the same seams the detail already uses (attach / edit-field /
 * CAD download), so the record stays the single source of truth and the rows refresh as it does.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { motion } from "motion/react";
import type { PartDetail, Requirement } from "../api/types";
import { useCadSourceQuery } from "../api/queries";
import { useGuidedCapture, type GuidedStatus } from "../lib/useGuidedCapture";
import { useToast } from "../lib/toast";
import { Button } from "./primitives";
import { DownloadIcon } from "./icons";

interface Props {
  detail: PartDetail;
  hasModel: boolean;
  onClose: () => void;
  onAttachSymbol?: (lib: string, name: string) => void;
  onAttachFootprint?: (lib: string, name: string) => void;
  onEditField?: (field: string, value: unknown) => void;
  busy?: boolean;
}

const CheckMark = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={3} strokeLinecap="round" strokeLinejoin="round" className="h-3 w-3">
    <path d="M20 6 9 17l-5-5" />
  </svg>
);

// A soft progress meter that fills as received/needs grows (the "feel-good" fill).
function CaptureMeter({ received, total }: { received: number; total: number }) {
  const pct = total ? Math.round((received / total) * 100) : 0;
  return (
    <div
      className="flex flex-none items-center gap-2 pt-0.5"
      role="progressbar"
      aria-valuenow={received}
      aria-valuemin={0}
      aria-valuemax={total}
      aria-valuetext={`${received} of ${total} files received`}
    >
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-raise2">
        <motion.div
          className="h-full rounded-full bg-ok"
          initial={false}
          animate={{ width: `${pct}%` }}
          transition={{ type: "spring", stiffness: 220, damping: 28 }}
        />
      </div>
      <span className="tnum whitespace-nowrap font-mono text-2xs text-t3">
        {received}/{total}
      </span>
    </div>
  );
}

// The both-format checklist: KiCad and Altium groups, only the needed rows, each
// flipping waiting -> received with a confirming settle.
function CaptureChecklist({
  needs,
  received,
}: {
  needs: Requirement[];
  received: Partial<Record<Requirement, boolean>>;
}) {
  const groups = [
    { name: "KiCad", rows: KICAD_ROWS.filter((r) => needs.includes(r.req)) },
    { name: "Altium", rows: ALTIUM_ROWS.filter((r) => needs.includes(r.req)) },
  ].filter((g) => g.rows.length > 0);
  return (
    <div className="flex flex-col gap-3">
      {groups.map((g) => (
        <div key={g.name}>
          <div className="mb-1.5 text-2xs font-semibold uppercase tracking-wide text-t3">
            {g.name}
          </div>
          <div className="flex flex-col gap-1.5">
            {g.rows.map((r) => (
              <CaptureRow key={r.req} label={r.label} done={!!received[r.req]} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function CaptureRow({ label, done }: { label: string; done: boolean }) {
  return (
    <div className="flex items-center gap-2.5" data-received={done}>
      <motion.span
        className={
          "grid h-4 w-4 flex-none place-items-center rounded-full " +
          (done ? "bg-ok text-white" : "border-[1.5px] border-line2 text-transparent")
        }
        initial={false}
        animate={done ? { scale: [1, 1.28, 1] } : { scale: 1 }}
        transition={{ duration: 0.34, ease: "easeOut" }}
      >
        <CheckMark />
      </motion.span>
      <span className={"flex-1 text-sm " + (done ? "text-t2" : "text-t1")}>{label}</span>
      <span className={"text-xs " + (done ? "font-medium text-ok" : "text-t3")}>
        {done ? "Received" : "Waiting"}
      </span>
    </div>
  );
}

function cadLabel(status: GuidedStatus): string {
  switch (status) {
    case "resolving":
      return "Looking Up...";
    case "window-open":
    case "receiving":
      return "Waiting For Files...";
    case "attaching":
      return "Attaching...";
    case "timed-out":
    case "unavailable":
    case "error":
      return "Try Again";
    default:
      return "Get CAD Files (KiCad + Altium)";
  }
}

// Checklist row layout, per tool. Only the rows a part actually needs render.
const KICAD_ROWS = [
  { req: "kicad_symbol", label: "Symbol" },
  { req: "kicad_footprint", label: "Footprint" },
  { req: "kicad_model", label: "3D Model" },
] as const;
const ALTIUM_ROWS = [
  { req: "altium_symbol", label: "Symbol" },
  { req: "altium_footprint", label: "Footprint" },
] as const;

// Sentence-case toast copy fired as each requirement lands (body prose, not a label).
const REQ_TOAST: Record<Requirement, string> = {
  kicad_symbol: "KiCad symbol received",
  kicad_footprint: "KiCad footprint received",
  kicad_model: "KiCad 3D model received",
  altium_symbol: "Altium symbol received",
  altium_footprint: "Altium footprint received",
};

function pickIngestFiles(): Promise<string[]> | null {
  const hostApi = (
    window as unknown as {
      pywebview?: { api?: { pick_ingest_files?: () => Promise<string[]> } };
    }
  ).pywebview?.api;
  return hostApi?.pick_ingest_files ? hostApi.pick_ingest_files() : null;
}

export function CompletePartModal({
  detail,
  hasModel,
  onClose,
  onAttachSymbol,
  onAttachFootprint,
  onEditField,
  busy,
}: Props) {
  const hasSymbol = !!detail.symbol?.name;
  const hasFootprint = !!detail.footprint?.name;
  const hasDatasheet = !!(detail.datasheet?.source_url || detail.datasheet?.file);

  // The guided capture flow: resolve the part's needs (KiCad + Altium), open the
  // guided window, and fill the checklist as each file lands. The needs come from
  // the cad-source query up front so the checklist renders before start().
  const cadSource = useCadSourceQuery(detail.id, true);
  const cadNeeds = useMemo<Requirement[]>(() => cadSource.data?.needs ?? [], [cadSource.data]);
  const download = useGuidedCapture(detail.id, cadNeeds);
  const { toast } = useToast();
  const needs: Requirement[] = download.needs;
  const receivedCount = needs.filter((n) => download.received[n]).length;
  const showCad = needs.length > 0;
  const cadBusy =
    download.status === "resolving" ||
    download.status === "window-open" ||
    download.status === "receiving" ||
    download.status === "attaching";

  // Feel-good validation: toast each requirement the moment it flips to received.
  const prevReceived = useRef<Partial<Record<Requirement, boolean>>>({});
  useEffect(() => {
    const rec = download.received;
    (Object.keys(rec) as Requirement[]).forEach((req) => {
      if (rec[req] && !prevReceived.current[req]) toast(REQ_TOAST[req], "ok");
    });
    prevReceived.current = { ...rec };
  }, [download.received, toast]);

  async function browse() {
    const picked = pickIngestFiles();
    if (!picked) return;
    const paths = await picked;
    if (paths && paths.length > 0) void download.submitPaths(paths);
  }

  const requirements = useMemo(
    () =>
      [
        { key: "symbol", label: "Symbol", kind: "asset" as const, present: hasSymbol },
        { key: "footprint", label: "Footprint", kind: "asset" as const, present: hasFootprint },
        { key: "model", label: "3D Model", kind: "cad-only" as const, present: hasModel },
        { key: "datasheet", label: "Datasheet", kind: "url" as const, present: hasDatasheet },
        { key: "mpn", label: "Part Number", kind: "text" as const, present: !!detail.mpn },
        { key: "manufacturer", label: "Manufacturer", kind: "text" as const, present: !!detail.manufacturer },
        { key: "description", label: "Value / Description", kind: "text" as const, present: !!detail.description },
      ]
        // The 3D model has no manual attach path (download only), so when the CAD Files
        // section is shown it owns the model row; drop the redundant duplicate here.
        .filter((r) => !(showCad && r.key === "model")),
    [detail, hasSymbol, hasFootprint, hasModel, hasDatasheet, showCad],
  );
  const doneCount = requirements.filter((r) => r.present).length;
  const total = requirements.length;

  return (
    <div
      className="fixed inset-0 z-[95] flex items-start justify-center overflow-y-auto bg-black/55 p-4 pt-[7vh] backdrop-blur-sm"
      role="presentation"
      onClick={onClose}
    >
      <div
        className="w-full max-w-[540px] overflow-hidden rounded-card border border-line2 bg-popover shadow-pop"
        role="dialog"
        aria-modal="true"
        aria-label="Complete this part"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between border-b border-line px-5 py-4">
          <div>
            <div className="text-base font-semibold text-t1">Complete This Part</div>
            <div className="mt-0.5 text-xs text-t3">
              Add the files and data this part still needs.
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span className="tnum whitespace-nowrap font-mono text-xs text-t3">
              {doneCount} / {total}
            </span>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="grid h-7 w-7 place-items-center rounded-control text-t3 hover:bg-raise2 hover:text-t1"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" className="h-3.5 w-3.5">
                <path d="M18 6 6 18M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        <div className="max-h-[68vh] overflow-y-auto px-5 py-4">
          {/* Guided capture: get BOTH the KiCad and the Altium assets in one pass. The
              checklist fills live as each file lands, with a progress meter and per-row
              validation. Shown whenever the part is missing any CAD or Altium asset. */}
          {showCad ? (
            <div className="mb-4 overflow-hidden rounded-control border border-line2 bg-field">
              <div className="flex items-start justify-between gap-3 border-b border-line px-3.5 py-2.5">
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-t1">CAD Files</div>
                  <p
                    className={
                      "mt-0.5 text-xs " +
                      (download.status === "error"
                        ? "text-err"
                        : download.status === "timed-out"
                          ? "text-warn"
                          : "text-t3")
                    }
                  >
                    {download.message ??
                      `Get both the KiCad and Altium assets from ${cadSource.data?.vendor ?? "the vendor"} in one pass.`}
                  </p>
                </div>
                <CaptureMeter received={receivedCount} total={needs.length} />
              </div>
              <div className="px-3.5 py-3">
                <CaptureChecklist needs={needs} received={download.received} />
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  {cadSource.data?.url ? (
                    <Button
                      variant="accent"
                      small
                      icon={<DownloadIcon className="h-3.5 w-3.5" />}
                      disabled={cadBusy}
                      onClick={() => void download.start()}
                    >
                      {cadLabel(download.status)}
                    </Button>
                  ) : null}
                  <Button small disabled={cadBusy} onClick={() => void browse()}>
                    Browse For Files
                  </Button>
                </div>
              </div>
            </div>
          ) : null}

          <div className="flex flex-col divide-y divide-line">
            {requirements.map((req) => (
              <Requirement
                key={req.key}
                req={req}
                busy={busy}
                onAttachSymbol={onAttachSymbol}
                onAttachFootprint={onAttachFootprint}
                onEditField={onEditField}
              />
            ))}
          </div>
        </div>

        <div className="flex justify-end border-t border-line px-5 py-3.5">
          <Button variant="accent" small onClick={onClose}>
            Done
          </Button>
        </div>
      </div>
    </div>
  );
}

type Req = {
  key: string;
  label: string;
  kind: "asset" | "cad-only" | "url" | "text";
  present: boolean;
};

function Requirement({
  req,
  busy,
  onAttachSymbol,
  onAttachFootprint,
  onEditField,
}: {
  req: Req;
  busy?: boolean;
  onAttachSymbol?: (lib: string, name: string) => void;
  onAttachFootprint?: (lib: string, name: string) => void;
  onEditField?: (field: string, value: unknown) => void;
}) {
  const [open, setOpen] = useState(false);
  const [lib, setLib] = useState(req.key === "symbol" ? "Device" : "");
  const [name, setName] = useState("");
  const [text, setText] = useState("");
  const editable = !!(onAttachSymbol || onAttachFootprint || onEditField);

  function applyAsset() {
    if (!lib.trim() || !name.trim()) return;
    if (req.key === "symbol") onAttachSymbol?.(lib.trim(), name.trim());
    else onAttachFootprint?.(lib.trim(), name.trim());
    setOpen(false);
    setName("");
  }
  function applyValue(field: string) {
    if (!text.trim()) return;
    onEditField?.(field, text.trim());
    setOpen(false);
    setText("");
  }

  return (
    <div className="py-2.5">
      <div className="flex items-center gap-2.5">
        <span
          className={
            "grid h-4 w-4 flex-none place-items-center rounded-full " +
            (req.present ? "bg-ok text-white" : "border-[1.5px] border-line2 text-transparent")
          }
        >
          <CheckMark />
        </span>
        <span className={"flex-1 text-sm " + (req.present ? "text-t2" : "font-medium text-t1")}>
          {req.label}
        </span>
        {req.present ? (
          <span className="text-xs text-t3">Added</span>
        ) : req.kind === "cad-only" ? (
          <span className="text-xs text-t3">From the CAD files above</span>
        ) : editable ? (
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-label={open ? undefined : `Add ${req.label}`}
            className="rounded-control border border-line2 px-2.5 py-1 text-xs font-semibold text-t2 hover:border-acc hover:text-t1"
          >
            {open ? "Cancel" : "Add"}
          </button>
        ) : null}
      </div>

      {open && !req.present ? (
        <div className="mt-2.5 pl-6.5">
          {req.kind === "asset" ? (
            <div className="flex flex-wrap items-end gap-2">
              <Field label="Library" value={lib} onChange={setLib} placeholder={req.key === "symbol" ? "Device" : "Resistor_SMD"} />
              <Field label="Name" value={name} onChange={setName} placeholder={req.key === "symbol" ? "R" : "R_0603_1608Metric"} onEnter={applyAsset} />
              <Button small variant="accent" disabled={busy || !lib.trim() || !name.trim()} onClick={applyAsset}>
                Attach
              </Button>
            </div>
          ) : (
            <div className="flex flex-wrap items-end gap-2">
              <Field
                label={req.kind === "url" ? "URL" : req.label}
                value={text}
                onChange={setText}
                placeholder={req.kind === "url" ? "https://..." : ""}
                wide
                onEnter={() => applyValue(req.key)}
              />
              <Button small variant="accent" disabled={busy || !text.trim()} onClick={() => applyValue(req.key)}>
                Save
              </Button>
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  placeholder,
  wide,
  onEnter,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  wide?: boolean;
  onEnter?: () => void;
}) {
  return (
    <label className={"flex flex-col gap-1 " + (wide ? "min-w-[280px] flex-1" : "")}>
      <span className="text-2xs font-medium uppercase tracking-wide text-t3">{label}</span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && onEnter?.()}
        placeholder={placeholder}
        className="h-8 w-full rounded-control border border-line2 bg-field px-2.5 text-sm text-t1 outline-none placeholder:text-t3 focus:border-acc"
      />
    </label>
  );
}
