/**
 * The INVENTORY behind the Manage menu: what the menu offers, in what order, and which of those
 * entries this machine can actually perform.
 *
 * The menu itself is a popover with focus handling and a keyboard contract; what it lists is a
 * decision about the product. Keeping the two apart means the order can be read, argued with and
 * tested without rendering anything, and it means `ManageMenu.tsx` and `ShellActions.tsx` each
 * export nothing but the surfaces they draw.
 *
 * A `.tsx` file with no JSX in it, on purpose. Every label here is paired with its copy id and is
 * resolved through `<Text id={item.copyId}>{item.label}</Text>` at the render site, and the copy
 * gates next door read that pairing out of `.tsx` sources only. Moving these labels into a `.ts`
 * would take seven menu entries out of the letter rule's reach without changing a word of them.
 */
import type { EdaApplication, PartShell } from "../../api/types";
import type { ManageMenuItem } from "./ManageMenu";

/**
 * The canonical order. Identity first (what the component IS), then the data (what it claims), then
 * the assets, then where the claims came from, then - alone, after a rule - removal.
 *
 * An ellipsis means another surface follows. `Refresh Component Data` has none because it happens
 * where you stand.
 */
export function manageMenuItems(actions: {
  onEditIdentity: () => void;
  onEditClassification: () => void;
  onReviewMissing: () => void;
  onRefresh: () => void;
  refreshing: boolean;
  onViewProvenance: () => void;
  onDelete: () => void;
  /**
   * Export Component... / Open In... / Reveal Component Files..., when this host can perform
   * them. They arrive as a list rather than as three more callbacks because whether each one
   * EXISTS is decided by the machine (is there a native window, is anything installed, does this
   * component have files) and that decision belongs with the surface that asked, not here.
   */
  shellItems?: ManageMenuItem[];
}): ManageMenuItem[] {
  return [
    {
      id: "edit-identity",
      copyId: "component-browser.manage-edit-identity",
      label: "Edit Identification...",
      run: actions.onEditIdentity,
    },
    {
      id: "edit-classification",
      copyId: "component-browser.manage-edit-classification",
      label: "Edit Class and Classification...",
      run: actions.onEditClassification,
    },
    {
      id: "review-missing",
      copyId: "component-browser.manage-review-missing",
      label: "Review Missing Specifications...",
      run: actions.onReviewMissing,
    },
    {
      id: "refresh",
      copyId: "component-browser.manage-refresh",
      label: "Refresh Component Data",
      disabled: actions.refreshing,
      run: actions.onRefresh,
    },
    {
      id: "view-provenance",
      copyId: "component-browser.manage-provenance",
      label: "View Data Provenance...",
      run: actions.onViewProvenance,
    },
    ...(actions.shellItems ?? []),
    {
      id: "delete",
      copyId: "component-browser.manage-delete",
      label: "Delete Component...",
      destructive: true,
      separated: true,
      run: actions.onDelete,
    },
  ];
}

/** The formats an application is offered for. An application it cannot read is not offered. */
export const APPLICATION_FORMAT: Record<string, string> = {
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
