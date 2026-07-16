import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AddPartModal } from "./AddPartModal";
import { AddPartProvider, useAddPart } from "../lib/addPart";

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
