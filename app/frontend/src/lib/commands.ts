/**
 * The command registry: the seam that unifies the rail and the Ctrl+K palette
 * (M6h). Every navigation and every app action is a command with a stable id, a
 * Title Case title, a group, and a run(). Navigation commands are derived from
 * NAV so the palette and the rail can never offer different destinations;
 * feature pages register their own action commands (e.g. "Wire KiCad") here.
 */
import { NAV } from "./nav";
import type { Route } from "./router";

export interface CommandContext {
  navigate: (route: Route) => void;
}

export interface Command {
  id: string;
  title: string;
  group: string;
  keywords?: string[];
  run: (ctx: CommandContext) => void | Promise<void>;
}

const registry = new Map<string, Command>();

export function registerCommand(cmd: Command): void {
  registry.set(cmd.id, cmd);
}

export function unregisterCommand(id: string): void {
  registry.delete(id);
}

export function registeredCommands(): Command[] {
  return [...registry.values()];
}

/** Navigation commands, always fresh from NAV's available destinations. */
export function navCommands(): Command[] {
  return NAV.filter((entry) => entry.available).map((entry) => ({
    id: `nav.${entry.route}`,
    title: `Go To ${entry.title}`,
    group: "Go To",
    keywords: [entry.route, entry.title],
    run: (ctx) => ctx.navigate(entry.route),
  }));
}

/** Everything the palette can run: navigation plus registered actions. */
export function allCommands(): Command[] {
  return [...navCommands(), ...registeredCommands()];
}
