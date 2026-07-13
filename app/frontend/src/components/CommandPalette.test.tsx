import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { PartSummary } from "../api/types";
import { RouterProvider, useRouter } from "../lib/router";
import { ThemeProvider } from "../lib/theme";
import { requestPart } from "../lib/partSelection";
import { CommandPalette } from "./CommandPalette";

vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return { ...actual, api: { listParts: vi.fn() } };
});

// Isolate the cross-page jump: assert requestPart fires without pulling in the
// Components page. onRequestedPart is unused here but exported by the module.
vi.mock("../lib/partSelection", () => ({
  requestPart: vi.fn(),
  onRequestedPart: vi.fn(() => () => {}),
}));

const mockApi = vi.mocked(api);
const mockRequestPart = vi.mocked(requestPart);

const LM358: PartSummary = {
  id: "lm358",
  display_name: "LM358",
  category: "ICs",
  mpn: "LM358DR",
  manufacturer: "Texas Instruments",
  is_complete: true,
  missing: [],
};
const R10K: PartSummary = {
  id: "r10k",
  display_name: "R 10k",
  category: "Passives",
  mpn: "RC0402-10K",
  manufacturer: "Yageo",
  is_complete: true,
  missing: [],
};

// A probe that exposes the active route so navigation is observable in the DOM,
// plus a focusable control outside the palette to test focus restore-on-close.
function RouteProbe() {
  const { route } = useRouter();
  return (
    <>
      <div data-testid="route">{route}</div>
      <button data-testid="outside">Outside</button>
    </>
  );
}

function renderPalette() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <RouterProvider>
          <RouteProbe />
          <CommandPalette />
        </RouterProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

async function open(user: ReturnType<typeof userEvent.setup>) {
  await user.keyboard("{Control>}k{/Control}");
  return screen.findByRole("dialog");
}

beforeEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  mockApi.listParts.mockResolvedValue({ parts: [LM358, R10K], count: 2 });
  mockRequestPart.mockClear();
});

describe("CommandPalette", () => {
  it("opens on Ctrl+K and lists every available destination plus the theme action, hiding unbuilt routes", async () => {
    const user = userEvent.setup();
    renderPalette();
    const dialog = await open(user);

    // Go To group: the rail's available destinations, prefix stripped.
    expect(within(dialog).getByText("Go To")).toBeInTheDocument();
    expect(within(dialog).getByText("Components")).toBeInTheDocument();
    expect(within(dialog).getByText("Ingest")).toBeInTheDocument();
    expect(within(dialog).getByText("Duplicates")).toBeInTheDocument();
    expect(within(dialog).getByText("Doctor")).toBeInTheDocument();
    expect(within(dialog).getByText("Settings")).toBeInTheDocument();
    // Unbuilt routes are never offered (they are not `available` in NAV).
    expect(within(dialog).queryByText("Projects")).toBeNull();
    // Actions group: the one global action.
    expect(within(dialog).getByText("Actions")).toBeInTheDocument();
    expect(within(dialog).getByText("Switch to Light Theme")).toBeInTheDocument();
  });

  it("closes again on a second Ctrl+K", async () => {
    const user = userEvent.setup();
    renderPalette();
    await open(user);
    await user.keyboard("{Control>}k{/Control}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("fuzzy-filters commands by what is typed", async () => {
    const user = userEvent.setup();
    renderPalette();
    await open(user);
    await user.type(screen.getByLabelText("Search Commands and Parts"), "settings");

    expect(screen.getByText("Settings")).toBeInTheDocument();
    expect(screen.queryByText("Components")).toBeNull();
    expect(screen.queryByText("Ingest")).toBeNull();
  });

  it("navigates when a destination command is clicked", async () => {
    const user = userEvent.setup();
    renderPalette();
    await open(user);
    await user.click(screen.getByText("Ingest"));

    expect(screen.getByTestId("route")).toHaveTextContent("ingest");
    // Running a command closes the palette.
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("moves the highlight with ArrowDown and ArrowUp, then Enter runs it", async () => {
    const user = userEvent.setup();
    renderPalette();
    await open(user);
    // Empty query: [Components, Ingest, Duplicates, Settings, Switch Theme].
    // Down, down, up lands back on Ingest (index 1). This is load-bearing for BOTH
    // arrows: a broken ArrowDown would keep the highlight on Components, and a
    // broken ArrowUp would leave it on Duplicates, so either regression routes
    // somewhere other than Ingest.
    await user.keyboard("{ArrowDown}{ArrowDown}{ArrowUp}{Enter}");
    expect(screen.getByTestId("route")).toHaveTextContent("ingest");
  });

  it("wraps ArrowUp from the first item to the last", async () => {
    const user = userEvent.setup();
    renderPalette();
    await open(user);
    // From the first item (Components), one ArrowUp wraps to the last item (the
    // theme action); running it flips the theme. A no-op or non-wrapping ArrowUp
    // would run Components instead and leave the theme unchanged.
    await user.keyboard("{ArrowUp}{Enter}");
    await waitFor(() =>
      expect(document.documentElement.dataset.theme).toBe("light"),
    );
  });

  it("finds parts by any field and jumps to the part on Components when picked", async () => {
    const user = userEvent.setup();
    renderPalette();
    await open(user);
    // A manufacturer query matches the part even though it is not the name.
    await user.type(screen.getByLabelText("Search Commands and Parts"), "yageo");

    expect(await screen.findByText("Parts")).toBeInTheDocument();
    const row = await screen.findByText("R 10k");
    await user.click(row);

    expect(mockRequestPart).toHaveBeenCalledWith("r10k");
    expect(screen.getByTestId("route")).toHaveTextContent("components");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("does not dump parts on an empty query (only commands show)", async () => {
    const user = userEvent.setup();
    renderPalette();
    await open(user);
    // The list loaded, but with no query there is no Parts section.
    await waitFor(() => expect(mockApi.listParts).toHaveBeenCalled());
    expect(screen.queryByText("Parts")).toBeNull();
    expect(screen.queryByText("LM358")).toBeNull();
  });

  it("shows a searching state (not 'no match') while the parts fetch is in flight", async () => {
    // Hold the parts fetch open so a parts-only query cannot resolve yet.
    let release!: (v: { parts: PartSummary[]; count: number }) => void;
    mockApi.listParts.mockReturnValue(
      new Promise((r) => {
        release = r;
      }),
    );
    const user = userEvent.setup();
    renderPalette();
    await open(user);
    // "yageo" matches no command, so parts are the only possible source; they are
    // still loading, so the honest-negative must not be shown yet.
    await user.type(screen.getByLabelText("Search Commands and Parts"), "yageo");
    expect(screen.getByText("Searching...")).toBeInTheDocument();
    expect(screen.queryByText("No commands or parts match.")).toBeNull();
    // Once the fetch resolves with a match, the real result replaces the spinner.
    release({ parts: [LM358, R10K], count: 2 });
    expect(await screen.findByText("R 10k")).toBeInTheDocument();
    expect(screen.queryByText("Searching...")).toBeNull();
  });

  it("restores focus to the previously focused element on close", async () => {
    const user = userEvent.setup();
    renderPalette();
    const outside = screen.getByTestId("outside");
    outside.focus();
    expect(outside).toHaveFocus();

    await open(user); // Ctrl+K captures the prior focus and moves it to the input
    expect(screen.getByLabelText("Search Commands and Parts")).toHaveFocus();

    await user.keyboard("{Escape}");
    await waitFor(() => expect(outside).toHaveFocus());
  });

  it("traps Tab so focus cannot escape to the background", async () => {
    const user = userEvent.setup();
    renderPalette();
    await open(user);
    const input = screen.getByLabelText("Search Commands and Parts");
    expect(input).toHaveFocus();
    // Tab is trapped (the results are arrow-driven), so focus stays on the input
    // rather than leaking to the inert "Outside" button behind the scrim.
    await user.tab();
    expect(input).toHaveFocus();
    expect(screen.getByTestId("outside")).not.toHaveFocus();
  });

  it("shows an honest error (not 'no match') when the parts fetch fails", async () => {
    mockApi.listParts.mockRejectedValue(new Error("boom"));
    const user = userEvent.setup();
    renderPalette();
    await open(user);
    // A parts-only query whose fetch failed must not masquerade as "no match".
    await user.type(screen.getByLabelText("Search Commands and Parts"), "yageo");
    expect(await screen.findByText("Could not load parts.")).toBeInTheDocument();
    expect(screen.queryByText("No commands or parts match.")).toBeNull();
  });

  it("shows an honest empty state when nothing matches", async () => {
    const user = userEvent.setup();
    renderPalette();
    await open(user);
    await user.type(screen.getByLabelText("Search Commands and Parts"), "zzzqzzq");
    expect(screen.getByText("No commands or parts match.")).toBeInTheDocument();
    // Enter on an empty result set is a safe no-op (no crash, palette stays open).
    await user.keyboard("{Enter}");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("runs the theme toggle and then offers the opposite theme", async () => {
    const user = userEvent.setup();
    renderPalette();
    await open(user);
    await user.click(screen.getByText("Switch to Light Theme"));

    await waitFor(() =>
      expect(document.documentElement.dataset.theme).toBe("light"),
    );
    // Reopen: the action now offers the other direction.
    await open(user);
    expect(screen.getByText("Switch to Dark Theme")).toBeInTheDocument();
    expect(screen.queryByText("Switch to Light Theme")).toBeNull();
  });

  it("closes on Escape and on a scrim click", async () => {
    const user = userEvent.setup();
    renderPalette();
    await open(user);
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    // And a click on the backdrop scrim also dismisses it.
    const dialog = await open(user);
    const scrim = dialog.parentElement as HTMLElement;
    await user.click(scrim);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});
