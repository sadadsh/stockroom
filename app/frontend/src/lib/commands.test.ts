import {
  allCommands,
  navCommands,
  registerCommand,
  registeredCommands,
  unregisterCommand,
} from "./commands";

describe("command registry", () => {
  it("derives a nav command only for available destinations", () => {
    const ids = navCommands().map((c) => c.id);
    expect(ids).toContain("nav.components");
    // Unbuilt surfaces are not offered, so the palette can never route to a stub.
    expect(ids).not.toContain("nav.ingest");
  });

  it("a nav command navigates to its route when run", () => {
    const navigate = vi.fn();
    const cmd = navCommands().find((c) => c.id === "nav.components");
    cmd?.run({ navigate });
    expect(navigate).toHaveBeenCalledWith("components");
  });

  it("registers, lists, and unregisters action commands", () => {
    const cmd = { id: "test.act", title: "Do A Thing", group: "Actions", run: () => {} };
    registerCommand(cmd);
    expect(allCommands().map((c) => c.id)).toContain("test.act");
    unregisterCommand("test.act");
    expect(registeredCommands().map((c) => c.id)).not.toContain("test.act");
  });
});
