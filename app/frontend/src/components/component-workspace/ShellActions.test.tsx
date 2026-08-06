/**
 * The Manage menu's three shell actions, as a surface contract.
 *
 * Every assertion here is about ABSENCE. The three items only exist when this machine can perform
 * them, and the whole reason they were missing for so long is that offering them without a bridge
 * would have meant three menu entries that open nothing. A dead click path is worse than an
 * absent one, so what is proved below is that nothing is drawn speculatively.
 *
 * The last block is about the other half: `WorkspaceShellDialogs`, which holds the running token
 * and the two mutations. That token is the only thing standing between one press and two processes
 * started on the same component, and it is the piece the workspace can no longer see, so it is
 * asserted here on the rendered rows rather than left to the workspace's own tests.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState, type ReactNode } from "react";
import { ApiError, api } from "../../api/client";
import type { PartShell } from "../../api/types";
import { ThemeProvider } from "../../lib/theme";
import { ToastProvider } from "../../lib/toast";
import { ManageMenu } from "./ManageMenu";
import { manageMenuItems, openableApplications, shellManageItems } from "./manageActions";
import {
  ExportComponentDialog,
  OpenInDialog,
  WorkspaceShellDialogs,
  type ShellDialog,
} from "./ShellActions";

vi.mock("../../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../../api/client")>();
  return { ...actual, api: { exportPart: vi.fn(), openPartIn: vi.fn() } };
});

const mockApi = vi.mocked(api);

const HOST_WITH_EVERYTHING: PartShell = {
  supported: true,
  component_directory: true,
  export_formats: ["kicad", "step"],
  eda_applications: [
    { id: "kicad", name: "KiCad 9.0", version: "9.0.1" },
    { id: "altium-designer", name: "Altium Designer 25", version: "25.0" },
  ],
};

const NOTHING = { onExport: () => {}, onOpenIn: () => {}, onReveal: () => {} };

function provide(node: React.ReactNode) {
  return render(<ThemeProvider>{node}</ThemeProvider>);
}

describe("which shell actions the Manage menu offers", () => {
  it("offers all three when the host owns a window and the component has files", () => {
    expect(shellManageItems(HOST_WITH_EVERYTHING, NOTHING).map((item) => item.label)).toEqual([
      "Export Component...",
      "Open In...",
      "Reveal Component Files...",
    ]);
  });

  it("offers none of them on a host that owns no native window", () => {
    // Nothing there can reveal a folder or start an application. The items are absent, not
    // present and explaining themselves.
    expect(
      shellManageItems({ ...HOST_WITH_EVERYTHING, supported: false }, NOTHING),
    ).toEqual([]);
  });

  it("drops Export when the component has no CAD files, and Open In with it", () => {
    const items = shellManageItems(
      { ...HOST_WITH_EVERYTHING, export_formats: [] },
      NOTHING,
    );

    expect(items.map((item) => item.id)).toEqual(["reveal"]);
  });

  it("drops Open In when nothing that could read this component is installed", () => {
    const items = shellManageItems(
      { ...HOST_WITH_EVERYTHING, eda_applications: [] },
      NOTHING,
    );

    expect(items.map((item) => item.id)).toEqual(["export", "reveal"]);
  });

  it("drops Reveal when this component has no directory in the library yet", () => {
    const items = shellManageItems(
      { ...HOST_WITH_EVERYTHING, component_directory: false },
      NOTHING,
    );

    expect(items.map((item) => item.id)).toEqual(["export", "open-in"]);
  });

  it("offers an installed application only for a format this component really has", () => {
    // Altium Designer is installed and this component has no 3D model, so there is nothing here
    // for it to open. Listing it would be a menu entry that opens an empty folder.
    const shell: PartShell = { ...HOST_WITH_EVERYTHING, export_formats: ["kicad"] };

    expect(openableApplications(shell).map((item) => item.id)).toEqual(["kicad"]);
  });
});

describe("where the shell actions sit in the Manage menu", () => {
  it("places them after provenance and before the destructive item, which stays last", async () => {
    const user = userEvent.setup();
    const items = manageMenuItems({
      onEditIdentity: () => {},
      onEditClassification: () => {},
      onReviewMissing: () => {},
      onRefresh: () => {},
      refreshing: false,
      onReviewCadSources: () => {},
      onViewProvenance: () => {},
      onDelete: () => {},
      shellItems: shellManageItems(HOST_WITH_EVERYTHING, NOTHING),
    });
    provide(<ManageMenu items={items} />);
    await user.click(screen.getByRole("button", { name: /Manage/ }));

    expect(screen.getAllByRole("menuitem").map((node) => node.textContent)).toEqual([
      "Edit Identification...",
      "Edit Class and Classification...",
      "Review Missing Specifications...",
      "Refresh Component Data",
      "Review CAD Sources...",
      "View Data Provenance...",
      "Export Component...",
      "Open In...",
      "Reveal Component Files...",
      "Delete Component...",
    ]);
    const entries = screen.getAllByRole("menuitem");
    const last = entries[entries.length - 1];
    expect(last.textContent).toBe("Delete Component...");
    // Restrained red TEXT, never a filled control, and never larger or heavier than its siblings.
    expect(last.className).toContain("text-err-text");
    expect(last.className).not.toContain("bg-err");
    expect(last.className).not.toContain("font-semibold");
  });
});

describe("Export Component", () => {
  it("lists only the formats this component has files for", () => {
    provide(
      <ExportComponentDialog
        open
        shell={{ ...HOST_WITH_EVERYTHING, export_formats: ["step"] }}
        pending={null}
        onExport={() => {}}
        onClose={() => {}}
      />,
    );

    expect(screen.getByText("3D Model (STEP)")).toBeInTheDocument();
    expect(screen.queryByText("KiCad Library Files")).toBeNull();
  });

  it("says so plainly rather than showing an empty chooser", () => {
    provide(
      <ExportComponentDialog
        open
        shell={{ ...HOST_WITH_EVERYTHING, export_formats: [] }}
        pending={null}
        onExport={() => {}}
        onClose={() => {}}
      />,
    );

    expect(
      screen.getByText("This component has no CAD files to export so far."),
    ).toBeInTheDocument();
  });

  it("exports the format that was pressed", async () => {
    const user = userEvent.setup();
    const onExport = vi.fn();
    provide(
      <ExportComponentDialog
        open
        shell={{ ...HOST_WITH_EVERYTHING, export_formats: ["kicad"] }}
        pending={null}
        onExport={onExport}
        onClose={() => {}}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Export" }));

    expect(onExport).toHaveBeenCalledWith("kicad");
  });
});

describe("Open In", () => {
  it("names the applications this machine really has, and no others", () => {
    provide(
      <OpenInDialog
        open
        shell={HOST_WITH_EVERYTHING}
        pending={null}
        onOpen={() => {}}
        onClose={() => {}}
      />,
    );

    expect(screen.getByText("KiCad 9.0")).toBeInTheDocument();
    expect(screen.getByText("Altium Designer 25")).toBeInTheDocument();
  });

  it("states that nothing can open this component rather than offering a dead row", () => {
    provide(
      <OpenInDialog
        open
        shell={{ ...HOST_WITH_EVERYTHING, eda_applications: [] }}
        pending={null}
        onOpen={() => {}}
        onClose={() => {}}
      />,
    );

    expect(
      screen.getByText(
        "No application that can open this component is installed on this machine.",
      ),
    ).toBeInTheDocument();
  });

  it("opens the pressed application on the format it can read", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    provide(
      <OpenInDialog
        open
        shell={{
          ...HOST_WITH_EVERYTHING,
          export_formats: ["step"],
        }}
        pending={null}
        onOpen={onOpen}
        onClose={() => {}}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Open" }));

    expect(onOpen).toHaveBeenCalledWith("altium-designer", "step");
  });
});

describe("the wired pair, and the one token that says a process is out", () => {
  function provideWired(ui: ReactNode) {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={qc}>
        <ThemeProvider>
          <ToastProvider>{ui}</ToastProvider>
        </ThemeProvider>
      </QueryClientProvider>,
    );
  }

  /** The workspace's half of the contract: it decides WHICH dialog is up, and closes it. */
  function Host({ initial }: { initial: ShellDialog }) {
    const [open, setOpen] = useState<ShellDialog>(initial);
    return (
      <WorkspaceShellDialogs
        componentId="lm358"
        shell={HOST_WITH_EVERYTHING}
        open={open}
        onClose={() => setOpen(null)}
        onFailure={(error, fallback) => {
          void error;
          void fallback;
        }}
      />
    );
  }

  function exportRows(): HTMLButtonElement[] {
    return Array.from(
      document.querySelectorAll<HTMLButtonElement>(
        "[data-dev-id='component-browser.export-format']",
      ),
    );
  }

  it("disables the OTHER format while one export is out, instead of letting both start", async () => {
    const user = userEvent.setup();
    // Never resolves: the assertion is about the window between the press and the answer, which is
    // exactly the window the running token exists to cover.
    mockApi.exportPart.mockImplementation(() => new Promise(() => {}));
    provideWired(<Host initial="export" />);

    expect(exportRows()).toHaveLength(2);
    await user.click(exportRows()[0]);

    expect(exportRows()[0].textContent).toBe("Exporting");
    expect(exportRows()[1].textContent).toBe("Export");
    expect(exportRows()[0].disabled).toBe(true);
    expect(exportRows()[1].disabled).toBe(true);
  });

  it("closes and reports how many files were written when the export lands", async () => {
    const user = userEvent.setup();
    mockApi.exportPart.mockResolvedValue({
      part_id: "lm358",
      format: "kicad",
      file_count: 3,
      file_names: ["lm358.kicad_sym", "lm358.kicad_mod", "lm358.step"],
    });
    provideWired(<Host initial="export" />);

    await user.click(exportRows()[0]);

    expect(await screen.findByText("Component exported (3)")).toBeInTheDocument();
    await waitFor(() => expect(exportRows()).toHaveLength(0));
  });

  it("keeps the chooser up and the row pressable again when the export fails", async () => {
    const user = userEvent.setup();
    mockApi.exportPart.mockRejectedValue(new ApiError(500, "no"));
    provideWired(<Host initial="export" />);

    await user.click(exportRows()[0]);

    // Still open - a failed export must not look like a finished one - and the token is released,
    // so the same row can be tried again rather than being dead until the window is reopened.
    await waitFor(() => expect(exportRows()[0].textContent).toBe("Export"));
    expect(exportRows()[0].disabled).toBe(false);
    expect(exportRows()[1].disabled).toBe(false);
  });

  it("sends the pressed application, its readable format and this component to the host", async () => {
    const user = userEvent.setup();
    mockApi.openPartIn.mockResolvedValue({
      part_id: "lm358",
      application_id: "kicad",
      format: "kicad",
      opened: true,
    });
    provideWired(<Host initial="open-in" />);

    await user.click(screen.getAllByRole("button", { name: "Open" })[0]);

    expect(mockApi.openPartIn).toHaveBeenCalledWith({
      partId: "lm358",
      applicationId: "kicad",
      format: "kicad",
    });
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Open" })).toBeNull(),
    );
  });
});
