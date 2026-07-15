import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { ApiError, api } from "../api/client";
import { ProjectViewer, type ViewFile } from "./ProjectViewer";

vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return { ...actual, api: { ...actual.api, projectFile: vi.fn() } };
});

const mockApi = vi.mocked(api);

// Register a stub kicanvas-embed so loadKicanvas() sees the element already defined and
// resolves immediately (jsdom never loads the real WebGL bundle). Defined once, before any
// render, so the module-level singleton promise resolves for every test.
beforeAll(() => {
  if (!customElements.get("kicanvas-embed")) {
    customElements.define("kicanvas-embed", class extends HTMLElement {});
  }
  if (!customElements.get("kicanvas-source")) {
    customElements.define("kicanvas-source", class extends HTMLElement {});
  }
});

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

const FILES: ViewFile[] = [
  { path: "board.kicad_pcb", label: "board.kicad_pcb", kind: "Board" },
  { path: "board.kicad_sch", label: "board.kicad_sch", kind: "Schematic" },
];

describe("ProjectViewer", () => {
  it("fetches the first file WITH the bearer and inlines it as a kicanvas-source", async () => {
    mockApi.projectFile.mockResolvedValue("(kicad_pcb (version 20240108))");
    wrap(<ProjectViewer projectId="p1" files={FILES} />);

    await waitFor(() =>
      expect(mockApi.projectFile).toHaveBeenCalledWith("p1", "board.kicad_pcb"),
    );
    const embed = await screen.findByTestId("kicanvas-embed");
    expect(embed.querySelector("kicanvas-source")?.textContent).toContain("(kicad_pcb");
  });

  it("switches the viewed file when a tab is clicked and refetches", async () => {
    mockApi.projectFile.mockImplementation(async (_id, path) =>
      path.endsWith(".kicad_pcb") ? "(kicad_pcb board)" : "(kicad_sch sheet)",
    );
    wrap(<ProjectViewer projectId="p1" files={FILES} />);

    await screen.findByTestId("kicanvas-embed");
    const user = userEvent.setup();
    await user.click(screen.getByTestId("viewer-tab-board.kicad_sch"));

    await waitFor(() =>
      expect(mockApi.projectFile).toHaveBeenCalledWith("p1", "board.kicad_sch"),
    );
    await waitFor(() =>
      expect(
        screen.getByTestId("kicanvas-embed").querySelector("kicanvas-source")?.textContent,
      ).toContain("(kicad_sch"),
    );
  });

  it("shows an honest error (not a blank canvas) when the file fails to load", async () => {
    mockApi.projectFile.mockRejectedValue(new ApiError(404, "not a registered project file"));
    wrap(<ProjectViewer projectId="p1" files={FILES} />);

    expect(await screen.findByTestId("viewer-error")).toHaveTextContent(/not a registered/i);
    expect(screen.queryByTestId("kicanvas-embed")).not.toBeInTheDocument();
  });

  it("shows an honest empty state when the project has no board or schematic", () => {
    wrap(<ProjectViewer projectId="p1" files={[]} />);
    expect(screen.getByText(/no board or schematic to view/i)).toBeInTheDocument();
    expect(mockApi.projectFile).not.toHaveBeenCalled();
  });

  it("hides the tab bar for a single-file project", async () => {
    mockApi.projectFile.mockResolvedValue("(kicad_pcb board)");
    wrap(<ProjectViewer projectId="p1" files={[FILES[0]]} />);
    await screen.findByTestId("kicanvas-embed");
    expect(screen.queryByTestId("viewer-tabs")).not.toBeInTheDocument();
  });
});
