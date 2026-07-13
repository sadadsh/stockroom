import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../api/client";
import type { DuplicateGroup, DuplicatesResponse } from "../api/types";
import { ToastProvider } from "../lib/toast";
import { DuplicatesPage } from "./DuplicatesPage";

vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return {
    ...actual,
    api: { getDuplicates: vi.fn(), deletePart: vi.fn() },
  };
});

const mockApi = vi.mocked(api);

const MPN_GROUP: DuplicateGroup = {
  key: "LM358DR",
  parts: [
    {
      id: "lm358",
      display_name: "LM358",
      category: "ICs",
      mpn: "LM358DR",
      manufacturer: "Texas Instruments",
      is_complete: true,
      missing: [],
    },
    {
      id: "lm358_dup",
      display_name: "LM358 Copy",
      category: "ICs",
      mpn: "LM358DR",
      manufacturer: "Texas Instruments",
      is_complete: false,
      missing: ["datasheet", "3D model"],
    },
  ],
};

const FP_GROUP: DuplicateGroup = {
  key: "R_0402_1005Metric",
  parts: [
    {
      id: "r1",
      display_name: "R 10k",
      category: "Passives",
      mpn: "RC0402-10K",
      manufacturer: "Yageo",
      is_complete: true,
      missing: [],
    },
    {
      id: "r2",
      display_name: "R 4k7",
      category: "Passives",
      mpn: "RC0402-4K7",
      manufacturer: "Yageo",
      is_complete: true,
      missing: [],
    },
  ],
};

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <DuplicatesPage />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

function partCard(id: string): HTMLElement {
  return screen.getByTestId(`dup-part-${id}`);
}

beforeEach(() => {
  mockApi.getDuplicates.mockResolvedValue({
    by_mpn: [MPN_GROUP],
    by_footprint: [FP_GROUP],
  });
  mockApi.deletePart.mockResolvedValue(undefined);
});

describe("DuplicatesPage", () => {
  it("renders both sections with their groups and members", async () => {
    renderPage();
    expect(await screen.findByText("Same Part Number")).toBeInTheDocument();
    expect(screen.getByText("Shared Footprint")).toBeInTheDocument();
    // the shared keys and every member name appear
    expect(screen.getByText("LM358DR")).toBeInTheDocument();
    expect(screen.getByText("LM358")).toBeInTheDocument();
    expect(screen.getByText("LM358 Copy")).toBeInTheDocument();
    expect(screen.getByText("R_0402_1005Metric")).toBeInTheDocument();
    expect(screen.getByText("R 10k")).toBeInTheDocument();
  });

  it("marks the most-complete member as the keep candidate and shows what the other lacks", async () => {
    renderPage();
    await screen.findByText("LM358");
    // the first (most complete) member carries the Keep marker
    expect(within(partCard("lm358")).getByText(/keep/i)).toBeInTheDocument();
    expect(within(partCard("lm358")).getByText(/complete/i)).toBeInTheDocument();
    // the incomplete duplicate is not the keep candidate and lists its gaps
    expect(within(partCard("lm358_dup")).queryByText(/keep/i)).toBeNull();
    expect(within(partCard("lm358_dup")).getByText(/datasheet/i)).toBeInTheDocument();
  });

  it("deletes a duplicate only after an in-window confirm, then calls deletePart", async () => {
    renderPage();
    await screen.findByText("LM358 Copy");
    await userEvent.click(
      within(partCard("lm358_dup")).getByRole("button", { name: /delete/i }),
    );
    // nothing deleted until the confirm dialog is accepted (no OS dialog, spec section 7)
    expect(mockApi.deletePart).not.toHaveBeenCalled();
    const dialog = screen.getByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: /^delete$/i }));
    expect(mockApi.deletePart).toHaveBeenCalledWith("lm358_dup");
  });

  it("disables the per-card Delete while the surface refetches, so a resolved delete cannot be re-fired into a 404", async () => {
    // First load shows the group; the post-delete refetch is held open so the
    // just-deleted card is still on screen (the real background-refetch window).
    let releaseRefetch!: (v: DuplicatesResponse) => void;
    mockApi.getDuplicates
      .mockResolvedValueOnce({ by_mpn: [MPN_GROUP], by_footprint: [FP_GROUP] })
      .mockReturnValueOnce(
        new Promise<DuplicatesResponse>((r) => {
          releaseRefetch = r;
        }),
      );
    renderPage();
    await screen.findByText("LM358 Copy");
    await userEvent.click(
      within(partCard("lm358_dup")).getByRole("button", { name: /delete/i }),
    );
    await userEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: /^delete$/i }),
    );
    // the delete resolved (once) and the surface is now refetching; the stale
    // card's Delete must be disabled so a second click cannot fire another delete.
    await waitFor(() => expect(mockApi.deletePart).toHaveBeenCalledTimes(1));
    const staleDelete = within(partCard("lm358_dup")).getByRole("button", {
      name: /delete/i,
    });
    expect(staleDelete).toBeDisabled();
    await userEvent.click(staleDelete);
    expect(mockApi.deletePart).toHaveBeenCalledTimes(1); // still one, no re-fire
    releaseRefetch({ by_mpn: [], by_footprint: [] });
  });

  it("frames a shared standard footprint as informational, not an error", async () => {
    renderPage();
    await screen.findByText("Shared Footprint");
    // the footprint section explains sharing is often normal, so the user is not
    // pushed to delete legitimately-shared standard footprints.
    expect(screen.getByText(/normal|expected|standard/i)).toBeInTheDocument();
  });

  it("shows an honest empty state when there are no duplicates", async () => {
    mockApi.getDuplicates.mockResolvedValue({ by_mpn: [], by_footprint: [] });
    renderPage();
    expect(await screen.findByText(/no parts share an mpn/i)).toBeInTheDocument();
    expect(screen.getByText(/no parts share a footprint/i)).toBeInTheDocument();
  });

  it("surfaces a load error honestly", async () => {
    mockApi.getDuplicates.mockRejectedValue(new Error("boom"));
    renderPage();
    expect(await screen.findByText(/could not load duplicates/i)).toBeInTheDocument();
  });
});
