import { fireEvent, render, screen } from "@testing-library/react";
import { DropOverlay } from "./DropOverlay";

// pywebview sets `pywebviewFullPath` (the real filesystem path) on each dropped
// File; the overlay reads that, since the browser otherwise hides the path.
function fileWithPath(name: string, path: string): File {
  const f = new File(["x"], name);
  Object.defineProperty(f, "pywebviewFullPath", { value: path });
  return f;
}

describe("DropOverlay", () => {
  it("shows and hides the overlay as files are dragged over the window", () => {
    render(<DropOverlay onDrop={vi.fn()} />);
    expect(screen.queryByText("Drop to Add Parts")).not.toBeInTheDocument();

    fireEvent.dragEnter(window, { dataTransfer: { types: ["Files"], files: [] } });
    expect(screen.getByText("Drop to Add Parts")).toBeInTheDocument();

    fireEvent.dragLeave(window, { dataTransfer: { types: ["Files"] } });
    expect(screen.queryByText("Drop to Add Parts")).not.toBeInTheDocument();
  });

  it("hands the dropped native file paths to onDrop and hides", () => {
    const onDrop = vi.fn();
    render(<DropOverlay onDrop={onDrop} />);
    fireEvent.dragEnter(window, { dataTransfer: { types: ["Files"], files: [] } });

    fireEvent.drop(window, {
      dataTransfer: {
        types: ["Files"],
        files: [fileWithPath("part.zip", "/tmp/part.zip")],
      },
    });

    expect(onDrop).toHaveBeenCalledWith(["/tmp/part.zip"]);
    expect(screen.queryByText("Drop to Add Parts")).not.toBeInTheDocument();
  });

  it("ignores a drag that carries no files", () => {
    render(<DropOverlay onDrop={vi.fn()} />);
    fireEvent.dragEnter(window, { dataTransfer: { types: ["text/plain"] } });
    expect(screen.queryByText("Drop to Add Parts")).not.toBeInTheDocument();
  });
});
