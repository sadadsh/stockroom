import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AddPartProvider, useAddPart } from "./addPart";
import {
  defaultUiSession,
  readUiSession,
  resetUiSessionForTests,
} from "./uiSession";

function Probe() {
  const add = useAddPart();
  return (
    <>
      <span data-testid="state">{add.isOpen ? "open" : "closed"}</span>
      <button type="button" onClick={add.open}>Open</button>
      <button type="button" onClick={add.close}>Close</button>
    </>
  );
}

describe("Add Part session continuity", () => {
  it("restores and clears the server-owned open surface", async () => {
    const session = defaultUiSession();
    session.open_surface = "add_part";
    resetUiSessionForTests(session);
    render(
      <AddPartProvider>
        <Probe />
      </AddPartProvider>,
    );

    expect(screen.getByTestId("state")).toHaveTextContent("open");
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.getByTestId("state")).toHaveTextContent("closed");
    expect(readUiSession().open_surface).toBeNull();
  });
});
