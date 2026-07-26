/**
 * Tests for the Library Version section.
 *
 * PRIOR ART: no new test infrastructure. This uses the harness the repo already standardises on
 * (vitest + @testing-library/react + a per-test QueryClient and the real ToastProvider), and the
 * fixture/mock shape is copied from `LibraryHealthSection.test.tsx` so both read the same.
 * REJECTED: a shared render helper extracted across component tests, because the existing files
 * each keep their own three-line `renderSection`, and one more instance is not yet a pattern worth
 * hoisting into a helper every test then has to be read through.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../api/client";
import type { LibraryPinRead, LibraryPinStatus } from "../api/types";
import { ToastProvider } from "../lib/toast";
import { LibraryVersionSection } from "./LibraryVersionSection";

vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return {
    ...actual,
    api: { getLibraryPin: vi.fn(), setLibraryPin: vi.fn() },
  };
});

const mockApi = vi.mocked(api);

function read(over: Partial<LibraryPinRead> = {}): LibraryPinRead {
  return {
    project: "Board",
    eda: "kicad",
    under_git: true,
    pinned: {
      schema: 1,
      profile: "Stockroom",
      remote: "https://github.com/sadadsh/stockroom.git",
      commit: "a1b2c3d4e5f6a7b8c9d0a1b2c3d4e5f6a7b8c9d0",
      pinned_at: "2026-07-20T10:00:00+00:00",
    },
    path_contract: {
      kind: "env_var",
      variable: "SR_LIB",
      config_file: "kicad_common.json",
      prefix: "${SR_LIB}/",
      description: "KiCad resolves every Stockroom library reference through the SR_LIB variable.",
    },
    status: "match",
    detail: "This machine's library is at exactly the commit this project is pinned to.",
    remedy: "Nothing to do.",
    severity: "ok",
    ahead: 0,
    behind: 0,
    library_commit: "a1b2c3d4e5f6a7b8c9d0a1b2c3d4e5f6a7b8c9d0",
    library_short: "a1b2c3d",
    library_remote: "https://github.com/sadadsh/stockroom.git",
    library_profile: "Stockroom",
    ...over,
  };
}

function renderSection() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <LibraryVersionSection projectId="board" />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

it("shows both versions and no action when the pin already matches this machine", async () => {
  mockApi.getLibraryPin.mockResolvedValue(read());
  renderSection();

  expect(await screen.findByTestId("pin-status")).toHaveTextContent("In Sync");
  expect(screen.getByTestId("pin-pinned-sha")).toHaveTextContent("a1b2c3d");
  expect(screen.getByTestId("pin-local-sha")).toHaveTextContent("a1b2c3d");
  // nothing to do, so nothing is offered: a button that changes nothing is noise
  expect(screen.queryByTestId("pin-apply")).toBeNull();
});

it("offers to pin a project that has never been pinned", async () => {
  mockApi.getLibraryPin.mockResolvedValue(
    read({
      pinned: null,
      status: "unpinned",
      severity: "notice",
      detail: "This project does not record which library version it was resolved against.",
      remedy: "Pin the library to record the version this project currently resolves against.",
    }),
  );
  mockApi.setLibraryPin.mockResolvedValue({
    project: "Board",
    pinned: {
      schema: 1,
      profile: "Stockroom",
      remote: "",
      commit: "a1b2c3d4e5f6a7b8c9d0a1b2c3d4e5f6a7b8c9d0",
      pinned_at: "2026-07-25T06:00:00+00:00",
    },
    committed: "deadbee",
  });
  renderSection();

  expect(await screen.findByTestId("pin-pinned-sha")).toHaveTextContent("None");
  await userEvent.click(screen.getByTestId("pin-apply"));
  await waitFor(() => expect(mockApi.setLibraryPin).toHaveBeenCalledWith("board"));
  expect(await screen.findByText(/Pinned to library a1b2c3d/)).toBeInTheDocument();
});

it("counts how far the library has moved on since the pin", async () => {
  mockApi.getLibraryPin.mockResolvedValue(
    read({
      status: "library_ahead",
      severity: "notice",
      ahead: 4,
      library_commit: "ffffffffffffffffffffffffffffffffffffffff",
      detail: "The library has moved on since this project was pinned.",
      remedy: "Re-check the project against the current library, then update the pin.",
    }),
  );
  renderSection();

  expect(await screen.findByTestId("pin-delta")).toHaveTextContent("4 newer");
  expect(screen.getByTestId("pin-apply")).toHaveTextContent("Update Pin");
});

it("NEVER offers to pin when this machine's library is older than the pin", async () => {
  /**
   * The correctness property of the whole surface. Pinning here would move the pin BACKWARDS onto
   * a library that is missing the parts the project references, while looking like a fix. The
   * remedy is to pull, and that is all the surface may say.
   */
  mockApi.getLibraryPin.mockResolvedValue(
    read({
      status: "library_behind",
      severity: "problem",
      behind: 3,
      library_commit: "0000000000000000000000000000000000000000",
      detail: "This machine's library is OLDER than the version this project expects.",
      remedy: "Pull the library so this machine has the version the project was built against.",
    }),
  );
  renderSection();

  expect(await screen.findByTestId("pin-status")).toHaveTextContent("Library Behind");
  expect(screen.getByTestId("pin-delta")).toHaveTextContent("3 missing");
  expect(screen.queryByTestId("pin-apply")).toBeNull();
  expect(screen.getByTestId("pin-remedy")).toHaveTextContent("Pull the library");
});

it("does not offer to pin a commit this machine has never seen either", async () => {
  mockApi.getLibraryPin.mockResolvedValue(
    read({
      status: "unknown_commit",
      severity: "problem",
      detail: "This machine's library does not contain the commit the project is pinned to.",
      remedy: "Fetch the library from its remote, then re-check this project.",
    }),
  );
  renderSection();
  expect(await screen.findByTestId("pin-status")).toHaveTextContent("Version Missing");
  expect(screen.queryByTestId("pin-apply")).toBeNull();
});

it("says a project outside git can never share a pin, and disables the action", async () => {
  mockApi.getLibraryPin.mockResolvedValue(
    read({ under_git: false, pinned: null, status: "unpinned", severity: "notice" }),
  );
  renderSection();
  expect(await screen.findByTestId("pin-no-git")).toBeInTheDocument();
  expect(screen.getByTestId("pin-apply")).toBeDisabled();
});

it("explains how this tool keeps library paths resolving on another machine", async () => {
  mockApi.getLibraryPin.mockResolvedValue(read());
  renderSection();
  expect(await screen.findByTestId("pin-path-contract")).toHaveTextContent("SR_LIB");
});

it("renders the backend's own wording for every status rather than inventing its own", async () => {
  /** Guards the "two layers describing the same state differently" bug class: the detail and the
   * remedy are DISPLAYED, never re-derived here. */
  const statuses: LibraryPinStatus[] = [
    "unpinned",
    "match",
    "library_ahead",
    "library_behind",
    "diverged",
    "unknown_commit",
    "different_library",
    "different_profile",
    "library_not_git",
  ];
  for (const status of statuses) {
    mockApi.getLibraryPin.mockResolvedValue(
      read({ status, detail: `detail for ${status}`, remedy: `remedy for ${status}` }),
    );
    const { unmount } = renderSection();
    expect(await screen.findByTestId("pin-detail")).toHaveTextContent(`detail for ${status}`);
    expect(screen.getByTestId("pin-remedy")).toHaveTextContent(`remedy for ${status}`);
    // and never the raw backend token, which is what a missing label looks like
    expect(screen.getByTestId("pin-status").textContent).not.toContain("_");
    unmount();
  }
});

it("surfaces a failed pin instead of leaving the button looking successful", async () => {
  mockApi.getLibraryPin.mockResolvedValue(
    read({ pinned: null, status: "unpinned", severity: "notice" }),
  );
  mockApi.setLibraryPin.mockRejectedValue(new Error("boom"));
  renderSection();
  await userEvent.click(await screen.findByTestId("pin-apply"));
  expect(await screen.findByText(/Could not pin the library version/)).toBeInTheDocument();
});

it("names WHICH profile the pin was taken against when that is the difference", async () => {
  /** Without this the card says "Different Profile" and never says which one, which is a status
   * the user cannot act on. */
  mockApi.getLibraryPin.mockResolvedValue(
    read({
      status: "different_profile",
      severity: "problem",
      library_profile: "Stockroom",
      pinned: {
        schema: 1,
        profile: "Archive",
        remote: "",
        commit: "a1b2c3d4e5f6a7b8c9d0a1b2c3d4e5f6a7b8c9d0",
        pinned_at: "2026-07-20T10:00:00+00:00",
      },
    }),
  );
  renderSection();
  expect(await screen.findByTestId("pin-status")).toHaveTextContent("Different Profile");
  expect(screen.getByText(/Archive profile/)).toBeInTheDocument();
  expect(screen.getByText(/Stockroom profile/)).toBeInTheDocument();
});
