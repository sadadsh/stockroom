/**
 * The Complete Part window: ONE place to get everything a landed part still needs. It is laid
 * out as two regions - FILES (the guided capture, the hero: get both the KiCad and the Altium
 * assets in one pass, watching a two-track checklist fill) and DETAILS (datasheet, part number,
 * manufacturer, value). The capture runs through the global CaptureProvider store, so "Keep
 * Working" can hand it off to the background status pill and the user can close this and keep
 * moving while the files land. Applying a row routes to the same seams the detail uses (attach /
 * edit-field / guided capture), so the record stays the single source of truth.
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
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={3} strokeLinecap="round" strokeLinejoin="round" className="h-2.5 w-2.5">
    <path d="M20 6 9 17l-5-5" />
  </svg>
);

// A segmented meter: one cell per needed file, filling as each lands. The discrete cells read
// the discrete requirements at a glance (vs one anonymous bar), and settle green on completion.
function SegmentMeter({
  needs,
  received,
  done,
}: {
  needs: Requirement[];
  received: Partial<Record<Requirement, boolean>>;
  done: boolean;
}) {
  const count = needs.filter((n) => received[n]).length;
  return (
    <div
      className="flex flex-none items-center gap-2"
      role="progressbar"
      aria-valuenow={count}
      aria-valuemin={0}
      aria-valuemax={needs.length}
      aria-valuetext={`${count} of ${needs.length} files received`}
    >
      <div className="flex gap-1">
        {needs.map((n) => (
          <motion.span
            key={n}
            className={"h-2 w-5 rounded-full " + (received[n] ? "bg-ok" : "bg-raise2")}
            initial={false}
            animate={received[n] ? { opacity: done ? 1 : 0.92, scaleY: [1, 1.6, 1] } : { opacity: 1, scaleY: 1 }}
            transition={{ duration: 0.3, ease: "easeOut" }}
          />
        ))}
      </div>
      <span className="tnum whitespace-nowrap font-mono text-2xs text-t3">
        {count}/{needs.length}
      </span>
    </div>
  );
}

const KICAD_ROWS = [
  { req: "kicad_symbol", label: "Symbol" },
  { req: "kicad_footprint", label: "Footprint" },
] as const;
// The 3D model is a .step - one file, referenced by BOTH the KiCad and the Altium footprint - so
// it is captured once and lives in its own Shared group, not doubled under each tool.
const SHARED_ROWS = [{ req: "kicad_model", label: "3D Model" }] as const;
const ALTIUM_ROWS = [
  { req: "altium_symbol", label: "Symbol" },
  { req: "altium_footprint", label: "Footprint" },
] as const;

// One EDA tool's group of needed rows, each flipping waiting -> received with a settle. The
// group renders directly in the hero card (a small tool sub-label + a hairline), so a part that
// needs only one tool - the common case in a KiCad-complete library - reads clean and balanced
// rather than as a sparse boxed panel.
function CaptureGroup({
  tool,
  rows,
  received,
  note,
}: {
  tool: string;
  rows: readonly { req: Requirement; label: string }[];
  received: Partial<Record<Requirement, boolean>>;
  note?: string;
}) {
  const done = rows.filter((r) => received[r.req]).length;
  return (
    <div data-track={tool}>
      <div className="mb-1 flex items-center gap-2">
        <span className="text-2xs font-semibold uppercase tracking-[0.14em] text-t3">{tool}</span>
        {note ? <span className="text-2xs text-t3">{note}</span> : null}
        <span className="h-px flex-1 bg-line" />
        <span className="tnum font-mono text-2xs text-t3">
          {done}/{rows.length}
        </span>
      </div>
      <div className="flex flex-col">
        {rows.map((r) => (
          <CaptureRow key={r.req} label={r.label} done={!!received[r.req]} />
        ))}
      </div>
    </div>
  );
}

function CaptureRow({ label, done }: { label: string; done: boolean }) {
  return (
    <div className="flex items-center gap-2.5 py-1" data-received={done}>
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
      <span
        className={
          "rounded-full px-2 py-0.5 text-2xs font-medium " +
          (done ? "bg-ok/15 text-ok" : "bg-raise2 text-t3")
        }
      >
        {done ? "Received" : "Needed"}
      </span>
    </div>
  );
}

// A needs-accurate one-liner: never promise KiCad when only Altium is missing (or vice versa).
function needsSubline(hasKicad: boolean, hasAltium: boolean, vendor: string): string {
  if (hasKicad && hasAltium) return `Get its KiCad and Altium libraries from ${vendor}.`;
  if (hasAltium) return `Get its Altium symbol and footprint from ${vendor}.`;
  return `Get its KiCad symbol, footprint and 3D model from ${vendor}.`;
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
    case "done":
      return "Files Complete";
    case "timed-out":
    case "unavailable":
    case "error":
      return "Try Again";
    default:
      return "Get Files";
  }
}

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

// A quiet section eyebrow that gives FILES and DETAILS a real, legible hierarchy.
function Eyebrow({ children, trailing }: { children: React.ReactNode; trailing?: React.ReactNode }) {
  return (
    <div className="mb-2 flex items-center gap-2.5">
      <span className="text-2xs font-semibold uppercase tracking-[0.14em] text-t3">{children}</span>
      <span className="h-px flex-1 bg-line" />
      {trailing}
    </div>
  );
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

  const cadSource = useCadSourceQuery(detail.id, true);
  const cadNeeds = useMemo<Requirement[]>(() => cadSource.data?.needs ?? [], [cadSource.data]);
  const download = useGuidedCapture(detail.id, cadNeeds, detail.display_name);
  const { toast } = useToast();
  const needs: Requirement[] = download.needs;
  const showCad = needs.length > 0;
  const isDone = download.status === "done";
  const cadBusy =
    download.status === "resolving" ||
    download.status === "window-open" ||
    download.status === "receiving" ||
    download.status === "attaching";
  // "Keep Working" only makes sense while a capture is actually in flight through the host.
  const canBackground = cadBusy;

  // Closing the window while a capture is still in flight must not lose it: hand it to the
  // background pill instead of dropping it. Every close path (backdrop, the X, Done) goes here.
  function handleClose() {
    if (cadBusy) download.keepWorking();
    onClose();
  }

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

  const kicadRows = KICAD_ROWS.filter((r) => needs.includes(r.req));
  const sharedRows = SHARED_ROWS.filter((r) => needs.includes(r.req));
  const altiumRows = ALTIUM_ROWS.filter((r) => needs.includes(r.req));

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
        // When the FILES section is shown it owns the whole asset story (symbol, footprint,
        // and 3D model), so drop those from DETAILS to avoid the same asset word reading
        // "Added" here and "Needed" in FILES at once. DETAILS then stays metadata-only.
      ].filter((r) => !(showCad && (r.key === "model" || r.key === "symbol" || r.key === "footprint"))),
    [detail, hasSymbol, hasFootprint, hasModel, hasDatasheet, showCad],
  );
  const doneCount =
    requirements.filter((r) => r.present).length + needs.filter((n) => download.received[n]).length;
  const total = requirements.length + needs.length;

  const statusTone =
    download.status === "error"
      ? "text-err"
      : download.status === "timed-out"
        ? "text-warn"
        : isDone
          ? "text-ok"
          : "text-t3";

  return (
    <div
      className="fixed inset-0 z-[95] flex items-start justify-center overflow-y-auto bg-black/55 p-4 pt-[7vh] backdrop-blur-sm"
      role="presentation"
      onClick={handleClose}
    >
      <motion.div
        className="w-full max-w-[560px] overflow-hidden rounded-card border border-line2 bg-popover shadow-pop"
        role="dialog"
        aria-modal="true"
        aria-label="Complete this part"
        onClick={(e) => e.stopPropagation()}
        initial={{ opacity: 0, y: 10, scale: 0.985 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.2, ease: "easeOut" }}
      >
        <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
          <div className="min-w-0">
            <div className="truncate text-lg font-semibold leading-tight text-t1">
              {detail.display_name}
            </div>
            <div className="mt-0.5 text-xs text-t3">Add the files and data this part still needs.</div>
          </div>
          <div className="flex flex-none items-center gap-3">
            <span className="tnum whitespace-nowrap font-mono text-xs text-t2">
              {doneCount} / {total}
            </span>
            <button
              type="button"
              onClick={handleClose}
              aria-label="Close"
              className="grid h-7 w-7 place-items-center rounded-control text-t3 hover:bg-raise2 hover:text-t1"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" className="h-3.5 w-3.5">
                <path d="M18 6 6 18M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        <div className="max-h-[70vh] overflow-y-auto px-5 py-4">
          {showCad ? (
            <section className="mb-5">
              <Eyebrow>Files</Eyebrow>
              <div
                className={
                  "rounded-control border p-4 shadow-file transition-colors " +
                  (isDone ? "border-ok/40 bg-ok/[0.07]" : "border-line2 bg-raise")
                }
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 items-start gap-2.5">
                    <span
                      className={
                        "mt-0.5 grid h-7 w-7 flex-none place-items-center rounded-control " +
                        (isDone ? "bg-ok/20 text-ok" : "bg-raise2 text-t1")
                      }
                    >
                      {isDone ? (
                        <CheckMark />
                      ) : (
                        <DownloadIcon className="h-3.5 w-3.5" />
                      )}
                    </span>
                    <div className="min-w-0">
                      <div className="text-sm font-semibold text-t1">
                        {isDone ? "Files Complete" : "Guided Capture"}
                      </div>
                      <div className="mt-0.5 text-2xs leading-snug text-t3">
                        {isDone
                          ? "Every format this part needed is attached."
                          : needsSubline(
                              kicadRows.length > 0 || sharedRows.length > 0,
                              altiumRows.length > 0,
                              cadSource.data?.vendor ?? "DigiKey",
                            )}
                      </div>
                    </div>
                  </div>
                  <SegmentMeter needs={needs} received={download.received} done={isDone} />
                </div>

                <div className="mt-3.5 flex flex-col gap-3">
                  {kicadRows.length > 0 ? (
                    <CaptureGroup tool="KiCad" rows={kicadRows} received={download.received} />
                  ) : null}
                  {sharedRows.length > 0 ? (
                    <CaptureGroup
                      tool="Shared"
                      rows={sharedRows}
                      received={download.received}
                      note="Used by KiCad and Altium"
                    />
                  ) : null}
                  {altiumRows.length > 0 ? (
                    <CaptureGroup tool="Altium" rows={altiumRows} received={download.received} />
                  ) : null}
                </div>

                {download.message ? (
                  <p className={"mt-3 text-xs " + statusTone}>{download.message}</p>
                ) : null}

                <div className="mt-3 flex flex-wrap items-center gap-2">
                  {cadSource.data?.url && !isDone ? (
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
                  {!isDone ? (
                    // When no guided source resolves (no CAD URL), Browse is the ONLY path,
                    // so it becomes the primary; otherwise it stays the quiet manual fallback.
                    <Button
                      small
                      variant={cadSource.data?.url ? undefined : "accent"}
                      disabled={cadBusy}
                      onClick={() => void browse()}
                    >
                      Browse For Files
                    </Button>
                  ) : null}
                  {canBackground ? (
                    <button
                      type="button"
                      onClick={() => {
                        download.keepWorking();
                        onClose();
                      }}
                      className="ml-auto rounded-control px-2.5 py-1 text-xs font-medium text-t2 hover:bg-raise2 hover:text-t1"
                    >
                      Keep Working
                    </button>
                  ) : null}
                </div>
              </div>
            </section>
          ) : null}

          <section>
            <Eyebrow>Details</Eyebrow>
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
          </section>
        </div>

        <div className="flex justify-end border-t border-line px-5 py-3.5">
          <Button variant="accent" small onClick={handleClose}>
            Done
          </Button>
        </div>
      </motion.div>
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
    <div className="py-2">
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
          <span className="text-2xs text-t3">Added</span>
        ) : req.kind === "cad-only" ? (
          <span className="text-2xs text-t3">From the files above</span>
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
