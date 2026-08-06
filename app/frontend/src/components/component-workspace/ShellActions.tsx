/**
 * The three Manage actions that leave the application: export the component's CAD set, open it in
 * an EDA application this machine really has, and reveal its files.
 *
 * This is the ONE place in ordinary use where an EDA application may be named. Everywhere else a
 * component is inspected the assets are Symbol, Footprint and 3D Model, because which tool can
 * read a file is not what the file IS. Here the tool is the entire question - "open this in what"
 * has no answer that is not a product name - and the spec permits it behind exactly these
 * actions.
 *
 * Nothing here is offered speculatively. The host answers which formats this component has files
 * for and which applications are installed, and an item with nothing behind it is not drawn:
 * a menu entry that cannot work is a dead click path, and a disabled one is the same dead path
 * with an explanation nobody asked for. WHICH of the three the host can perform is decided in
 * `manageActions.tsx`, beside the rest of the Manage inventory; these are the two dialogs.
 *
 * `WorkspaceShellDialogs` at the foot of this file is the wired pair: it holds the one token that
 * says which row is running and the two mutations that leave the process. That token means nothing
 * anywhere else in the workspace - it names a format or an application id, and only these two
 * dialogs can read it - so it lives here with the markup that renders it rather than in the
 * workspace's own state. WHICH dialog is open stays with the workspace, because the Manage menu
 * opens it.
 */
import { useState } from "react";
import { useExportPart, useOpenPartIn } from "../../api/queries";
import type { PartShell } from "../../api/types";
import { Text, useText } from "../../lib/copy";
import { useToast } from "../../lib/toast";
import { Button } from "../primitives";
import { EmptyState } from "../productState";
import { UI_PROPERTY_LABEL, UI_ROW_PRIMARY, UI_ROW_METADATA } from "../typography";
import { WorkspaceModal } from "./WorkspaceModal";
import { APPLICATION_FORMAT, openableApplications } from "./manageActions";

/** The formats a component can leave the library in, in presentation order. */
const FORMAT_COPY: Record<string, { copyId: string; label: string; detail: string }> = {
  kicad: {
    copyId: "component-browser.export-format-kicad",
    label: "KiCad Files",
    detail: "Symbol, footprint and 3D model as separate KiCad files.",
  },
  step: {
    copyId: "component-browser.export-format-step",
    label: "3D Model (STEP)",
    detail: "The 3D model on its own, in the format it is held in.",
  },
};

/**
 * Export Component...: pick the format, and say what each one contains before it is written.
 *
 * The formats are the ones the component really has files for. A format it does not have is
 * absent rather than greyed out - the list answers "what can leave this library", and an entry
 * that produces an empty folder is not an answer.
 */
export function ExportComponentDialog({
  open,
  shell,
  pending,
  onExport,
  onClose,
}: {
  open: boolean;
  shell: PartShell | undefined;
  pending: string | null;
  onExport: (format: string) => void;
  onClose: () => void;
}) {
  const title = useText("component-browser.export-title", "Export Component");
  const formats = shell?.export_formats ?? [];
  return (
    <WorkspaceModal open={open} title={title} onClose={onClose}>
      <div className="flex flex-col gap-2">
        <p className={UI_ROW_METADATA}>
          <Text id="component-browser.export-note">
            Exported files are written to a Stockroom folder outside the catalog and are replaced
            each time the same format is exported.
          </Text>
        </p>
        {formats.length === 0 ? (
          <EmptyState id="component-browser.export-none">
            This component has no CAD files to export so far.
          </EmptyState>
        ) : (
          <ul className="flex flex-col">
            {formats.map((format) => {
              const copy = FORMAT_COPY[format];
              if (!copy) return null;
              return (
                <li
                  key={format}
                  className="flex items-center gap-3 border-b border-line/60 py-2 last:border-b-0"
                >
                  <span className="min-w-0 flex-1">
                    <span className={UI_ROW_PRIMARY + " block"}>
                      <Text id={copy.copyId}>{copy.label}</Text>
                    </span>
                    <span className={UI_ROW_METADATA + " block"}>
                      <Text id={copy.copyId + "-detail"}>{copy.detail}</Text>
                    </span>
                  </span>
                  <Button
                    small
                    data-dev-id="component-browser.export-format"
                    disabled={pending !== null}
                    onClick={() => onExport(format)}
                  >
                    {pending === format ? (
                      <Text id="component-browser.export-running">Exporting</Text>
                    ) : (
                      <Text id="component-browser.export-run">Export</Text>
                    )}
                  </Button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </WorkspaceModal>
  );
}

/**
 * Open In...: the applications this machine really carries, and nothing else.
 *
 * Detection is the window host's answer, not a static list, so an application that was never
 * installed is never named and an application that was uninstalled stops being named.
 */
export function OpenInDialog({
  open,
  shell,
  pending,
  onOpen,
  onClose,
}: {
  open: boolean;
  shell: PartShell | undefined;
  pending: string | null;
  onOpen: (applicationId: string, format: string) => void;
  onClose: () => void;
}) {
  const title = useText("component-browser.open-in-title", "Open In");
  const applications = shell ? openableApplications(shell) : [];
  return (
    <WorkspaceModal open={open} title={title} onClose={onClose}>
      <div className="flex flex-col gap-2">
        <p className={UI_ROW_METADATA}>
          <Text id="component-browser.open-in-note">
            Stockroom exports this component first, then opens the exported files. The catalog
            itself is not modified.
          </Text>
        </p>
        {applications.length === 0 ? (
          <EmptyState id="component-browser.open-in-none">
            No application that can open this component is installed on this machine.
          </EmptyState>
        ) : (
          <ul className="flex flex-col">
            {applications.map((application) => (
              <li
                key={application.id}
                className="flex items-center gap-3 border-b border-line/60 py-2 last:border-b-0"
              >
                <span className="min-w-0 flex-1">
                  {/* The application's own name, exactly as this machine reports it. */}
                  <span className={UI_ROW_PRIMARY + " block"}>{application.name}</span>
                  {application.version ? (
                    <span className={UI_PROPERTY_LABEL + " block"}>{application.version}</span>
                  ) : null}
                </span>
                <Button
                  small
                  data-dev-id="component-browser.open-in-application"
                  disabled={pending !== null}
                  onClick={() =>
                    onOpen(application.id, APPLICATION_FORMAT[application.id] ?? "kicad")
                  }
                >
                  {pending === application.id ? (
                    <Text id="component-browser.open-in-running">Opening</Text>
                  ) : (
                    <Text id="component-browser.open-in-run">Open</Text>
                  )}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </WorkspaceModal>
  );
}

/** Which of the two shell dialogs is raised. `null` is the reading state. */
export type ShellDialog = "export" | "open-in" | null;

/**
 * The two dialogs above, wired to the host.
 *
 * One pending token serves both because only one of them is ever open, and it is the id of the row
 * that is running - a format for Export, an application for Open In - so every other row disables
 * itself while the process is out. It is state that no other part of the workspace can use or
 * observe, which is why it is held here rather than passed down.
 *
 * A failure is reported through the workspace's own `onFailure`, so a shell error reads exactly
 * like every other write failure in this component: the API's message when there is one, the
 * supplied fallback when there is not.
 */
export function WorkspaceShellDialogs({
  componentId,
  shell,
  open,
  onClose,
  onFailure,
}: {
  componentId: string;
  shell: PartShell | undefined;
  open: ShellDialog;
  onClose: () => void;
  onFailure: (error: unknown, fallback: string) => void;
}) {
  const exportPart = useExportPart();
  const openPartIn = useOpenPartIn();
  const { toast } = useToast();
  const [pending, setPending] = useState<string | null>(null);
  const exportedLabel = useText("component-browser.exported", "Component exported");
  const exportFailed = useText("component-browser.export-failed", "Could not export");
  const openFailed = useText("component-browser.open-in-failed", "Could not open");

  return (
    <>
      <ExportComponentDialog
        open={open === "export"}
        shell={shell}
        pending={pending}
        onClose={onClose}
        onExport={(format) => {
          setPending(format);
          exportPart.mutate(
            { partId: componentId, format },
            {
              onSuccess: (result) => {
                setPending(null);
                onClose();
                toast(`${exportedLabel} (${result.file_count})`, "ok");
              },
              onError: (error) => {
                setPending(null);
                onFailure(error, exportFailed);
              },
            },
          );
        }}
      />

      <OpenInDialog
        open={open === "open-in"}
        shell={shell}
        pending={pending}
        onClose={onClose}
        onOpen={(applicationId, format) => {
          setPending(applicationId);
          openPartIn.mutate(
            { partId: componentId, applicationId, format },
            {
              onSuccess: () => {
                setPending(null);
                onClose();
              },
              onError: (error) => {
                setPending(null);
                onFailure(error, openFailed);
              },
            },
          );
        }}
      />
    </>
  );
}
