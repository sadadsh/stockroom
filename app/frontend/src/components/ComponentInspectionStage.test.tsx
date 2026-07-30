import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { api } from "../api/client";
import { ThemeProvider } from "../lib/theme";
import { ComponentInspectionStage } from "./ComponentInspectionStage";

vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      previewSvg: vi.fn(),
      modelGlb: vi.fn(),
      landPattern: vi.fn(),
    },
  };
});

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
    container: HTMLElement,
    glb: ArrayBuffer,
    options?: { onError?: () => void; onReady?: () => void },
  ) => mountSpy(container, glb, options),
}));

const mockApi = vi.mocked(api);
const allAvailable = { symbol: true, footprint: true, model: true };

beforeEach(() => {
  mockApi.previewSvg.mockResolvedValue(
    new Blob(["<svg viewBox='0 0 10 10'><rect width='10' height='10'/></svg>"], {
      type: "image/svg+xml",
    }),
  );
  mockApi.modelGlb.mockResolvedValue(
    new Uint8Array([0x67, 0x6c, 0x54, 0x46]).buffer,
  );
  mockApi.landPattern.mockResolvedValue({
    units: "mm",
    pads: [],
    graphics: [],
    model_placement: null,
  });
});

function wrap(ui: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, retryDelay: 0 } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>{ui}</ThemeProvider>
    </QueryClientProvider>,
  );
}

describe("ComponentInspectionStage", () => {
  it("uses one projection stage and never calls linked bytes a visible model", async () => {
    wrap(
      <ComponentInspectionStage
        partId="lm358"
        partName="LM358"
        available={allAvailable}
      />,
    );

    expect(screen.getByRole("tab", { name: "3D Model" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByText("Checking visible geometry")).toBeInTheDocument();
    expect(screen.queryByText(/3D Ready/i)).not.toBeInTheDocument();

    await waitFor(() => expect(mountSpy).toHaveBeenCalledTimes(1));
    mountSpy.mock.calls[0][2]?.onReady?.();
    expect(await screen.findByText("Visible model · Whole object framed")).toBeInTheDocument();
  });

  it("expands the same renderer and preserves its state", async () => {
    wrap(
      <ComponentInspectionStage
        partId="lm358"
        partName="LM358"
        available={allAvailable}
      />,
    );
    await waitFor(() => expect(mountSpy).toHaveBeenCalledTimes(1));
    const canvas = screen.getByTestId("model-canvas");

    await userEvent.click(screen.getByRole("button", { name: "Expand Inspection" }));
    expect(screen.getByRole("dialog", { name: "Inspect LM358" })).toBeInTheDocument();
    expect(screen.getByTestId("model-canvas")).toBe(canvas);
    expect(screen.getByRole("button", { name: "Fit" })).toBeInTheDocument();
    expect(mountSpy).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole("button", { name: "Close Inspection" }));
    expect(screen.getByRole("region", { name: "Inspect LM358" })).toBeInTheDocument();
    expect(screen.getByTestId("model-canvas")).toBe(canvas);
    expect(mountSpy).toHaveBeenCalledTimes(1);
  });

  it("fits a decoded symbol into the same full stage", async () => {
    wrap(
      <ComponentInspectionStage
        partId="lm358"
        partName="LM358"
        available={allAvailable}
      />,
    );
    await userEvent.click(screen.getByRole("tab", { name: "Symbol" }));
    const image = await screen.findByAltText("symbol preview");
    expect(image).toHaveClass("object-contain", "p-4");
    fireEvent.load(image);
    expect(await screen.findByText("Visible symbol · Whole drawing fitted")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Expand Inspection" }));
    expect(screen.getByAltText("symbol preview")).toBe(image);
    expect(image).toHaveClass("p-[clamp(1rem,3vmin,2.5rem)]");
  });

  it("shows a failed model preview as unavailable instead of ready", async () => {
    mockApi.modelGlb.mockRejectedValue(new Error("invalid model"));
    wrap(
      <ComponentInspectionStage
        partId="broken"
        partName="Broken Part"
        available={allAvailable}
      />,
    );

    expect(await screen.findByText("Preview unavailable")).toBeInTheDocument();
    expect(screen.queryByText(/ready/i)).not.toBeInTheDocument();
  });

  it("has no selected disabled tab when no visual representation exists", () => {
    wrap(
      <ComponentInspectionStage
        partId="empty"
        partName="Empty Part"
        available={{ symbol: false, footprint: false, model: false }}
      />,
    );

    expect(screen.getByText("No visual representations are linked.")).toBeInTheDocument();
    expect(screen.queryByRole("tab", { selected: true })).not.toBeInTheDocument();
  });
});
