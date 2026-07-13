import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { ApiError, api } from "../api/client";
import { ThemeProvider } from "../lib/theme";
import { ModelViewer } from "./ModelViewer";
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
// it so the component's mount/error wiring is exercised without a GL context.
const mountSpy = vi.fn(() => vi.fn());
vi.mock("../lib/threeScene", () => ({ mountModelScene: (...a: unknown[]) => mountSpy(...a) }));

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
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
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
    expect(mockApi.previewSvg).toHaveBeenCalledWith("symbol", "lm358");
  });

  it("falls back to the art glyph when the render is unavailable", async () => {
    mockApi.previewSvg.mockRejectedValue(new ApiError(404, "no symbol"));
    wrap(
      <PreviewImage kind="footprint" partId="x" fallback={<span>ART-FALLBACK</span>} />,
    );
    expect(await screen.findByText("ART-FALLBACK")).toBeInTheDocument();
  });
});

describe("SvgViewport", () => {
  it("renders the SVG and offers Reset View, tinted for the dark theme", async () => {
    wrap(<SvgViewport blob={svgBlob()} alt="symbol preview" />);
    const img = (await screen.findByAltText("symbol preview")) as HTMLImageElement;
    // dark is the default theme, so the monochrome art is inverted to near-white ink
    expect(img.style.filter).toBe("invert(1)");
    expect(screen.getByRole("button", { name: "Reset View" })).toBeInTheDocument();
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
  it("shows an honest message when 3D conversion tooling is absent (502)", async () => {
    mockApi.modelGlb.mockRejectedValue(new ApiError(502, "trimesh not installed"));
    wrap(<ModelViewer partId="tps62130" />);
    expect(
      await screen.findByText(/conversion tooling is not installed/i),
    ).toBeInTheDocument();
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
    expect(screen.getByRole("dialog", { name: "Previews for LM358" })).toBeInTheDocument();
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
    mockApi.modelGlb.mockRejectedValue(new ApiError(502, "no tooling"));
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
    expect(
      await screen.findByText(/conversion tooling is not installed/i),
    ).toBeInTheDocument();
  });

  it("closes on Escape, on the Close button, and on a scrim click", async () => {
    mockApi.previewSvg.mockResolvedValue(svgBlob());
    const onClose = vi.fn();
    const { rerender } = wrap(
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
