import { api } from "../api/client";
import { downloadBlob } from "../lib/download";
import { openExternalUrl } from "../lib/externalNavigation";
import { pickHostFiles } from "../lib/hostFilePicker";
import { pickHostFolder } from "../lib/hostFolderPicker";
import {
  PreviewEffectError,
  installPreviewEffectGuard,
} from "./previewEffects";

function exposeHost(api: object) {
  Object.defineProperty(window, "__STOCKROOM_HOST__", {
    configurable: true,
    value: api,
  });
}

describe("fixture preview effects", () => {
  afterEach(() => {
    Reflect.deleteProperty(window, "__STOCKROOM_HOST__");
    Reflect.deleteProperty(window, "pywebview");
    vi.unstubAllGlobals();
  });

  it("blocks managed and legacy native pickers before invoking either bridge", async () => {
    const pickFolder = vi.fn().mockResolvedValue(["D:\\Projects\\Controller"]);
    const pickFiles = vi.fn().mockResolvedValue(["D:\\Downloads\\Part.zip"]);
    const legacyFolder = vi.fn().mockResolvedValue(["D:\\Legacy"]);
    exposeHost({ pickFolder, pickFiles });
    Object.defineProperty(window, "pywebview", {
      configurable: true,
      value: { api: { pick_folder: legacyFolder } },
    });
    const restore = installPreviewEffectGuard("settings.pickers");

    try {
      await expect(pickHostFolder("project")).rejects.toThrow(
        "Return to Real Data to choose a project folder",
      );
      await expect(pickHostFiles("cad-recovery")).rejects.toThrow(
        "Return to Real Data to choose CAD recovery files",
      );
    } finally {
      restore();
    }

    expect(pickFolder).not.toHaveBeenCalled();
    expect(pickFiles).not.toHaveBeenCalled();
    expect(legacyFolder).not.toHaveBeenCalled();
  });

  it("blocks external navigation and downloads before invoking window or anchor controls", () => {
    const open = vi.fn();
    vi.stubGlobal("open", open);
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click");
    const restore = installPreviewEffectGuard("components.full-data");

    try {
      expect(() => openExternalUrl("https://example.test/datasheet.pdf")).toThrow(
        PreviewEffectError,
      );
      expect(() => downloadBlob("bom.csv", new Blob(["part"]))).toThrow(
        PreviewEffectError,
      );
    } finally {
      restore();
      click.mockRestore();
    }

    expect(open).not.toHaveBeenCalled();
    expect(click).not.toHaveBeenCalled();
  });

  it("blocks provider, updater, EDA, and source API effects before fetch", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const restore = installPreviewEffectGuard("global.update.available");

    try {
      for (const invoke of [
        () => api.showCaptureProvider("batch-fixture"),
        () => api.applyUpdate(),
        () => api.openPartIn({ partId: "LM358DR", applicationId: "kicad", format: "symbol" }),
        () => api.devSave({ tokens: { root: {}, light: {} }, copy: {}, icons: {}, elements: {}, behaviors: {}, layout: { workspace: null } }),
        () => api.devPublish("Promote fixture"),
        () => api.devPromote({ message: "Promote fixture", source: { tokens: { root: {}, light: {} }, copy: {}, icons: {}, elements: {}, behaviors: {}, layout: { workspace: null } }, translations: { base: { dark: { tokens: { root: {}, light: {} }, copy: {}, icons: {}, elements: {}, behaviors: {}, layout: { workspace: null } }, light: { tokens: { root: {}, light: {} }, copy: {}, icons: {}, elements: {}, behaviors: {}, layout: { workspace: null } } }, variations: {} } }),
      ]) {
        await expect(invoke()).rejects.toBeInstanceOf(PreviewEffectError);
      }
    } finally {
      restore();
    }

    expect(fetch).not.toHaveBeenCalled();
  });

  it("allows personal autosave as the sole preview write", async () => {
    const response = {
      ok: true,
      status: 200,
      json: async () => ({ revision: "r2", document: { schemaVersion: 1 } }),
    };
    const fetch = vi.fn().mockResolvedValue(response);
    vi.stubGlobal("fetch", fetch);
    const restore = installPreviewEffectGuard("components.full-data");

    try {
      await api.designStudioPut({
        document: { schemaVersion: 1 } as never,
        expected_revision: "r1",
      });
    } finally {
      restore();
    }

    expect(fetch).toHaveBeenCalledOnce();
  });
});
