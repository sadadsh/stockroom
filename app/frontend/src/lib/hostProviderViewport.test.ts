import { installPreviewEffectGuard } from "../design-studio/previewEffects";
import {
  onProviderCloseRequest,
  sendProviderCommand,
  setProviderViewport,
  type ProviderBrowserIdentity,
} from "./hostProviderViewport";

const identity: ProviderBrowserIdentity = {
  componentId: "part-1",
  providerId: "mouser",
  routeId: "mouser",
  sessionId: "session-1",
};

describe("provider viewport bridge", () => {
  afterEach(() => Reflect.deleteProperty(window, "__STOCKROOM_HOST__"));

  it("sends the exact component and physical browser bounds to the managed host", () => {
    const update = vi.fn();
    Object.defineProperty(window, "__STOCKROOM_HOST__", {
      configurable: true,
      value: { setProviderViewport: update },
    });

    setProviderViewport({
      ...identity,
      visible: true,
      x: 280,
      y: 76,
      width: 900,
      height: 620,
    });

    expect(update).toHaveBeenCalledWith({
      ...identity,
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
          ...identity,
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

  it("returns the native outcome for browser commands", async () => {
    const command = vi.fn().mockResolvedValue(true);
    Object.defineProperty(window, "__STOCKROOM_HOST__", {
      configurable: true,
      value: { providerCommand: command },
    });

    await expect(sendProviderCommand(identity, "reload")).resolves.toEqual({
      accepted: true,
      error: "",
    });

    expect(command).toHaveBeenCalledWith({ ...identity, command: "reload" });
  });

  it("sends an exact address through the component-bound host bridge", async () => {
    const command = vi.fn().mockResolvedValue(true);
    Object.defineProperty(window, "__STOCKROOM_HOST__", {
      configurable: true,
      value: { providerCommand: command },
    });

    await sendProviderCommand(identity, "navigate", "https://www.mouser.com/c/?q=LM358");

    expect(command).toHaveBeenCalledWith({
      ...identity,
      command: "navigate",
      url: "https://www.mouser.com/c/?q=LM358",
    });
  });

  it("reports a refused or missing native command instead of claiming dispatch", async () => {
    Object.defineProperty(window, "__STOCKROOM_HOST__", {
      configurable: true,
      value: { providerCommand: vi.fn().mockResolvedValue(false) },
    });

    await expect(sendProviderCommand(identity, "back")).resolves.toEqual({
      accepted: false,
      error: "The embedded provider browser refused Back.",
    });

    Reflect.deleteProperty(window, "__STOCKROOM_HOST__");
    await expect(sendProviderCommand(identity, "reload")).resolves.toEqual({
      accepted: false,
      error: "The embedded provider browser is unavailable in this host.",
    });
  });

  it("delivers a native Escape close request only to its exact provider session", () => {
    const close = vi.fn();
    const unsubscribe = onProviderCloseRequest(identity, close);
    window.dispatchEvent(new CustomEvent("stockroom:provider-close-requested", {
      detail: { ...identity, sessionId: "stale-session" },
    }));
    window.dispatchEvent(new CustomEvent("stockroom:provider-close-requested", {
      detail: identity,
    }));

    expect(close).toHaveBeenCalledTimes(1);
    unsubscribe();
  });
});
