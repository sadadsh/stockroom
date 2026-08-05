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
 * with an explanation nobody asked for.
 */
import type { EdaApplication, PartShell } from "../../api/types";
import { Text, useText } from "../../lib/copy";
import { Button } from "../primitives";
import { EmptyState } from "../productState";
import { UI_PROPERTY_LABEL, UI_ROW_PRIMARY, UI_ROW_METADATA } from "../typography";
import { WorkspaceModal } from "./WorkspaceModal";
import type { ManageMenuItem } from "./ManageMenu";

/** The formats a component can leave the library in, in presentation order. */
const FORMAT_COPY: Record<string, { copyId: string; label: string; detail: string }> = {
  kicad: {
    copyId: "component-browser.export-format-kicad",
    label: "KiCad Library Files",
    detail: "Symbol, footprint and 3D model as separate KiCad files.",
  },
  step: {
    copyId: "component-browser.export-format-step",
    label: "3D Model (STEP)",
    detail: "The 3D model on its own, in the format it is held in.",
  },
};

/** The formats an application is offered for. An application it cannot read is not offered. */
const APPLICATION_FORMAT: Record<string, string> = {
  kicad: "kicad",
  "altium-designer": "step",
};

export function shellManageItems(
  shell: PartShell | undefined,
  actions: {
    onExport: () => void;
    onOpenIn: () => void;
    onReveal: () => void;
  },
): ManageMenuItem[] {
  if (!shell?.supported) return [];
  const items: ManageMenuItem[] = [];
  if (shell.export_formats.length > 0) {
    items.push({
      id: "export",
      copyId: "component-browser.manage-export",
      label: "Export Component...",
      run: actions.onExport,
    });
  }
  if (openableApplications(shell).length > 0) {
    items.push({
      id: "open-in",
      copyId: "component-browser.manage-open-in",
      label: "Open In...",
      run: actions.onOpenIn,
    });
  }
  if (shell.component_directory) {
    items.push({
      id: "reveal",
      copyId: "component-browser.manage-reveal",
      label: "Reveal Component Files...",
      run: actions.onReveal,
    });
  }
  return items;
}

/** Installed applications this component actually has a format for. */
export function openableApplications(shell: PartShell): EdaApplication[] {
  return shell.eda_applications.filter((application) => {
    const format = APPLICATION_FORMAT[application.id];
    return !!format && shell.export_formats.includes(format);
  });
}

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
            Exported files are written to a Stockroom folder outside the library and are replaced
            each time you export the same format.
          </Text>
        </p>
        {formats.length === 0 ? (
          <EmptyState id="component-browser.export-none">
            This component has no CAD files to export yet.
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
            Stockroom exports this component first, then opens the exported files. The library
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
