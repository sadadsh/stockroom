import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LibraryPage } from "./LibraryPage";

// The tab shell's job is pure wiring: which tab is active, where a click
// navigates, which body renders. The bodies have their own test suites, so
// they are stubbed here. Add Parts is no longer a tab (it is a full-screen
// wizard reached from the Parts toolbar), and Duplicates + Doctor are folded
// under one Library Health tab with an internal segmented control.
vi.mock("./ComponentsPage", () => ({
  ComponentsPage: () => <div data-testid="body-parts" />,
}));
vi.mock("./BomPage", () => ({
  BomPage: () => <div data-testid="body-bom" />,
}));
vi.mock("./DuplicatesPage", () => ({
  DuplicatesPage: () => <div data-testid="body-duplicates" />,
}));
vi.mock("./DoctorPage", () => ({
  DoctorPage: () => <div data-testid="body-doctor" />,
}));

const { navigate } = vi.hoisted(() => ({ navigate: vi.fn() }));
vi.mock("../lib/router", () => ({
  useRouter: () => ({ route: "components", navigate }),
}));

beforeEach(() => navigate.mockClear());

describe("LibraryPage", () => {
  it("renders the Library header with the three grouped tabs", () => {
    render(<LibraryPage route="components" />);
    expect(screen.getByText("Library")).toBeInTheDocument();
    for (const label of ["Parts", "BOM Coverage", "Library Health"]) {
      expect(screen.getByRole("tab", { name: label })).toBeInTheDocument();
    }
    // Add Parts is demoted out of the tab strip.
    expect(screen.queryByRole("tab", { name: "Add Parts" })).toBeNull();
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

  it("lights the Library Health tab for both the doctor and duplicates routes", () => {
    render(<LibraryPage route="doctor" />);
    expect(screen.getByRole("tab", { name: "Library Health" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByTestId("body-doctor")).toBeInTheDocument();

    render(<LibraryPage route="duplicates" />);
    expect(screen.getAllByRole("tab", { name: "Library Health" })[1]).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByTestId("body-duplicates")).toBeInTheDocument();
  });

  it("navigates to a tab's route when it is clicked", async () => {
    render(<LibraryPage route="components" />);
    await userEvent.click(screen.getByRole("tab", { name: "BOM Coverage" }));
    expect(navigate).toHaveBeenCalledWith("bom");
  });

  it("enters Library Health on the doctor route by default", async () => {
    render(<LibraryPage route="components" />);
    await userEvent.click(screen.getByRole("tab", { name: "Library Health" }));
    expect(navigate).toHaveBeenCalledWith("doctor");
  });
});
