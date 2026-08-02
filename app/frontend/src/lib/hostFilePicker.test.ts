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

  it("fails honestly when no native host owns file selection", async () => {
    await expect(pickHostFiles("cad-recovery")).rejects.toBeInstanceOf(
      HostFilePickerUnavailableError,
    );
  });
});
