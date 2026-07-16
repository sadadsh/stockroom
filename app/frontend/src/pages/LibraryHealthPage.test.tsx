import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LibraryHealthPage } from "./LibraryHealthPage";

// The two health tools have their own suites; here we only check the segmented
// control wiring and which body it reveals.
vi.mock("./DoctorPage", () => ({
  DoctorPage: () => <div data-testid="body-doctor" />,
}));
vi.mock("./DuplicatesPage", () => ({
  DuplicatesPage: () => <div data-testid="body-duplicates" />,
}));

const { navigate } = vi.hoisted(() => ({ navigate: vi.fn() }));
vi.mock("../lib/router", () => ({
  useRouter: () => ({ route: "doctor", navigate }),
}));

describe("LibraryHealthPage", () => {
  it("shows the Doctor body and marks the Doctor segment when active is doctor", () => {
    render(<LibraryHealthPage active="doctor" />);
    expect(screen.getByTestId("body-doctor")).toBeInTheDocument();
    expect(screen.queryByTestId("body-duplicates")).toBeNull();
    expect(screen.getByRole("radio", { name: "Doctor" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("shows the Duplicates body when active is duplicates", () => {
    render(<LibraryHealthPage active="duplicates" />);
    expect(screen.getByTestId("body-duplicates")).toBeInTheDocument();
    expect(screen.queryByTestId("body-doctor")).toBeNull();
  });

  it("navigates to the other tool's route when its segment is picked", async () => {
    render(<LibraryHealthPage active="doctor" />);
    await userEvent.click(screen.getByRole("radio", { name: "Duplicates" }));
    expect(navigate).toHaveBeenCalledWith("duplicates");
  });
});
