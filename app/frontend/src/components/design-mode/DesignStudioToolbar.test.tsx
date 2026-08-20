import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DesignStudioToolbar } from "./DesignStudioToolbar";

const applyLocal = vi.fn();
const studio = {
  activeScenario: null as { id: string; title: string } | null,
  activeScenarioId: null as string | null,
  appliedRevision: null as string | null,
  appliedState: "ready" as "loading" | "ready" | "applying" | "error",
  appliedMatchesDraft: false,
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

function renderToolbar(mode: "preview" | "edit" = "preview") {
  return render(
    <DesignStudioToolbar
      mode={mode}
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
    studio.appliedMatchesDraft = false;
  });

  it("shows Draft Only before a design is explicitly committed", () => {
    renderToolbar();
    expect(screen.getByText("Draft")).toBeVisible();
    expect(screen.getByRole("button", { name: "Apply To This PC" })).toBeEnabled();
  });

  it("keeps secondary display controls inside one View menu", async () => {
    renderToolbar();

    expect(screen.queryByLabelText("Viewport")).not.toBeInTheDocument();
    expect(screen.queryByRole("slider", { name: "Grid And Snap Size" })).not.toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "View" }));

    expect(screen.getByLabelText("Viewport")).toBeVisible();
    expect(screen.getByRole("button", { name: "Presentation" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Grid" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Snap" })).toBeVisible();
    expect(screen.getByRole("slider", { name: "Grid And Snap Size" })).toHaveValue("8");
  });

  it("lets Escape close only the View menu", async () => {
    renderToolbar();
    const user = userEvent.setup();
    const view = screen.getByRole("button", { name: "View" });
    await user.click(view);
    expect(screen.getByLabelText("Viewport")).toBeVisible();

    await user.keyboard("{Escape}");

    expect(screen.queryByLabelText("Viewport")).not.toBeInTheDocument();
    expect(view).toHaveFocus();
  });

  it("keeps grid, snap, and shared size controls inside View in Edit", async () => {
    renderToolbar("edit");

    expect(screen.getByRole("group", { name: "Studio Mode" })).toBeVisible();
    expect(screen.queryByRole("group", { name: "Edit Grid Controls" })).not.toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "View" }));
    const controls = screen.getByRole("group", { name: "Edit Grid Controls" });
    expect(within(controls).getByRole("button", { name: "Grid" })).toBeVisible();
    expect(within(controls).getByRole("button", { name: "Snap" })).toBeVisible();
    expect(within(controls).getByRole("slider", { name: "Grid And Snap Size" })).toHaveValue("8");
  });

  it("uses one clear Apply action and a short Exit action", () => {
    renderToolbar();
    expect(screen.getByRole("button", { name: "Apply To This PC" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Exit" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Set" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Close Design Studio" })).not.toBeInTheDocument();
  });

  it("distinguishes the committed revision from later draft changes", () => {
    studio.appliedRevision = "1234567890abcdef";
    studio.appliedMatchesDraft = true;
    const { rerender } = renderToolbar();
    expect(screen.getByText("Applied · 12345678")).toBeVisible();
    expect(screen.getByRole("button", { name: "Applied" })).toBeDisabled();

    studio.appliedMatchesDraft = false;
    rerender(<DesignStudioToolbar
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
      snap
      onSnapChange={vi.fn()}
      onClose={vi.fn()}
    />);
    expect(screen.getByText("Draft Changes")).toBeVisible();
    expect(screen.getByRole("button", { name: "Apply To This PC" })).toBeEnabled();
  });

  it("reports a failed Apply instead of leaving an old applied revision looking current", () => {
    studio.appliedRevision = "1234567890abcdef";
    studio.appliedState = "error";
    renderToolbar();
    expect(screen.getByText("Apply Failed")).toBeVisible();
  });

  it("never applies a fixture-backed preview", async () => {
    studio.activeScenario = { id: "global.source-promotion.ready", title: "Source Promotion Ready" };
    studio.activeScenarioId = studio.activeScenario.id;
    renderToolbar();

    expect(screen.getByText("Preview Data")).toBeVisible();
    const button = screen.getByRole("button", { name: "Apply To This PC" });
    expect(button).toBeDisabled();
    await userEvent.setup().click(button);
    expect(applyLocal).not.toHaveBeenCalled();
  });

  it("applies the personal draft only after the person presses Apply", async () => {
    renderToolbar();

    await userEvent.setup().click(screen.getByRole("button", { name: "Apply To This PC" }));
    expect(applyLocal).toHaveBeenCalledOnce();
  });
});
