/**
 * The Manage menu's three shell actions, as a surface contract.
 *
 * Every assertion here is about ABSENCE. The three items only exist when this machine can perform
 * them, and the whole reason they were missing for so long is that offering them without a bridge
 * would have meant three menu entries that open nothing. A dead click path is worse than an
 * absent one, so what is proved below is that nothing is drawn speculatively.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { PartShell } from "../../api/types";
import { ThemeProvider } from "../../lib/theme";
import { manageMenuItems, ManageMenu } from "./ManageMenu";
import {
  ExportComponentDialog,
  OpenInDialog,
  openableApplications,
  shellManageItems,
} from "./ShellActions";

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
      "Edit Identity...",
      "Edit Category and Classification...",
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
    expect(last.className).toContain("text-err");
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
      screen.getByText("This component has no CAD files to export yet."),
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
