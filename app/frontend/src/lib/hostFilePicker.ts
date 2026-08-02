export type HostFilePurpose = "cad-recovery";

type LegacyHostApi = {
  pick_files?: (purpose: HostFilePurpose) => Promise<string[]>;
};

type ManagedHostApi = {
  pickFiles?: (purpose: HostFilePurpose) => Promise<string[]>;
};

export class HostFilePickerUnavailableError extends Error {
  constructor() {
    super("The Stockroom window needs to finish updating before it can choose files.");
    this.name = "HostFilePickerUnavailableError";
  }
}

export async function pickHostFiles(purpose: HostFilePurpose): Promise<string[]> {
  const bridges = window as unknown as {
    __STOCKROOM_HOST__?: ManagedHostApi;
    pywebview?: { api?: LegacyHostApi };
  };
  const managedPicker = bridges.__STOCKROOM_HOST__?.pickFiles;
  if (managedPicker) return managedPicker(purpose);
  const legacyPicker = bridges.pywebview?.api?.pick_files;
  if (legacyPicker) return legacyPicker(purpose);
  throw new HostFilePickerUnavailableError();
}
