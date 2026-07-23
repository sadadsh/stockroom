import { createElement, type ReactNode } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeProvider } from "../lib/theme";
import { DevModeProvider } from "../lib/devMode";
import { ConfirmDialog } from "./ConfirmDialog";

const base = {
  title: "Delete This Part?",
  body: "This cannot be undone easily.",
  confirmLabel: "Delete",
};

// Dev mode reads the theme + copy providers; wrap so <Text> can become click-to-edit.
function devWrapper({ children }: { children: ReactNode }) {
  return createElement(ThemeProvider, null, createElement(DevModeProvider, null, children));
}

function toggleDevMode() {
  fireEvent.keyDown(window, { key: "D", ctrlKey: true, shiftKey: true });
}

describe("ConfirmDialog", () => {
  it("renders nothing when closed", () => {
    const { container } = render(
      <ConfirmDialog {...base} open={false} onConfirm={vi.fn()} onCancel={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("confirms when the confirm button is clicked", async () => {
    const onConfirm = vi.fn();
    render(
      <ConfirmDialog {...base} open danger onConfirm={onConfirm} onCancel={vi.fn()} />,
    );
    await userEvent.setup().click(screen.getByRole("button", { name: "Delete" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("cancels on the Cancel button and on Escape", async () => {
    const onCancel = vi.fn();
    render(
      <ConfirmDialog {...base} open onConfirm={vi.fn()} onCancel={onCancel} />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await user.keyboard("{Escape}");
    expect(onCancel).toHaveBeenCalledTimes(2);
  });

  it("keeps the Cancel button's accessible name outside dev mode with no copy wrapper", () => {
    const { container } = render(
      <ConfirmDialog {...base} open onConfirm={vi.fn()} onCancel={vi.fn()} />,
    );
    // Off dev mode a <Text> is a bare string: the button still reads "Cancel" and no editable
    // copy target exists.
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
    expect(container.querySelector("[data-copy-id]")).toBeNull();
  });

  it("wraps the Cancel label as an editable data-copy-id target in dev mode", () => {
    const { container } = render(
      <ConfirmDialog {...base} open onConfirm={vi.fn()} onCancel={vi.fn()} />,
      { wrapper: devWrapper },
    );
    toggleDevMode();
    // The static Cancel label carries its modals.json id; the Delete label is a caller prop and is
    // wrapped at its call site, not here.
    expect(container.querySelector('[data-copy-id="modal.confirm.cancel"]')).not.toBeNull();
    // The accessible name is unchanged - the <Text> span sits inside the button.
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
  });
});
