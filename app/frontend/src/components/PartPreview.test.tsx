import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { ApiError, api, type LandPattern } from "../api/client";
import { ThemeProvider } from "../lib/theme";
import { ModelViewer } from "./ModelViewer";
import { Glb3DView } from "./Glb3DView";
import { PreviewImage } from "./PreviewImage";
import { PreviewModal } from "./PreviewModal";
import { SvgViewport } from "./SvgViewport";

// The previews are the only api calls these components make; mock them directly.
vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return {
    ...actual,
    api: { ...actual.api, previewSvg: vi.fn(), modelGlb: vi.fn() },
  };
});

// The three.js half is verified in the Windows pixel gate, not jsdom (no WebGL); mock
// it so the component's mount/error wiring is exercised without a GL context. The mock
// keeps the (container, glb, onError) signature so a test can fire the async parse error.
// mountModelScene returns a HANDLE ({dispose, setView}), not a bare dispose function: the viewer
// needs a channel to move the camera to a canonical view. The mock mirrors that shape, or the
// component's cleanup calls handle.dispose on a plain function and every 3D test dies on unmount.
function sceneHandle() {
  return {
    dispose: vi.fn(),
    fit: vi.fn(),
    setView: vi.fn(),
    setSpin: vi.fn((wanted: boolean) => wanted),
    setLandPattern: vi.fn(),
    setRenderMode: vi.fn(),
    setLayers: vi.fn(),
    setPlacementMode: vi.fn(),
    modelInfo: vi.fn(() => null),
  };
}

const mountSpy = vi.fn(
  (
    _container: HTMLElement,
    _glb: ArrayBuffer,
    _options?: { onError?: () => void; onReady?: () => void },
  ) => sceneHandle(),
);
vi.mock("../lib/threeScene", () => ({
  mountModelScene: (
    c: HTMLElement,
    g: ArrayBuffer,
    options?: { onError?: () => void; onReady?: () => void },
  ) => mountSpy(c, g, options),
}));

const mockApi = vi.mocked(api);

function svgBlob(): Blob {
  return new Blob(["<svg><rect/></svg>"], { type: "image/svg+xml" });
}

// Sensible defaults (restoreMocks resets to bare fns each test); individual tests
// override to exercise the error paths.
beforeEach(() => {
  mockApi.previewSvg.mockResolvedValue(svgBlob());
  mockApi.modelGlb.mockResolvedValue(
    new Uint8Array([0x67, 0x6c, 0x54, 0x46]).buffer,
  );
});

function wrap(ui: ReactNode) {
  // retryDelay:0 keeps the preview query's retry:2 (a real cold-render recovery) instant
  // in tests, so the fallback-on-error path still settles fast.
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, retryDelay: 0 } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>{ui}</ThemeProvider>
    </QueryClientProvider>,
  );
}

describe("PreviewImage", () => {
  it("renders the live SVG thumbnail once the blob loads", async () => {
    mockApi.previewSvg.mockResolvedValue(svgBlob());
    wrap(
      <PreviewImage kind="symbol" partId="lm358" fallback={<span>ART</span>} />,
    );
    expect(await screen.findByAltText("symbol preview")).toBeInTheDocument();
    // no rev for the current-tree thumbnail (the ?rev historical render is M6k)
    expect(mockApi.previewSvg).toHaveBeenCalledWith("symbol", "lm358", undefined);
  });

  it("falls back to the art glyph when the render is unavailable", async () => {
    mockApi.previewSvg.mockRejectedValue(new ApiError(404, "no symbol"));
    wrap(
      <PreviewImage kind="footprint" partId="x" fallback={<span>ART-FALLBACK</span>} />,
    );
    expect(await screen.findByText("ART-FALLBACK")).toBeInTheDocument();
  });

  // The tile is the ONE preview that used to tint with an unconditional `invert(0.66)` while its
  // three siblings (StockAssetPreview, SvgViewport, SvgDiffViewport) all switched on the theme.
  // Measured on the owner's real Windows window 2026-07-25: black line-art became rgb(162) which
  // is 2.34:1 against the light card - under the 3:1 floor for non-text (WCAG 1.4.11) - while the
  // SAME asset in the modal measured 14.87:1. A 6.3x spread on one asset, and the constant's own
  // comment claimed it worked "on both themes". These two tests pin the tile to its siblings so
  // one theme can never be tuned at the other's expense again.
  it("inverts the monochrome art for the dark theme, matching the modal", async () => {
    wrap(<PreviewImage kind="symbol" partId="lm358" fallback={<span>ART</span>} />);
    const img = (await screen.findByAltText("symbol preview")) as HTMLImageElement;
    // dark is the default theme
    expect(img.style.filter).toBe("invert(1)");
  });

  it("leaves the art un-inverted on the light theme, so black line-art stays black", async () => {
    // Set the HOST-INJECTED pref, not the localStorage mirror: injection is the real source of
    // truth (uiPrefs.ts) and the mirror leaks between tests in one jsdom instance.
    window.__STOCKROOM_UI__ = { theme: "light" };
    try {
      wrap(<PreviewImage kind="footprint" partId="lm358" fallback={<span>ART</span>} />);
      const img = (await screen.findByAltText("footprint preview")) as HTMLImageElement;
      // The bug: `invert(0.66)` turned black strokes into a mid grey that vanished on a light card.
      expect(img.style.filter).toBe("none");
    } finally {
      delete window.__STOCKROOM_UI__;
    }
  });
});

describe("SvgViewport", () => {
  it("renders the SVG and offers Reset View, tinted for the dark theme", async () => {
    wrap(<SvgViewport blob={svgBlob()} alt="symbol preview" />);
    const img = (await screen.findByAltText("symbol preview")) as HTMLImageElement;
    // dark is the default theme, so the monochrome art is inverted to near-white ink
    expect(img.style.filter).toBe("invert(1)");
    expect(screen.getByRole("button", { name: "Reset View" })).toBeInTheDocument();
    expect(screen.getByLabelText("Zoom level")).toHaveTextContent("100%");
  });

  it("supports explicit zoom controls and keyboard fit", async () => {
    wrap(<SvgViewport blob={svgBlob()} alt="symbol preview" />);
    await userEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(screen.getByLabelText("Zoom level")).toHaveTextContent("125%");
    const canvas = screen.getByRole("application", { name: /symbol preview inspection canvas/i });
    canvas.focus();
    await userEvent.keyboard("0");
    expect(screen.getByLabelText("Zoom level")).toHaveTextContent("100%");
  });

  it("recenters the view when Reset View is pressed after a pan", async () => {
    wrap(<SvgViewport blob={svgBlob()} alt="symbol preview" />);
    const img = (await screen.findByAltText("symbol preview")) as HTMLImageElement;
    const frame = screen.getByTestId("svg-viewport");
    // a pointer drag pans the image (the transform gains a translate)
    frame.dispatchEvent(
      new MouseEvent("pointerdown", { clientX: 10, clientY: 10, bubbles: true }),
    );
    frame.dispatchEvent(
      new MouseEvent("pointermove", { clientX: 60, clientY: 40, bubbles: true }),
    );
    frame.dispatchEvent(new MouseEvent("pointerup", { bubbles: true }));
    await waitFor(() => expect(img.style.transform).not.toBe("translate(0px, 0px) scale(1)"));
    await userEvent.click(screen.getByRole("button", { name: "Reset View" }));
    expect(img.style.transform).toBe("translate(0px, 0px) scale(1)");
  });
});

describe("ModelViewer", () => {
  it("shows the backend's honest reason when 3D conversion tooling is absent (502)", async () => {
    mockApi.modelGlb.mockRejectedValue(
      new ApiError(502, "3D preview needs the 'trimesh' package; install it"),
    );
    wrap(<ModelViewer partId="tps62130" />);
    expect(await screen.findByText(/needs the 'trimesh' package/i)).toBeInTheDocument();
  });

  it("shows a generic honest message on any other load error", async () => {
    mockApi.modelGlb.mockRejectedValue(new ApiError(0, "offline"));
    wrap(<ModelViewer partId="tps62130" />);
    expect(await screen.findByText(/could not load the 3d model/i)).toBeInTheDocument();
  });

  it("mounts the three.js scene with the fetched GLB bytes", async () => {
    const buf = new Uint8Array([0x67, 0x6c, 0x54, 0x46]).buffer;
    mockApi.modelGlb.mockResolvedValue(buf);
    wrap(<ModelViewer partId="tps62130" />);
    await waitFor(() => expect(mountSpy).toHaveBeenCalled());
    expect(mountSpy.mock.calls[0][1]).toBe(buf);
  });

  it("shows an honest message (not a blank canvas) when the GLB fails to parse", async () => {
    // simulate GLTFLoader's async onError firing after a successful fetch + mount
    mountSpy.mockImplementation((_c, _g, options) => {
      options?.onError?.();
      return sceneHandle();
    });
    mockApi.modelGlb.mockResolvedValue(new Uint8Array([0x67, 0x6c, 0x54, 0x46]).buffer);
    wrap(<ModelViewer partId="tps62130" />);
    expect(await screen.findByText(/could not render the 3d preview/i)).toBeInTheDocument();
  });

  it("shows the backend's honest 502 reason (e.g. a WRL model is STEP-only)", async () => {
    mockApi.modelGlb.mockRejectedValue(
      new ApiError(502, "3D preview supports STEP models; .wrl models are not convertible yet"),
    );
    wrap(<ModelViewer partId="led_red" />);
    expect(await screen.findByText(/supports step models/i)).toBeInTheDocument();
  });
});

describe("Glb3DView scene synchronization", () => {
  const bytes = new Uint8Array([0x67, 0x6c, 0x54, 0x46]).buffer;
  const land = {
    units: "mm",
    pads: [{
      number: "1",
      at: [0, 0] as [number, number],
      size: [1, 1] as [number, number],
      shape: "rect",
      rotation: 0,
      drill: 0,
      pad_type: "smd",
      side: "front",
      rratio: 0,
    }],
    graphics: [],
    model_placement: null,
  };

  it("delivers a land pattern that resolves after the GLB scene mounts", async () => {
    const handle = sceneHandle();
    mountSpy.mockReturnValue(handle);
    const result = wrap(
      <Glb3DView data={bytes} isLoading={false} isError={false} land={undefined} />,
    );
    await waitFor(() => expect(mountSpy).toHaveBeenCalled());

    result.rerender(
      <ThemeProvider>
        <Glb3DView data={bytes} isLoading={false} isError={false} land={land} />
      </ThemeProvider>,
    );
    await waitFor(() => expect(handle.setLandPattern).toHaveBeenCalledWith(land));
  });

  it("replays the visible toolbar state into a newly mounted scene", async () => {
    const handle = sceneHandle();
    mountSpy.mockReturnValue(handle);
    wrap(
      <Glb3DView
        data={bytes}
        isLoading={false}
        isError={false}
        land={land}
        showViews
        showShading
      />,
    );
    await waitFor(() => expect(mountSpy).toHaveBeenCalled());
    expect(handle.setLandPattern).toHaveBeenCalledWith(land);
    expect(handle.setRenderMode).toHaveBeenCalledWith("studio");
    expect(handle.setLayers).toHaveBeenCalledWith({
      model: true,
      pads: true,
      board: true,
    });
    expect(handle.setView).toHaveBeenCalledWith("iso");
    expect(handle.setPlacementMode).toHaveBeenCalledWith("auto");
    expect(screen.getByRole("group", { name: "Layers" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Appearance" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Source Color" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(screen.getByRole("group", { name: "Motion" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Camera view" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Auto rotate" })).toHaveClass("min-h-[32px]");
    expect(screen.getByRole("button", { name: "Isometric" })).toHaveClass("min-h-[32px]");
  });

  it("reports visible only after the scene proves renderable geometry", async () => {
    const handle = sceneHandle();
    mountSpy.mockReturnValue(handle);
    const onVisibilityChange = vi.fn();
    wrap(
      <Glb3DView
        data={bytes}
        isLoading={false}
        isError={false}
        onVisibilityChange={onVisibilityChange}
      />,
    );

    await waitFor(() => expect(mountSpy).toHaveBeenCalled());
    expect(onVisibilityChange).toHaveBeenCalledWith("checking");
    expect(onVisibilityChange).not.toHaveBeenCalledWith("visible");

    mountSpy.mock.calls[mountSpy.mock.calls.length - 1]?.[2]?.onReady?.();
    expect(onVisibilityChange).toHaveBeenCalledWith("visible");
  });

  it("fits the whole visible model from the button and keyboard", async () => {
    const handle = sceneHandle();
    mountSpy.mockReturnValue(handle);
    wrap(
      <Glb3DView
        data={bytes}
        isLoading={false}
        isError={false}
        showViews
      />,
    );
    await waitFor(() => expect(mountSpy).toHaveBeenCalled());

    await userEvent.click(screen.getByRole("button", { name: "Fit" }));
    const canvas = screen.getByRole("application", { name: /3d model inspection canvas/i });
    canvas.focus();
    await userEvent.keyboard("f");
    expect(handle.fit).toHaveBeenCalledTimes(2);
  });

  it("keeps the model usable when a legacy land response omits pad metadata", async () => {
    const handle = sceneHandle();
    mountSpy.mockReturnValue(handle);
    const incompleteLand = { units: "mm" } as LandPattern;
    wrap(
      <Glb3DView
        data={bytes}
        isLoading={false}
        isError={false}
        land={incompleteLand}
        showViews
      />,
    );

    await waitFor(() => expect(mountSpy).toHaveBeenCalled());
    expect(screen.getByTestId("model-canvas")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pads" })).not.toBeInTheDocument();
    expect(handle.setLandPattern).not.toHaveBeenCalledWith(incompleteLand);
  });

  it("makes the compact viewer a passive auto-rotating specimen", async () => {
    const handle = sceneHandle();
    mountSpy.mockReturnValue(handle);
    const placedLand = {
      ...land,
      model_placement: {
        offset: [0, 0, 0] as [number, number, number],
        scale: [1, 1, 1] as [number, number, number],
        rotate: [0, 0, 0] as [number, number, number],
      },
    };
    wrap(
      <Glb3DView
        data={bytes}
        isLoading={false}
        isError={false}
        land={placedLand}
        showViews
        showShading
        compact
      />,
    );
    await waitFor(() => expect(mountSpy).toHaveBeenCalled());
    expect(screen.getByTestId("model-canvas")).toBeInTheDocument();
    expect(handle.setSpin).toHaveBeenCalledWith(true);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByRole("group")).not.toBeInTheDocument();
  });

  it("does not carry a failed render across to replacement GLB bytes", async () => {
    mountSpy.mockImplementationOnce((_c, _g, options) => {
      options?.onError?.();
      return sceneHandle();
    });
    const result = wrap(
      <Glb3DView data={bytes} isLoading={false} isError={false} />,
    );
    expect(await screen.findByText(/could not render the 3d preview/i)).toBeInTheDocument();

    const replacement = bytes.slice(0);
    result.rerender(
      <ThemeProvider>
        <Glb3DView data={replacement} isLoading={false} isError={false} />
      </ThemeProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("model-canvas")).toBeInTheDocument());
  });
});

describe("PreviewModal", () => {
  const available = { model: true, symbol: true, footprint: true };

  it("opens on the clicked tab and lists every preview type", async () => {
    mockApi.previewSvg.mockResolvedValue(svgBlob());
    wrap(
      <PreviewModal
        open
        partId="lm358"
        partName="LM358"
        available={available}
        initialKind="symbol"
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByRole("dialog", { name: "Inspect LM358" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Symbol" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("tab", { name: "3D Model" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Footprint" })).toBeInTheDocument();
  });

  it("disables the tab for a preview the part does not have", () => {
    wrap(
      <PreviewModal
        open
        partId="x"
        partName="X"
        available={{ model: false, symbol: true, footprint: true }}
        initialKind="symbol"
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByRole("tab", { name: "3D Model" })).toBeDisabled();
  });

  it("switches to the 3D tab and renders the 3D body", async () => {
    mockApi.previewSvg.mockResolvedValue(svgBlob());
    mockApi.modelGlb.mockRejectedValue(new ApiError(502, "no 3D tooling on this box"));
    wrap(
      <PreviewModal
        open
        partId="lm358"
        partName="LM358"
        available={available}
        initialKind="symbol"
        onClose={vi.fn()}
      />,
    );
    await userEvent.click(screen.getByRole("tab", { name: "3D Model" }));
    expect(await screen.findByText(/no 3d tooling on this box/i)).toBeInTheDocument();
  });

  it("closes on Escape, on the Close button, and on a scrim click", async () => {
    mockApi.previewSvg.mockResolvedValue(svgBlob());
    const onClose = vi.fn();
    wrap(
      <PreviewModal
        open
        partId="x"
        partName="X"
        available={available}
        initialKind="symbol"
        onClose={onClose}
      />,
    );
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("renders nothing when closed", () => {
    wrap(
      <PreviewModal
        open={false}
        partId="x"
        partName="X"
        available={available}
        initialKind="symbol"
        onClose={vi.fn()}
      />,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
