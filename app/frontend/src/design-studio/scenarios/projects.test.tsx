import { screen, waitFor, within } from "@testing-library/react";
import { bootstrapScenarioRegistry } from ".";
import { projectScenarioIds } from "./projects";
import { mountScenario } from "./testHarness";

const EXPECTED_PROJECT_CASES = [
  "projects.loading",
  "projects.empty",
  "projects.list-error",
  "projects.workspace-error",
  "projects.kicad.overview",
  "projects.kicad.bom",
  "projects.kicad.build",
  "projects.kicad.activity",
  "projects.altium.overview",
  "projects.altium.bom",
  "projects.altium.build",
  "projects.altium.activity",
  "projects.render-blocked",
  "projects.native-render-ready",
  "projects.missing-kicad",
  "projects.missing-altium",
  "projects.overlay-blocked",
  "projects.no-repository",
  "projects.diverged",
  "projects.shared-review",
  "projects.build-complete",
] as const;

const WORKBENCHES = ["overview", "bom", "build", "activity"] as const;

describe("Projects Design Studio scenarios", () => {
  it("registers the exact Projects case inventory with valid endpoint fixtures", () => {
    expect(projectScenarioIds).toEqual(EXPECTED_PROJECT_CASES);
    expect(
      bootstrapScenarioRegistry.issues.filter((issue) =>
        issue.scenarioId?.startsWith("projects."),
      ),
    ).toEqual([]);
  });

  it.each(WORKBENCHES)("mounts the real KiCad %s workbench", async (tab) => {
    const { liveRequest } = await mountScenario(`projects.kicad.${tab}`);
    expect(document.querySelector(`[data-dev-id="projects.${tab}"]`)).toBeVisible();
    expect(liveRequest).not.toHaveBeenCalled();
  });

  it.each(WORKBENCHES)("mounts the real Altium %s workbench", async (tab) => {
    const { liveRequest } = await mountScenario(`projects.altium.${tab}`);
    expect(document.querySelector(`[data-dev-id="projects.${tab}"]`)).toBeVisible();
    expect(liveRequest).not.toHaveBeenCalled();
  });

  it.each(EXPECTED_PROJECT_CASES)("mounts %s through the real application tree", async (id) => {
    const { liveRequest } = await mountScenario(id);
    const scenario = bootstrapScenarioRegistry.scenarioById(id);
    expect(scenario).toBeDefined();
    for (const target of scenario?.expectedTargets ?? []) {
      expect(document.querySelector(`[data-dev-id="${target}"], [data-dev-role="${target}"]`))
        .toBeInTheDocument();
    }
    expect(document.querySelector('[data-dev-id="shell.root"]')).toBeInTheDocument();
    expect(liveRequest).not.toHaveBeenCalled();
  });

  it("clicks through projects, documents, tabs, filters, placement, build, and changes", async () => {
    const { user, liveRequest } = await mountScenario("projects.kicad.overview");

    await user.click(screen.getByRole("option", { name: /Control Board/ }));
    expect(await screen.findByRole("heading", { name: "Control Board" })).toBeVisible();
    await user.click(screen.getByRole("option", { name: /Power Board/ }));
    expect(await screen.findByRole("heading", { name: "Power Board" })).toBeVisible();

    await user.click(screen.getByRole("button", {
      name: /Power, Schematic, Power\.kicad_sch/,
    }));
    expect(screen.getByRole("heading", { name: "Main Schematic" })).toBeVisible();
    await user.click(screen.getByRole("button", {
      name: /Power, PCB, Power\.kicad_pcb/,
    }));
    const overviewMap = await screen.findByRole("region", { name: "PCB view" });
    await user.click(within(overviewMap).getByRole("button", { name: /R2,/ }));
    expect(screen.getByText("Selected Placement")).toBeVisible();

    await user.click(screen.getByRole("tab", { name: "BOM" }));
    const bomFilter = await screen.findByRole("radiogroup", { name: "BOM line filter" });
    await user.click(within(bomFilter).getByRole("radio", { name: "Needs Link" }));
    expect(within(bomFilter).getByRole("radio", { name: "Needs Link" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getByRole("complementary", { name: "BOM line details" })).toBeVisible();

    await user.click(screen.getByRole("tab", { name: "Build" }));
    const buildMap = await screen.findByRole("region", { name: "PCB view" });
    await user.click(within(buildMap).getByRole("button", { name: /R2,/ }));
    expect(screen.getByRole("complementary", { name: "Selected placement" })).toHaveTextContent("R2");

    await user.click(screen.getByRole("tab", { name: "Recent Work" }));
    expect(await screen.findByText("Review Queue")).toBeVisible();
    expect(screen.getByRole("checkbox", { name: "Main PCB" })).toBeChecked();
    expect(liveRequest).not.toHaveBeenCalled();
  });

  it("keeps native Render and Open controls visible but blocks them with Real Data guidance", async () => {
    const { user, liveRequest } = await mountScenario("projects.render-blocked");
    const renderBoard = await screen.findByRole("button", { name: "Render PCB" });
    const openDocument = screen.getByRole("button", { name: "Open In KiCad" });
    expect(renderBoard).toBeVisible();
    expect(openDocument).toBeVisible();

    await user.click(renderBoard);
    await waitFor(() => expect(renderBoard).toHaveAccessibleDescription(/return to Real Data/i));
    await user.click(openDocument);
    await waitFor(() =>
      expect(document.querySelector('[data-dev-id="toast.status"]')).toHaveTextContent(
        /return to Real Data/i,
      ),
    );
    expect(liveRequest).not.toHaveBeenCalled();
  });

  it("exposes the native render result", async () => {
    await mountScenario("projects.native-render-ready");
    expect(document.querySelector('[data-dev-id="projects.native-board-render"]')).toBeVisible();
  });

  it("exposes the editor overlay blocker", async () => {
    await mountScenario("projects.overlay-blocked");
    expect(screen.getByText(/linked editor is in use/i)).toBeVisible();
  });

  it("exposes the missing KiCad runtime", async () => {
    await mountScenario("projects.missing-kicad");
    expect(screen.getByText(/install the linked editor/i)).toBeVisible();
    expect(screen.getByText(/KiCad Needed/i)).toBeVisible();
  });

  it("exposes the missing Altium runtime", async () => {
    await mountScenario("projects.missing-altium");
    expect(screen.getByText(/install the linked editor/i)).toBeVisible();
    expect(screen.getByText(/Altium Designer Needed/i)).toBeVisible();
  });

  it("exposes the repository initialization state", async () => {
    await mountScenario("projects.no-repository");
    expect(screen.getByText("Git Is Not Initialized")).toBeVisible();
  });

  it("exposes the diverged repository state", async () => {
    await mountScenario("projects.diverged");
    expect(screen.getByText("1 Ahead · 1 Behind")).toBeVisible();
  });

  it("exposes shared review evidence", async () => {
    await mountScenario("projects.shared-review");
    expect(screen.getByRole("complementary", { name: "Review evidence" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "work/nadia/power-board" })).toBeVisible();
  });

  it("exposes the completed build", async () => {
    await mountScenario("projects.build-complete");
    expect(screen.getByText("Build Complete")).toBeVisible();
  });
});
