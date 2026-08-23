import { afterEach, describe, expect, it, vi } from "vitest";
import { HostFilePickerUnavailableError, pickHostFiles } from "./hostFilePicker";

afterEach(() => {
  Reflect.deleteProperty(window, "__STOCKROOM_HOST__");
  Reflect.deleteProperty(window, "pywebview");
});

describe("host file picker", () => {
  it("uses the managed native picker for CAD recovery", async () => {
    const pickFiles = vi.fn().mockResolvedValue(["D:\\Downloads\\Part.zip"]);
    Object.defineProperty(window, "__STOCKROOM_HOST__", {
      configurable: true,
      value: { pickFiles },
    });

    await expect(pickHostFiles("cad-recovery")).resolves.toEqual([
      "D:\\Downloads\\Part.zip",
    ]);
    expect(pickFiles).toHaveBeenCalledWith("cad-recovery");
  });

  it("uses the managed native picker for the KiCad CLI", async () => {
    const pickFiles = vi.fn().mockResolvedValue(["C:\\KiCad\\bin\\kicad-cli.exe"]);
    Object.defineProperty(window, "__STOCKROOM_HOST__", {
      configurable: true,
      value: { pickFiles },
    });

    await expect(pickHostFiles("kicad-cli")).resolves.toEqual([
      "C:\\KiCad\\bin\\kicad-cli.exe",
    ]);
    expect(pickFiles).toHaveBeenCalledWith("kicad-cli");
  });

  it("fails honestly when no native host owns file selection", async () => {
    await expect(pickHostFiles("cad-recovery")).rejects.toBeInstanceOf(
      HostFilePickerUnavailableError,
    );
  });
});
