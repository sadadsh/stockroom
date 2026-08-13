/**
 * The Interface Studio against DYNAMIC ids: the half the catalogue cannot describe.
 *
 * Search has to find an id that belongs to a record rather than to a list; Copy ID has to hand back
 * that id verbatim, brackets and all, because it is the string an override is keyed on; and jump has
 * to land on the exact instance rather than on the first sibling that looks similar.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ThemeProvider } from "../lib/theme";
import { DevModeProvider } from "../lib/devMode";
import { CANDIDATE_ROLE, candidateDevId, componentTabDevId } from "../lib/componentDevIds";
import { DevPanel } from "./DevPanel";
import { DevInspector } from "./DevInspector";

vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      devSave: vi.fn().mockResolvedValue({ ok: true, written: [], tokens: 0, copy: 0 }),
      devStatus: vi.fn().mockResolvedValue({
        available: true,
        branch: "main",
        revision: "a".repeat(40),
        dirty: [],
        can_publish: false,
        publish_blocker: "Save a Dev Mode change before publishing.",
      }),
    },
  };
});

const scrollIntoViewMock = vi.fn();
const writeText = vi.fn().mockResolvedValue(undefined);

beforeEach(() => {
  scrollIntoViewMock.mockClear();
  writeText.mockClear();
  HTMLElement.prototype.scrollIntoView = scrollIntoViewMock;
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText },
    configurable: true,
  });
});

afterEach(() => {
  document.documentElement.removeAttribute("style");
  document.documentElement.removeAttribute("data-theme");
});

// Two repeated families with per-instance ids: three staged candidate cards (which also declare a
// shared role) and two open-component tabs.
const CANDIDATES = ["stm32h743vit6", "tpd6e05u06rvzr", "rc0402fr-07100rl"];

function Harness() {
  return (
    <ThemeProvider>
      <DevModeProvider>
        <div className="flex flex-col">
          {CANDIDATES.map((id) => (
            <div
              key={id}
              data-dev-id={candidateDevId(id)}
              data-dev-role={CANDIDATE_ROLE}
              className="text-t1"
            >
              {id}
            </div>
          ))}
        </div>
        <div data-dev-id="component-browser.tabs" className="flex">
          <button type="button" data-dev-id={componentTabDevId("stm32h743vit6")}>
            Tab One
          </button>
          <button type="button" data-dev-id={componentTabDevId("tpd6e05u06rvzr")}>
            Tab Two
          </button>
        </div>
        <DevPanel />
        <DevInspector />
      </DevModeProvider>
    </ThemeProvider>
  );
}

function toggleDevMode() {
  fireEvent.keyDown(window, { key: "D", ctrlKey: true, shiftKey: true });
}

function openCatalogue() {
  fireEvent.click(screen.getByRole("button", { name: /Catalogue/ }));
}

function search(term: string) {
  fireEvent.change(screen.getByLabelText("Search ids"), { target: { value: term } });
}

function inspectClick(el: Element) {
  fireEvent.click(screen.getByRole("button", { name: "Edit" }));
  fireEvent.click(el);
}

describe("Dev Mode search finds live dynamic ids", () => {
  it("lists the ids currently rendered, not just the catalogue", () => {
    render(<Harness />);
    toggleDevMode();
    openCatalogue();
    const live = screen.getByTestId("dev-live-ids");
    for (const id of CANDIDATES) {
      expect(within(live).getByText(candidateDevId(id))).toBeInTheDocument();
    }
    expect(within(live).getByText(componentTabDevId("stm32h743vit6"))).toBeInTheDocument();
  });

  it("narrows the live list by the same search box as the catalogue", () => {
    render(<Harness />);
    toggleDevMode();
    openCatalogue();
    search("tpd6e05");
    const live = screen.getByTestId("dev-live-ids");
    expect(within(live).getByText(candidateDevId("tpd6e05u06rvzr"))).toBeInTheDocument();
    expect(within(live).queryByText(candidateDevId("stm32h743vit6"))).not.toBeInTheDocument();
    // The catalogue half of the same search still works: this term matches no catalogue row.
    expect(screen.queryByText("components.row")).not.toBeInTheDocument();
  });

  it("finds a catalogue id and a live id from one search box", () => {
    render(<Harness />);
    toggleDevMode();
    openCatalogue();
    search("candidate");
    expect(screen.getByText("ingest.candidate")).toBeInTheDocument();
    const live = screen.getByTestId("dev-live-ids");
    expect(within(live).getByText(candidateDevId("stm32h743vit6"))).toBeInTheDocument();
  });
});

describe("jump to element targets the exact instance", () => {
  it("selects and flashes the named instance, never the first sibling", () => {
    render(<Harness />);
    toggleDevMode();
    openCatalogue();
    const target = candidateDevId("rc0402fr-07100rl");
    fireEvent.click(within(screen.getByTestId("dev-live-ids")).getByText(target));

    expect(screen.getByTestId("dev-selected-id")).toHaveTextContent(target);
    // The flash outline is on the named node and on nothing else.
    const flashed = document.querySelectorAll("[data-dev-id][style*='outline']");
    expect(flashed).toHaveLength(1);
    expect(flashed[0].getAttribute("data-dev-id")).toBe(target);
  });
});

describe("Copy ID returns the exact id", () => {
  it("copies a dynamic instance id verbatim, brackets included", async () => {
    render(<Harness />);
    toggleDevMode();
    const second = document.querySelector(
      `[data-dev-id="${candidateDevId("tpd6e05u06rvzr")}"]`,
    )!;
    inspectClick(second);

    fireEvent.click(screen.getByRole("button", { name: "Copy ID" }));
    expect(writeText).toHaveBeenCalledWith(candidateDevId("tpd6e05u06rvzr"));
    expect(await screen.findByRole("button", { name: "Copy ID" })).toHaveTextContent("Copied");
  });
});

describe("hover and inspect show the exact id", () => {
  it("names the hovered instance and borrows its role's label", () => {
    render(<Harness />);
    toggleDevMode();
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    const third = document.querySelector(
      `[data-dev-id="${candidateDevId("rc0402fr-07100rl")}"]`,
    )!;
    fireEvent.pointerMove(third);

    const badge = screen.getByTestId("dev-hover");
    expect(within(badge).getByText(candidateDevId("rc0402fr-07100rl"))).toBeInTheDocument();
    expect(within(badge).getByText("Staged candidate card (one instance)")).toBeInTheDocument();
  });
});

describe("the Box tab writes under the contract the person chose", () => {
  it("edits this instance by default, and every one of these on request", () => {
    render(<Harness />);
    toggleDevMode();
    const second = document.querySelector(
      `[data-dev-id="${candidateDevId("tpd6e05u06rvzr")}"]`,
    )!;
    inspectClick(second);
    fireEvent.click(screen.getByRole("tab", { name: "Box" }));

    // Default scope: this one. The width lands on the selected card only.
    fireEvent.change(screen.getByLabelText("Width value"), { target: { value: "240px" } });
    expect((second as HTMLElement).style.getPropertyValue("width")).toBe("240px");
    const first = document.querySelector(
      `[data-dev-id="${candidateDevId("stm32h743vit6")}"]`,
    ) as HTMLElement;
    expect(first.style.getPropertyValue("width")).toBe("");

    // Switch the contract: the same field now writes the shared role, so every card moves.
    fireEvent.click(screen.getByRole("button", { name: "Every One Of These" }));
    fireEvent.change(screen.getByLabelText("Padding value"), { target: { value: "8px" } });
    for (const id of CANDIDATES) {
      const node = document.querySelector(`[data-dev-id="${candidateDevId(id)}"]`) as HTMLElement;
      expect(node.style.getPropertyValue("padding")).toBe("8px");
    }
    // The instance edit is still exactly where it was.
    expect((second as HTMLElement).style.getPropertyValue("width")).toBe("240px");
    expect(first.style.getPropertyValue("width")).toBe("");
  });

  it("marks a value the writer would reject instead of pretending it applied", () => {
    render(<Harness />);
    toggleDevMode();
    const card = document.querySelector(
      `[data-dev-id="${candidateDevId("stm32h743vit6")}"]`,
    ) as HTMLElement;
    inspectClick(card);
    fireEvent.click(screen.getByRole("tab", { name: "Box" }));

    const width = screen.getByLabelText("Width value");
    fireEvent.change(width, { target: { value: "240" } });
    expect(width).toHaveAttribute("aria-invalid", "true");
    expect(card.style.getPropertyValue("width")).toBe("");

    fireEvent.change(width, { target: { value: "240px" } });
    expect(width).not.toHaveAttribute("aria-invalid");
    expect(card.style.getPropertyValue("width")).toBe("240px");
  });
});
