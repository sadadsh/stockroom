import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LibraryPage } from "./LibraryPage";

// The tab shell's job is pure wiring: which tab is active, where a click
// navigates, which body renders. The bodies have their own test suites, so
// they are stubbed here.
vi.mock("./ComponentsPage", () => ({
  ComponentsPage: () => <div data-testid="body-parts" />,
}));
vi.mock("./IngestPage", () => ({
  IngestPage: () => <div data-testid="body-ingest" />,
}));
vi.mock("./DuplicatesPage", () => ({
  DuplicatesPage: () => <div data-testid="body-duplicates" />,
}));
vi.mock("./DoctorPage", () => ({
  DoctorPage: () => <div data-testid="body-doctor" />,
}));

const { navigate } = vi.hoisted(() => ({ navigate: vi.fn() }));
vi.mock("../lib/router", () => ({
  useRouter: () => ({ route: "ingest", navigate }),
}));

describe("LibraryPage", () => {
  it("renders the Library header with all four tabs and the active one marked", () => {
    render(<LibraryPage tab="ingest" />);
    expect(screen.getByText("Library")).toBeInTheDocument();
    for (const label of ["Parts", "Add Parts", "Duplicates", "Doctor"]) {
      expect(screen.getByRole("tab", { name: label })).toBeInTheDocument();
    }
    expect(screen.getByRole("tab", { name: "Add Parts" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("tab", { name: "Parts" })).toHaveAttribute(
      "aria-selected",
      "false",
    );
  });

  it("renders the body that belongs to the active tab", () => {
    render(<LibraryPage tab="duplicates" />);
    expect(screen.getByTestId("body-duplicates")).toBeInTheDocument();
    expect(screen.queryByTestId("body-parts")).toBeNull();
  });

  it("navigates to a tab's route when it is clicked", async () => {
    render(<LibraryPage tab="components" />);
    await userEvent.click(screen.getByRole("tab", { name: "Doctor" }));
    expect(navigate).toHaveBeenCalledWith("doctor");
  });
});
