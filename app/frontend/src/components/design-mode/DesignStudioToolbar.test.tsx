import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DesignStudioToolbar } from "./DesignStudioToolbar";

const promotePersonalDesign = vi.fn();
const studio = {
  activeScenario: null as { id: string; title: string } | null,
  activeScenarioId: null as string | null,
  promotionStatus: {
    state: "blocked" as "checking" | "ready" | "running" | "blocked" | "success" | "failure",
    message: "Dev Mode needs a managed Stockroom source checkout.",
  },
  promotePersonalDesign,
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
      mode="browse"
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
      snap={true}
      onSnapChange={vi.fn()}
      onClose={vi.fn()}
    />,
  );
}

describe("DesignStudioToolbar source promotion", () => {
  beforeEach(() => {
    promotePersonalDesign.mockReset();
    studio.activeScenario = null;
    studio.activeScenarioId = null;
    studio.promotionStatus = {
      state: "blocked",
      message: "Dev Mode needs a managed Stockroom source checkout.",
    };
  });

  it("shows the exact packaged-build blocker instead of offering a working source action", () => {
    renderToolbar();
    expect(screen.getByText("Dev Mode needs a managed Stockroom source checkout.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Make App Default" })).toBeDisabled();
  });

  it("never invokes source promotion from a fixture-backed simulated ready state", async () => {
    studio.activeScenario = { id: "global.source-promotion.ready", title: "Source Promotion Ready" };
    studio.activeScenarioId = studio.activeScenario.id;
    studio.promotionStatus = { state: "ready", message: "Ready to make this design the app default." };
    renderToolbar();

    const button = screen.getByRole("button", { name: "Make App Default" });
    expect(button).toBeDisabled();
    await userEvent.setup().click(button);
    expect(promotePersonalDesign).not.toHaveBeenCalled();
  });

  it("invokes the personal-design promotion in Real Data mode", async () => {
    studio.promotionStatus = { state: "ready", message: "Ready to make this design the app default." };
    renderToolbar();

    await userEvent.setup().click(screen.getByRole("button", { name: "Make App Default" }));
    expect(promotePersonalDesign).toHaveBeenCalledWith("Promote personal Stockroom design");
  });
});
