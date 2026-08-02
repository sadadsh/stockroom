export type HostFolderPurpose = "project" | "stm-cubemx";

export async function pickHostFolder(purpose: HostFolderPurpose): Promise<string> {
  const host = (
    window as unknown as {
      pywebview?: { api?: { pick_folder?: (purpose: HostFolderPurpose) => Promise<string[]> } };
    }
  ).pywebview?.api;
  if (!host?.pick_folder) return "";
  const selected = await host.pick_folder(purpose);
  return selected[0] ?? "";
}
