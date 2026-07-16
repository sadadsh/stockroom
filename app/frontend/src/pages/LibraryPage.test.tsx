import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LibraryPage } from "./LibraryPage";

// The tab shell's job is pure wiring: which tab is active, where a click
// navigates, which body renders. The bodies have their own suites, so they are
// stubbed. Add Parts is a full-screen wizard (not a tab), Duplicates is a Parts
// filter, and Doctor moved to Settings, so the flagship's tabs are Parts + BOM.
vi.mock("./ComponentsPage", () => ({
  ComponentsPage: () => <div data-testid="body-parts" />,
}));
vi.mock("./BomPage", () => ({
  BomPage: () => <div data-testid="body-bom" />,
}));

const { navigate } = vi.hoisted(() => ({ navigate: vi.fn() }));
vi.mock("../lib/router", () => ({
  useRouter: () => ({ route: "components", navigate }),
}));

beforeEach(() => navigate.mockClear());

describe("LibraryPage", () => {
  it("renders the Library header with the Parts and BOM Coverage tabs", () => {
    render(<LibraryPage route="components" />);
    expect(screen.getByText("Components")).toBeInTheDocument();
    for (const label of ["Parts", "BOM Coverage"]) {
      expect(screen.getByRole("tab", { name: label })).toBeInTheDocument();
    }
    // Add Parts is a wizard, Duplicates is a filter, Doctor is in Settings.
    for (const gone of ["Add Parts", "Duplicates", "Doctor"]) {
      expect(screen.queryByRole("tab", { name: gone })).toBeNull();
    }
    expect(screen.getByRole("tab", { name: "Parts" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("renders the body that belongs to the active tab", () => {
    render(<LibraryPage route="bom" />);
    expect(screen.getByTestId("body-bom")).toBeInTheDocument();
    expect(screen.queryByTestId("body-parts")).toBeNull();
  });

  it("navigates to a tab's route when it is clicked", async () => {
    render(<LibraryPage route="components" />);
    await userEvent.click(screen.getByRole("tab", { name: "BOM Coverage" }));
    expect(navigate).toHaveBeenCalledWith("bom");
  });
});
