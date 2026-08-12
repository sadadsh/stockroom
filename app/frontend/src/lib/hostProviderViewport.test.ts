import { installPreviewEffectGuard } from "../design-studio/previewEffects";
import { sendProviderCommand, setProviderViewport } from "./hostProviderViewport";

describe("provider viewport bridge", () => {
  afterEach(() => Reflect.deleteProperty(window, "__STOCKROOM_HOST__"));

  it("sends the exact component and physical browser bounds to the managed host", () => {
    const update = vi.fn();
    Object.defineProperty(window, "__STOCKROOM_HOST__", {
      configurable: true,
      value: { setProviderViewport: update },
    });

    setProviderViewport({
      componentId: "part-1",
      visible: true,
      x: 280,
      y: 76,
      width: 900,
      height: 620,
    });

    expect(update).toHaveBeenCalledWith({
      componentId: "part-1",
      visible: true,
      x: 280,
      y: 76,
      width: 900,
      height: 620,
    });
  });

  it("does not move a real provider surface from a fixture preview", () => {
    const update = vi.fn();
    Object.defineProperty(window, "__STOCKROOM_HOST__", {
      configurable: true,
      value: { setProviderViewport: update },
    });
    const restore = installPreviewEffectGuard("components.full-data");
    try {
      expect(() =>
        setProviderViewport({
          componentId: "part-1",
          visible: true,
          x: 0,
          y: 0,
          width: 800,
          height: 600,
        }),
      ).toThrow("Return to Real Data to place the provider browser");
    } finally {
      restore();
    }
    expect(update).not.toHaveBeenCalled();
  });

  it("sends browser navigation through the same component-bound host bridge", () => {
    const command = vi.fn();
    Object.defineProperty(window, "__STOCKROOM_HOST__", {
      configurable: true,
      value: { providerCommand: command },
    });

    sendProviderCommand("part-1", "reload");

    expect(command).toHaveBeenCalledWith({ componentId: "part-1", command: "reload" });
  });
});
