/**
 * The Complete Part window: ONE place to add everything a landed part still needs - its files
 * (symbol, footprint, 3D model) and its data (datasheet, MPN, manufacturer, value) - instead of a
 * button per asset tile plus a separate DigiKey card plus inline field edits. A single "Complete
 * Part" action on the detail opens it; each requirement is a row that shows a check when satisfied
 * or the exact input to satisfy it when not, and a one-click DigiKey pull fills all three CAD files
 * at once. Applying a row routes to the same seams the detail already uses (attach / edit-field /
 * CAD download), so the record stays the single source of truth and the rows refresh as it does.
 */
import { useMemo, useState } from "react";
import type { PartDetail } from "../api/types";
import { useCadSourceQuery } from "../api/queries";
import { useCadDownload, type CadDownloadStatus } from "../lib/useCadDownload";
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

function cadLabel(status: CadDownloadStatus): string {
  switch (status) {
    case "waiting":
      return "Waiting for the Download...";
    case "inspecting":
      return "Inspecting...";
    case "committing":
      return "Attaching...";
    case "unavailable":
    case "error":
      return "Try Again";
    default:
      return "Get Files From DigiKey";
  }
}

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
  const anyCadMissing = !hasSymbol || !hasFootprint || !hasModel;

  const cadSource = useCadSourceQuery(detail.id, anyCadMissing);
  const download = useCadDownload(detail.id);
  const cadBusy =
    download.status === "waiting" ||
    download.status === "inspecting" ||
    download.status === "committing";

  async function browse() {
    const picked = pickIngestFiles();
    if (!picked) return;
    const paths = await picked;
    if (paths && paths.length > 0) void download.submitPaths(paths);
  }

  const requirements = useMemo(
    () => [
      { key: "symbol", label: "Symbol", kind: "asset" as const, present: hasSymbol },
      { key: "footprint", label: "Footprint", kind: "asset" as const, present: hasFootprint },
      { key: "model", label: "3D Model", kind: "cad-only" as const, present: hasModel },
      { key: "datasheet", label: "Datasheet", kind: "url" as const, present: hasDatasheet },
      { key: "mpn", label: "Part Number", kind: "text" as const, present: !!detail.mpn },
      { key: "manufacturer", label: "Manufacturer", kind: "text" as const, present: !!detail.manufacturer },
      { key: "description", label: "Value / Description", kind: "text" as const, present: !!detail.description },
    ],
    [detail, hasSymbol, hasFootprint, hasModel, hasDatasheet],
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
          {/* CAD files (symbol / footprint / 3D model) in one step: pull all three from DigiKey
              when a source resolves for the MPN, and always allow dropping a vendor ZIP. Shown
              whenever any CAD asset is still missing. */}
          {anyCadMissing ? (
            <div className="mb-4 rounded-control border border-line2 bg-field p-3.5">
              <div className="text-sm font-semibold text-t1">Add CAD files</div>
              <p className={"mt-1 text-xs " + (download.status === "error" ? "text-err" : "text-t3")}>
                {download.message ??
                  "Pull the symbol, footprint, and 3D model from DigiKey, or drop a vendor ZIP (SnapEDA, Ultra Librarian)."}
              </p>
              <div className="mt-2.5 flex flex-wrap items-center gap-2">
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
                  Browse for ZIP
                </Button>
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
          <span className="text-xs text-t3">From DigiKey or a ZIP</span>
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
