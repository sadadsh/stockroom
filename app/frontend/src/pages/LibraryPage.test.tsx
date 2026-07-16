import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LibraryPage } from "./LibraryPage";

// The tab shell's job is pure wiring: which tab is active, where a click
// navigates, which body renders. The bodies have their own test suites, so
// they are stubbed here. Add Parts is not a tab (it is a full-screen wizard
// reached from the Parts toolbar), and Duplicates is now a filter inside Parts,
// so the flagship's tabs are just Parts, BOM Coverage, and Doctor.
vi.mock("./ComponentsPage", () => ({
  ComponentsPage: () => <div data-testid="body-parts" />,
}));
vi.mock("./BomPage", () => ({
  BomPage: () => <div data-testid="body-bom" />,
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
  it("renders the Library header with the grouped tabs", () => {
    render(<LibraryPage route="components" />);
    expect(screen.getByText("Components")).toBeInTheDocument();
    for (const label of ["Parts", "BOM Coverage", "Doctor"]) {
      expect(screen.getByRole("tab", { name: label })).toBeInTheDocument();
    }
    // Add Parts is demoted out of the tab strip; Duplicates is a Parts filter now.
    expect(screen.queryByRole("tab", { name: "Add Parts" })).toBeNull();
    expect(screen.queryByRole("tab", { name: "Duplicates" })).toBeNull();
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

  it("lights the Doctor tab and renders it for the doctor route", () => {
    render(<LibraryPage route="doctor" />);
    expect(screen.getByRole("tab", { name: "Doctor" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByTestId("body-doctor")).toBeInTheDocument();
  });

  it("navigates to a tab's route when it is clicked", async () => {
    render(<LibraryPage route="components" />);
    await userEvent.click(screen.getByRole("tab", { name: "BOM Coverage" }));
    expect(navigate).toHaveBeenCalledWith("bom");
  });

  it("navigates to the doctor route when the Doctor tab is clicked", async () => {
    render(<LibraryPage route="components" />);
    await userEvent.click(screen.getByRole("tab", { name: "Doctor" }));
    expect(navigate).toHaveBeenCalledWith("doctor");
  });
});
