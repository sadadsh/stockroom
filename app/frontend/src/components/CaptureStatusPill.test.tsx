import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const state = {
  active: {} as Record<string, unknown>,
  requestReopen: vi.fn(),
  reset: vi.fn(),
};
const navigate = vi.fn();

vi.mock("../lib/capture", () => ({ useCapture: () => state }));
vi.mock("../lib/router", () => ({ useRouter: () => ({ navigate }) }));

import { CaptureStatusPill } from "./CaptureStatusPill";

function setActive(partial: Record<string, unknown>) {
  state.active = {
    partId: null,
    partName: null,
    status: "idle",
    needs: [],
    received: {},
    backgrounded: false,
    ...partial,
  };
}

beforeEach(() => {
  state.requestReopen = vi.fn();
  state.reset = vi.fn();
  navigate.mockClear();
});

describe("CaptureStatusPill", () => {
  it("renders nothing when no capture is backgrounded", () => {
    setActive({ partId: "p1", status: "receiving", backgrounded: false });
    render(<CaptureStatusPill />);
    expect(screen.queryByText("Capturing")).toBeNull();
  });

  it("shows the part, status and meter when a capture is backgrounded", () => {
    setActive({
      partId: "p1",
      partName: "BQ24074",
      status: "receiving",
      backgrounded: true,
      needs: ["kicad_symbol", "altium_symbol"],
      received: { kicad_symbol: true },
    });
    render(<CaptureStatusPill />);
    expect(screen.getByText("BQ24074")).toBeInTheDocument();
    expect(screen.getByText("Capturing")).toBeInTheDocument();
    expect(screen.getByText("1/2")).toBeInTheDocument();
  });

  it("reopens the part on click", async () => {
    const user = userEvent.setup();
    setActive({
      partId: "p1",
      partName: "BQ24074",
      status: "receiving",
      backgrounded: true,
      needs: ["kicad_symbol"],
      received: {},
    });
    render(<CaptureStatusPill />);
    await user.click(screen.getByRole("button", { name: /Reopen the guided capture/ }));
    expect(state.requestReopen).toHaveBeenCalled();
    expect(navigate).toHaveBeenCalledWith("components");
  });

  it("can be dismissed on a terminal state", async () => {
    const user = userEvent.setup();
    setActive({
      partId: "p1",
      partName: "BQ24074",
      status: "done",
      backgrounded: true,
      needs: ["kicad_symbol"],
      received: { kicad_symbol: true },
    });
    render(<CaptureStatusPill />);
    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(state.reset).toHaveBeenCalled();
  });
});
