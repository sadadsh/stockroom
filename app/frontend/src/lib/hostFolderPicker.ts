import { guardPreviewEffect } from "../design-studio/previewEffects";

export type HostFolderPurpose = "project" | "stm-cubemx" | "kicad-config";

type HostFolderApi = {
  pick_folder?: (purpose: HostFolderPurpose) => Promise<string[]>;
  pick_project_folder?: () => Promise<string[]>;
};

type ManagedHostApi = {
  pickFolder?: (purpose: HostFolderPurpose) => Promise<string[]>;
};

export class HostFolderPickerUnavailableError extends Error {
  constructor() {
    super("The Stockroom window needs to finish updating before it can choose folders.");
    this.name = "HostFolderPickerUnavailableError";
  }
}

export async function pickHostFolder(purpose: HostFolderPurpose): Promise<string> {
  const label = purpose === "project" ? "project" : purpose === "stm-cubemx" ? "CubeMX" : "KiCad config";
  guardPreviewEffect({
    kind: "host-folder-picker",
    action: `choosing a ${label} folder`,
    instruction: `choose a ${label} folder`,
  });
  const bridges = window as unknown as {
    __STOCKROOM_HOST__?: ManagedHostApi;
    pywebview?: { api?: HostFolderApi };
  };
  const managedPicker = bridges.__STOCKROOM_HOST__?.pickFolder;
  if (managedPicker) {
    const selected = await managedPicker(purpose);
    return selected[0] ?? "";
  }
  const host = (
    window as unknown as {
      pywebview?: { api?: HostFolderApi };
    }
  ).pywebview?.api;
  if (!host) throw new HostFolderPickerUnavailableError();
  const picker = host.pick_folder
    ? () => host.pick_folder!(purpose)
    : purpose === "project" && host.pick_project_folder
      ? () => host.pick_project_folder!()
      : null;
  if (!picker) throw new HostFolderPickerUnavailableError();
  const selected = await picker();
  return selected[0] ?? "";
}
