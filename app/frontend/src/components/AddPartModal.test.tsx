import { render, screen, within, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AddPartModal } from "./AddPartModal";
import { AddPartProvider, useAddPart } from "../lib/addPart";
import { ThemeProvider } from "../lib/theme";
import { DevModeProvider } from "../lib/devMode";

// The modal hosts the whole Add A Part flow, which has its own suite; here we only
// check the modal's open/close contract.
vi.mock("../pages/IngestPage", () => ({
  IngestPage: () => <div data-testid="flow" />,
}));

function Harness() {
  const { open } = useAddPart();
  return (
    <>
      <button onClick={open}>trigger</button>
      <AddPartModal />
    </>
  );
}

function wrap() {
  return render(
    <AddPartProvider>
      <Harness />
    </AddPartProvider>,
  );
}

async function openModal(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "trigger" }));
  return screen.getByRole("dialog", { name: "Add a Part" });
}

describe("AddPartModal", () => {
  it("stays closed until opened, then shows the flow in a dialog", async () => {
    wrap();
    const user = userEvent.setup();
    expect(screen.queryByRole("dialog")).toBeNull();
    await openModal(user);
    expect(screen.getByTestId("flow")).toBeInTheDocument();
  });

  it("closes on the Close button", async () => {
    wrap();
    const user = userEvent.setup();
    const dialog = await openModal(user);
    await user.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("closes on Escape", async () => {
    wrap();
    const user = userEvent.setup();
    await openModal(user);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

// The copy/icon shell, exercised under ThemeProvider + DevModeProvider so dev mode can toggle.
function wrapDev() {
  return render(
    <ThemeProvider>
      <DevModeProvider>
        <AddPartProvider>
          <Harness />
        </AddPartProvider>
      </DevModeProvider>
    </ThemeProvider>,
  );
}

function toggleDevMode() {
  fireEvent.keyDown(window, { key: "D", ctrlKey: true, shiftKey: true });
}

describe("AddPartModal - copy + icon adoption", () => {
  it("shows the title text and a Close glyph, with no copy wrappers outside dev mode", async () => {
    const { container } = wrapDev();
    const user = userEvent.setup();
    const dialog = await openModal(user);

    // Title resolves to its default text (no override); the Close button keeps its accessible name
    // (useText) and draws an svg via <Icon id="action.close">.
    expect(within(dialog).getByText("Add a Part")).toBeInTheDocument();
    const close = within(dialog).getByRole("button", { name: "Close" });
    expect(close.querySelector("svg")).not.toBeNull();

    // Off dev mode a <Text> is a bare string: no editable copy targets exist.
    expect(container.querySelector("[data-copy-id]")).toBeNull();
  });

  it("wraps the title as an editable data-copy-id target in dev mode", async () => {
    const { container } = wrapDev();
    const user = userEvent.setup();
    await openModal(user);

    toggleDevMode();

    expect(container.querySelector('[data-copy-id="modal.addPart.title"]')).not.toBeNull();
    // The Close accessible name still resolves through useText with dev mode on.
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
  });
});
