import { afterEach, describe, expect, it, vi } from "vitest";
import {
  HostFolderPickerUnavailableError,
  pickHostFolder,
} from "./hostFolderPicker";

function exposeApi(api: object | undefined) {
  Object.defineProperty(window, "pywebview", {
    configurable: true,
    value: api ? { api } : undefined,
  });
}

function exposeManaged(api: object | undefined) {
  Object.defineProperty(window, "__STOCKROOM_HOST__", {
    configurable: true,
    value: api,
  });
}

afterEach(() => {
  exposeApi(undefined);
  exposeManaged(undefined);
});

describe("pickHostFolder", () => {
  it("distinguishes a missing native bridge from a person cancelling", async () => {
    exposeApi(undefined);

    await expect(pickHostFolder("project")).rejects.toBeInstanceOf(
      HostFolderPickerUnavailableError,
    );
  });

  it("returns an empty value only when the person cancels the native dialog", async () => {
    exposeApi({ pick_folder: vi.fn().mockResolvedValue([]) });

    await expect(pickHostFolder("stm-cubemx")).resolves.toBe("");
  });

  it("uses the managed Windows host bridge in packaged releases", async () => {
    const pickFolder = vi.fn().mockResolvedValue(["D:\\Projects\\Controller"]);
    exposeManaged({ pickFolder });

    await expect(pickHostFolder("project")).resolves.toBe("D:\\Projects\\Controller");
    expect(pickFolder).toHaveBeenCalledWith("project");
  });

  it("supports the previous project-only host during a rolling handoff", async () => {
    const legacy = vi.fn().mockResolvedValue(["D:\\Hardware\\Controller"]);
    exposeApi({ pick_project_folder: legacy });

    await expect(pickHostFolder("project")).resolves.toBe("D:\\Hardware\\Controller");
    expect(legacy).toHaveBeenCalledOnce();
  });

  it("does not misuse the project-only bridge for CubeMX", async () => {
    exposeApi({ pick_project_folder: vi.fn().mockResolvedValue(["D:\\STM32CubeMX"]) });

    await expect(pickHostFolder("stm-cubemx")).rejects.toBeInstanceOf(
      HostFolderPickerUnavailableError,
    );
  });
});
