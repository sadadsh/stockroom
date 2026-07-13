/**
 * The Ctrl+K command palette: one keystroke from anywhere to every destination,
 * every registered action, and every part. It is the same seam the rail uses -
 * `allCommands()` (navigation derived from NAV plus registered actions) - so the
 * palette can never offer a destination the rail cannot. Parts come from the warm
 * library index and are fuzzy-matched over their name, MPN, manufacturer, and
 * category; picking one jumps to Components and selects it (via partSelection).
 *
 * It lives in-window like every other surface (the ConfirmDialog scrim idiom): no
 * OS window, Escape or a scrim click closes, and it is fully keyboard-drivable
 * (up/down to move, Enter to run, Ctrl+K to toggle). The one genuinely global
 * action - the theme toggle - is registered here so the palette is useful on its
 * own and to establish the action-registration seam feature pages will reuse.
 */
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { PartSummary } from "../api/types";
import {
  allCommands,
  registerCommand,
  unregisterCommand,
  type Command,
} from "../lib/commands";
import { fuzzyScoreFields } from "../lib/fuzzy";
import { requestPart } from "../lib/partSelection";
import { useRouter } from "../lib/router";
import { useTheme } from "../lib/theme";
import { SearchIcon } from "./icons";

type FlatItem =
  | { kind: "command"; cmd: Command; label: string }
  | { kind: "part"; part: PartSummary };

interface Section {
  title: string;
  items: FlatItem[];
}

const PART_LIMIT = 8;

// A nav command titled "Go To Components" sits under the "Go To" header, so drop
// the redundant group prefix from the row label while keeping the registry title
// self-describing everywhere else it is used.
function rowLabel(cmd: Command): string {
  const prefix = cmd.group + " ";
  return cmd.title.startsWith(prefix) ? cmd.title.slice(prefix.length) : cmd.title;
}

export function CommandPalette() {
  const { navigate } = useRouter();
  const { theme, toggle } = useTheme();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // Register the one genuinely global action. Its title tracks the current theme
  // (offer the theme you are not on), so re-register when the theme flips; drop it
  // on unmount so the registry does not leak the command.
  useEffect(() => {
    registerCommand({
      id: "action.toggle-theme",
      title: theme === "dark" ? "Switch to Light Theme" : "Switch to Dark Theme",
      group: "Actions",
      keywords: ["theme", "appearance", "dark", "light", "mode"],
      run: () => toggle(),
    });
    return () => unregisterCommand("action.toggle-theme");
  }, [theme, toggle]);

  // The global open/close shortcut. Ctrl+K (or Cmd+K on mac) toggles from any
  // surface; preventDefault stops a browser default so the palette owns the key.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K")) {
        e.preventDefault();
        setOpen((v) => !v);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Fresh every open: clear the query, reset the highlight, and focus the input.
  useEffect(() => {
    if (!open) return;
    setQuery("");
    setActive(0);
    inputRef.current?.focus();
  }, [open]);

  // A new query re-ranks everything, so the highlight returns to the top match.
  useEffect(() => {
    setActive(0);
  }, [query]);

  // The full library list, fetched only while the palette is open and cache-shared
  // with the Components page (same query key), so opening it on Components is free.
  const partsQuery = useQuery({
    queryKey: ["parts", "", "", false],
    queryFn: () => api.listParts({}),
    enabled: open,
  });

  const q = query.trim();

  const sections = useMemo<Section[]>(() => {
    // Score every command over its title and keywords; an empty query keeps them
    // all (score 0) so a just-opened palette shows the full menu.
    const scoredCommands = allCommands()
      .map((cmd) => ({
        cmd,
        score: fuzzyScoreFields(q, [cmd.title, ...(cmd.keywords ?? [])]),
      }))
      .filter((x): x is { cmd: Command; score: number } => x.score !== null);

    // Group commands, preserving the order each group first appears (nav "Go To"
    // comes before registered "Actions"), and sort within a group by score.
    const order: string[] = [];
    const byGroup = new Map<string, { cmd: Command; score: number }[]>();
    for (const entry of scoredCommands) {
      if (!byGroup.has(entry.cmd.group)) {
        byGroup.set(entry.cmd.group, []);
        order.push(entry.cmd.group);
      }
      byGroup.get(entry.cmd.group)!.push(entry);
    }
    const out: Section[] = order.map((name) => ({
      title: name,
      items: byGroup
        .get(name)!
        .slice()
        .sort((a, b) => b.score - a.score)
        .map(
          (e): FlatItem => ({ kind: "command", cmd: e.cmd, label: rowLabel(e.cmd) }),
        ),
    }));

    // Parts only surface once there is something to match; dumping the whole
    // library on an empty query would bury the commands.
    if (q) {
      const parts = (partsQuery.data?.parts ?? [])
        .map((part) => ({
          part,
          score: fuzzyScoreFields(q, [
            part.display_name,
            part.mpn,
            part.manufacturer,
            part.category,
          ]),
        }))
        .filter((x): x is { part: PartSummary; score: number } => x.score !== null)
        .sort((a, b) => b.score - a.score)
        .slice(0, PART_LIMIT)
        .map((e): FlatItem => ({ kind: "part", part: e.part }));
      if (parts.length) out.push({ title: "Parts", items: parts });
    }
    return out;
  }, [q, open, partsQuery.data]);

  const flat = useMemo(() => sections.flatMap((s) => s.items), [sections]);

  // Keep the highlight in range as results shrink, and scroll it into view.
  useEffect(() => {
    if (active > flat.length - 1) setActive(flat.length ? flat.length - 1 : 0);
  }, [flat.length, active]);
  useEffect(() => {
    if (!open) return;
    const el = listRef.current?.querySelector(`[data-index="${active}"]`);
    if (el && "scrollIntoView" in el) {
      (el as HTMLElement).scrollIntoView({ block: "nearest" });
    }
  }, [active, open]);

  function runItem(item: FlatItem) {
    if (item.kind === "command") {
      item.cmd.run({ navigate });
    } else {
      requestPart(item.part.id);
      navigate("components");
    }
    setOpen(false);
  }

  function onInputKeyDown(e: ReactKeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => (flat.length ? (i + 1) % flat.length : 0));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => (flat.length ? (i - 1 + flat.length) % flat.length : 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const item = flat[active];
      if (item) runItem(item);
    } else if (e.key === "Escape") {
      e.preventDefault();
      setOpen(false);
    }
  }

  if (!open) return null;

  // A running index so hover/click and the active highlight share one coordinate
  // across every section.
  let cursor = -1;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-start justify-center bg-black/50 p-4 pt-[12vh]"
      role="presentation"
      onClick={() => setOpen(false)}
    >
      <div
        className="w-full max-w-[560px] overflow-hidden rounded-card border border-line bg-raise shadow-pop"
        role="dialog"
        aria-modal="true"
        aria-label="Command Palette"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex h-[46px] items-center gap-2.5 border-b border-line px-4">
          <SearchIcon className="flex-none text-t3" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onInputKeyDown}
            placeholder="Search Commands and Parts"
            aria-label="Search Commands and Parts"
            role="combobox"
            aria-expanded="true"
            aria-controls="palette-list"
            aria-activedescendant={flat.length ? `palette-opt-${active}` : undefined}
            className="min-w-0 flex-1 bg-transparent text-sm text-t1 outline-none placeholder:text-t3"
          />
        </div>

        <div
          ref={listRef}
          id="palette-list"
          role="listbox"
          aria-label="Commands and Parts"
          className="max-h-[52vh] overflow-y-auto py-2"
        >
          {flat.length === 0 ? (
            <div className="px-4 py-6 text-center text-sm text-t3">
              No commands or parts match.
            </div>
          ) : (
            sections.map((section) => (
              <div key={section.title} className="mb-1">
                <div className="px-4 pb-1 pt-2 text-[11px] font-semibold text-t3">
                  {section.title}
                </div>
                {section.items.map((item) => {
                  cursor += 1;
                  const index = cursor;
                  const isActive = index === active;
                  return (
                    <div
                      key={
                        item.kind === "command"
                          ? item.cmd.id
                          : `part-${item.part.id}`
                      }
                      id={`palette-opt-${index}`}
                      data-index={index}
                      role="option"
                      aria-selected={isActive}
                      onMouseMove={() => setActive(index)}
                      onClick={() => runItem(item)}
                      className={
                        "flex h-[34px] cursor-pointer items-center gap-2.5 px-4 text-sm " +
                        (isActive ? "bg-raise2 text-t1" : "text-t2")
                      }
                    >
                      {item.kind === "command" ? (
                        <span className="min-w-0 flex-1 truncate">{item.label}</span>
                      ) : (
                        <>
                          <span className="min-w-0 flex-1 truncate text-t1">
                            {item.part.display_name}
                          </span>
                          {item.part.mpn ? (
                            <span className="tnum flex-none font-mono text-2xs text-t3">
                              {item.part.mpn}
                            </span>
                          ) : null}
                        </>
                      )}
                    </div>
                  );
                })}
              </div>
            ))
          )}
        </div>

        <div className="flex h-[34px] items-center gap-4 border-t border-line px-4 text-2xs text-t3">
          <span>Up and Down to Navigate</span>
          <span>Enter to Open</span>
          <span className="ml-auto">Esc to Close</span>
        </div>
      </div>
    </div>
  );
}
