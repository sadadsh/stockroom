import {
  allCommands,
  navCommands,
  registerCommand,
  registeredCommands,
  unregisterCommand,
} from "./commands";
import { availableNav, type NavEntry } from "./nav";

describe("command registry", () => {
  it("derives a nav command for exactly the available destinations", () => {
    const ids = navCommands().map((c) => c.id).sort();
    // Every available destination is offered, and nothing else, so the palette can
    // never route to an unbuilt stub. Derive the expectation from NAV rather than a
    // hardcoded list so this stays honest as routes light up.
    const expected = availableNav().map((entry) => `nav.${entry.route}`).sort();
    expect(ids).toEqual(expected);
    // Built surfaces (including Projects, now shipped) are present.
    expect(ids).toContain("nav.components");
    expect(ids).toContain("nav.projects");
  });

  it("excludes an unavailable destination so the palette never routes to a stub", () => {
    // Every real route has shipped, so the live NAV has nothing unavailable to
    // exercise the guard. Inject a NAV with one unavailable entry: it must not
    // become a command. Load-bearing (drop the .filter(available) and this is red).
    const nav: NavEntry[] = [
      { route: "components", title: "Components", group: "primary", available: true },
      { route: "settings", title: "Settings", group: "foot", available: false },
    ];
    const ids = navCommands(nav).map((c) => c.id);
    expect(ids).toContain("nav.components");
    expect(ids).not.toContain("nav.settings");
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
