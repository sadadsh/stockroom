/**
 * Tests for the Library Sync settings section.
 *
 * PRIOR ART: no new test infrastructure. vitest + @testing-library/react with a per-test
 * QueryClient and the real ToastProvider, and the mock shape copied from
 * `LibraryHealthSection.test.tsx`, exactly as every other component test in this repo does it.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../api/client";
import type { HygieneRead, LibraryLfsStatus } from "../api/types";
import { ToastProvider } from "../lib/toast";
import { LibrarySyncSection } from "./LibrarySyncSection";

vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      getLibraryLfs: vi.fn(),
      adoptLibraryLfs: vi.fn(),
      getLibraryHygiene: vi.fn(),
      syncLibraryHygiene: vi.fn(),
    },
  };
});

const mockApi = vi.mocked(api);

function lfs(over: Partial<LibraryLfsStatus> = {}): LibraryLfsStatus {
  return {
    installed: true,
    version: "git-lfs/3.4.1",
    enabled: false,
    tracked_patterns: [],
    objects: 0,
    legacy_blobs: 0,
    covers: ["*.PcbLib", "*.SchLib", "*.step"],
    adopted: false,
    reason: "",
    ...over,
  };
}

const CLEAN: HygieneRead = { writes: [], untracked: [] };

function renderSection() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <LibrarySyncSection />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockApi.getLibraryHygiene.mockResolvedValue(CLEAN);
});

it("names what adoption would cover, rather than promising a benefit in the abstract", async () => {
  mockApi.getLibraryLfs.mockResolvedValue(lfs());
  renderSection();
  expect(await screen.findByTestId("lfs-state")).toHaveTextContent("Stored In Git History");
  const covers = screen.getByTestId("lfs-covers");
  expect(covers).toHaveTextContent("*.PcbLib");
  expect(covers).toHaveTextContent("*.step");
});

it("adopts git lfs and reports how many patterns it now handles", async () => {
  mockApi.getLibraryLfs.mockResolvedValue(lfs());
  mockApi.adoptLibraryLfs.mockResolvedValue({
    ...lfs({ enabled: true, adopted: true, tracked_patterns: ["*.PcbLib", "*.step"] }),
    writes: [".gitattributes"],
    untracked: [],
    committed: "abc1234",
  });
  renderSection();
  await userEvent.click(await screen.findByTestId("lfs-adopt"));
  await waitFor(() => expect(mockApi.adoptLibraryLfs).toHaveBeenCalledTimes(1));
  expect(await screen.findByText(/2 pattern\(s\) tracked/)).toBeInTheDocument();
});

it("offers no action at all when git lfs is not installed, and says why", async () => {
  /** A disabled button with no explanation is the shape that makes people think the app is
   * broken. The reason comes from the backend probe, not from a guess here. */
  mockApi.getLibraryLfs.mockResolvedValue(
    lfs({ installed: false, reason: "git-lfs is not installed on this machine" }),
  );
  renderSection();
  expect(await screen.findByTestId("lfs-state")).toHaveTextContent("Git LFS Not Installed");
  expect(screen.queryByTestId("lfs-adopt")).toBeNull();
  expect(screen.getByTestId("lfs-reason")).toHaveTextContent("not installed");
});

it("NEVER claims adoption fixes what is already in history", async () => {
  /** It does not: only new commits become pointers, and converting the past needs a rewrite plus
   * a force-push. Saying otherwise would be a claim the tool cannot back up. */
  mockApi.getLibraryLfs.mockResolvedValue(
    lfs({ enabled: true, adopted: true, tracked_patterns: ["*.PcbLib"], objects: 4, legacy_blobs: 9 }),
  );
  renderSection();
  expect(await screen.findByTestId("lfs-legacy")).toHaveTextContent("9 files were committed before");
  expect(screen.queryByTestId("lfs-adopt")).toBeNull();
});

it("lists the library files that would stop being shared before anyone agrees to it", async () => {
  mockApi.getLibraryLfs.mockResolvedValue(lfs());
  mockApi.getLibraryHygiene.mockResolvedValue({
    writes: [".gitignore"],
    untracked: ["altium/stockroom-parts.db", "symbols/fp-info-cache"],
  });
  renderSection();
  const files = await screen.findByTestId("library-hygiene-files");
  expect(files).toHaveTextContent("altium/stockroom-parts.db");
  expect(files).toHaveTextContent("symbols/fp-info-cache");
  expect(screen.getByTestId("library-hygiene-sync")).toHaveTextContent("Stop Sharing These");
});

it("says so plainly when the library is already clean", async () => {
  mockApi.getLibraryLfs.mockResolvedValue(lfs());
  renderSection();
  expect(await screen.findByTestId("library-hygiene-clean")).toBeInTheDocument();
});

it("surfaces a failed sync instead of leaving the button looking successful", async () => {
  mockApi.getLibraryLfs.mockResolvedValue(lfs());
  mockApi.getLibraryHygiene.mockResolvedValue({ writes: [".gitignore"], untracked: [] });
  mockApi.syncLibraryHygiene.mockRejectedValue(new Error("boom"));
  renderSection();
  await userEvent.click(await screen.findByTestId("library-hygiene-sync"));
  expect(await screen.findByText(/Could not sync the library's workspace hygiene/)).toBeInTheDocument();
});
