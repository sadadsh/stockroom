import { render, screen } from "@testing-library/react";
import { LibraryPage } from "./LibraryPage";

// The Components flagship is now just a header over the Parts view: BOM Coverage
// moved to the project BOM, Duplicates is a Parts filter, and Doctor is in Settings.
// So there is no tab strip anymore; the body is stubbed (it has its own suite).
vi.mock("./ComponentsPage", () => ({
  ComponentsPage: () => <div data-testid="body-parts" />,
}));

describe("LibraryPage", () => {
  it("renders the Components header over the Parts view, with no tab strip", () => {
    render(<LibraryPage />);
    expect(screen.getByText("Components")).toBeInTheDocument();
    expect(screen.getByTestId("body-parts")).toBeInTheDocument();
    expect(screen.queryByRole("tab")).toBeNull();
  });
});
