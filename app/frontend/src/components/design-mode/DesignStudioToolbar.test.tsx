import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DesignStudioToolbar } from "./DesignStudioToolbar";

const applyLocal = vi.fn();
const studio = {
  activeScenario: null as { id: string; title: string } | null,
  activeScenarioId: null as string | null,
  appliedRevision: null as string | null,
  appliedState: "ready" as "loading" | "ready" | "applying" | "error",
  applyLocal,
};

vi.mock("../../design-studio/DesignStudioProvider", () => ({ useDesignStudio: () => studio }));
vi.mock("../../lib/devMode", () => ({
  useDevMode: () => ({
    canUndo: false,
    canRedo: false,
    dirty: true,
    saving: false,
    undo: vi.fn(),
    redo: vi.fn(),
    resetAll: vi.fn(),
    save: vi.fn(),
    resolveCopy: (_id: string, fallback: string) => fallback,
  }),
}));
vi.mock("../../lib/theme", () => ({ useTheme: () => ({ theme: "dark", toggle: vi.fn() }) }));

function renderToolbar() {
  return render(
    <DesignStudioToolbar
      mode="preview"
      onModeChange={vi.fn()}
      presentation={false}
      onPresentationChange={vi.fn()}
      viewport="desktop-1366"
      onViewportChange={vi.fn()}
      customViewportWidth={1366}
      onCustomViewportWidthChange={vi.fn()}
      zoom={100}
      onZoomChange={vi.fn()}
      grid={false}
      onGridChange={vi.fn()}
      gridSize={8}
      onGridSizeChange={vi.fn()}
      snap={true}
      onSnapChange={vi.fn()}
      onClose={vi.fn()}
    />,
  );
}

describe("DesignStudioToolbar local Apply", () => {
  beforeEach(() => {
    applyLocal.mockReset();
    studio.activeScenario = null;
    studio.activeScenarioId = null;
    studio.appliedRevision = null;
    studio.appliedState = "ready";
  });

  it("shows Draft Only before a design is explicitly applied", () => {
    renderToolbar();
    expect(screen.getByText("Draft")).toBeVisible();
    expect(screen.getByRole("button", { name: "Apply" })).toBeEnabled();
  });

  it("keeps secondary display controls inside one View menu", async () => {
    renderToolbar();

    expect(screen.queryByLabelText("Viewport")).not.toBeInTheDocument();
    expect(screen.queryByRole("slider", { name: "Grid Size" })).not.toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "View" }));

    expect(screen.getByLabelText("Viewport")).toBeVisible();
    expect(screen.getByRole("slider", { name: "Grid Size" })).toHaveValue("8");
    expect(screen.getByRole("button", { name: "Presentation" })).toBeVisible();
  });

  it("uses one clear Apply action and a short Exit action", () => {
    renderToolbar();
    expect(screen.getByRole("button", { name: "Apply" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Exit" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Set" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Close Design Studio" })).not.toBeInTheDocument();
  });

  it("shows the active machine revision after Apply", () => {
    studio.appliedRevision = "1234567890abcdef";
    renderToolbar();
    expect(screen.getByText("Applied · 12345678")).toBeVisible();
  });

  it("never applies a fixture-backed preview", async () => {
    studio.activeScenario = { id: "global.source-promotion.ready", title: "Source Promotion Ready" };
    studio.activeScenarioId = studio.activeScenario.id;
    renderToolbar();

    const button = screen.getByRole("button", { name: "Apply" });
    expect(button).toBeDisabled();
    await userEvent.setup().click(button);
    expect(applyLocal).not.toHaveBeenCalled();
  });

  it("applies the personal draft only after the person presses Apply", async () => {
    renderToolbar();

    await userEvent.setup().click(screen.getByRole("button", { name: "Apply" }));
    expect(applyLocal).toHaveBeenCalledOnce();
  });
});
