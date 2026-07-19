import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../api/client";
import type { StagingCandidate } from "../api/types";
import { CadDownloadCard } from "./CadDownloadCard";

const CANDIDATE: StagingCandidate = {
  vendor: "digikey",
  symbol_lib_path: "/tmp/staging/x.kicad_sym",
  symbol_name: "BQ24074",
  footprint_variants: ["/tmp/staging/BQ24074.pretty/QFN-16.kicad_mod"],
  chosen_footprint_index: 0,
  model_path: "/tmp/staging/BQ24074.step",
  datasheet_path: null,
  display_name: "BQ24074",
  entry_name: "BQ24074",
  category: "IC",
  mpn: "BQ24074",
  manufacturer: "Texas Instruments",
  description: "Li-Ion charger",
  tags: [],
  purchase: [],
  gaps: [],
};

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) controller.enqueue(enc.encode(c));
      controller.close();
    },
  });
}

function resultStream(candidates: StagingCandidate[]): ReadableStream<Uint8Array> {
  return streamOf([
    `event: result\ndata: {"result":${JSON.stringify(candidates)}}\n\n`,
    "event: done\ndata: {}\n\n",
  ]);
}

function renderCard(partId = "part1", assetsMissing = true) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <CadDownloadCard partId={partId} assetsMissing={assetsMissing} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  delete (window as { pywebview?: unknown }).pywebview;
  delete window.__STOCKROOM_CAD_DOWNLOAD__;
});

describe("CadDownloadCard", () => {
  it("renders nothing when the part is not missing assets", () => {
    vi.spyOn(api, "partCadSource").mockResolvedValue({
      url: "https://www.digikey.com/x",
      mpn: "BQ24074",
      vendor: "DigiKey",
    });
    renderCard("part1", false);
    expect(screen.queryByTestId("cad-download-card")).not.toBeInTheDocument();
    expect(api.partCadSource).not.toHaveBeenCalled();
  });

  it("renders nothing when no DigiKey CAD source resolves for the part", async () => {
    vi.spyOn(api, "partCadSource").mockResolvedValue({ url: null, mpn: "", vendor: "DigiKey" });
    renderCard();
    await waitFor(() => expect(api.partCadSource).toHaveBeenCalled());
    expect(screen.queryByTestId("cad-download-card")).not.toBeInTheDocument();
  });

  it("shows the idle button once a DigiKey CAD source resolves", async () => {
    vi.spyOn(api, "partCadSource").mockResolvedValue({
      url: "https://www.digikey.com/en/products/detail/x/BQ24074/123",
      mpn: "BQ24074",
      vendor: "DigiKey",
    });
    renderCard();
    expect(
      await screen.findByRole("button", { name: /Get CAD Files From DigiKey/ }),
    ).toBeInTheDocument();
  });

  it("clicking the button opens the host bridge and offers Browse for ZIP while waiting", async () => {
    const openCadDownload = vi.fn();
    (
      window as unknown as { pywebview: { api: { open_cad_download: typeof openCadDownload } } }
    ).pywebview = { api: { open_cad_download: openCadDownload } };
    vi.spyOn(api, "partCadSource").mockResolvedValue({
      url: "https://www.digikey.com/en/products/detail/x/BQ24074/123",
      mpn: "BQ24074",
      vendor: "DigiKey",
    });
    renderCard();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: /Get CAD Files From DigiKey/ }));

    expect(openCadDownload).toHaveBeenCalledWith(
      "https://www.digikey.com/en/products/detail/x/BQ24074/123",
    );
    expect(await screen.findByRole("button", { name: /Browse for ZIP/ })).toBeInTheDocument();
    expect(screen.getByTestId("cad-download-message")).toHaveTextContent(
      "Waiting for the download",
    );
  });

  it("runs the full flow to done once the captured-download global fires", async () => {
    const openCadDownload = vi.fn();
    (
      window as unknown as { pywebview: { api: { open_cad_download: typeof openCadDownload } } }
    ).pywebview = { api: { open_cad_download: openCadDownload } };
    vi.spyOn(api, "partCadSource").mockResolvedValue({
      url: "https://www.digikey.com/en/products/detail/x/BQ24074/123",
      mpn: "BQ24074",
      vendor: "DigiKey",
    });
    vi.spyOn(api, "assetsInspect").mockResolvedValue({ job_id: "j1" });
    vi.spyOn(api, "openJobStream").mockResolvedValue(resultStream([CANDIDATE]));
    vi.spyOn(api, "assetsCommit").mockResolvedValue({} as never);
    renderCard();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: /Get CAD Files From DigiKey/ }));
    await screen.findByRole("button", { name: /Browse for ZIP/ });

    await act(async () => {
      window.__STOCKROOM_CAD_DOWNLOAD__!("C:\\Users\\me\\Downloads\\BQ24074.zip");
    });

    await waitFor(() =>
      expect(screen.getByTestId("cad-download-message")).toHaveTextContent(
        "Symbol, footprint, and 3D model attached.",
      ),
    );
    expect(api.assetsCommit).toHaveBeenCalledWith("part1", CANDIDATE);
  });

  it("shows an honest unavailable message if the source disappears by the time it is clicked", async () => {
    vi.spyOn(api, "partCadSource")
      .mockResolvedValueOnce({
        url: "https://www.digikey.com/en/products/detail/x/BQ24074/123",
        mpn: "BQ24074",
        vendor: "DigiKey",
      })
      .mockResolvedValueOnce({ url: null, mpn: "BQ24074", vendor: "DigiKey" });
    renderCard();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: /Get CAD Files From DigiKey/ }));

    expect(await screen.findByTestId("cad-download-message")).toHaveTextContent(
      "No DigiKey CAD source for this part.",
    );
    expect(await screen.findByRole("button", { name: /Try Again/ })).toBeInTheDocument();
  });

  it("surfaces an inspect/commit error inline instead of crashing", async () => {
    const openCadDownload = vi.fn();
    (
      window as unknown as { pywebview: { api: { open_cad_download: typeof openCadDownload } } }
    ).pywebview = { api: { open_cad_download: openCadDownload } };
    vi.spyOn(api, "partCadSource").mockResolvedValue({
      url: "https://www.digikey.com/en/products/detail/x/BQ24074/123",
      mpn: "BQ24074",
      vendor: "DigiKey",
    });
    vi.spyOn(api, "assetsInspect").mockRejectedValue(new Error("network down"));
    renderCard();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: /Get CAD Files From DigiKey/ }));
    await screen.findByRole("button", { name: /Browse for ZIP/ });
    await act(async () => {
      window.__STOCKROOM_CAD_DOWNLOAD__!("a.zip");
    });

    await waitFor(() =>
      expect(screen.getByTestId("cad-download-message")).toHaveTextContent("network down"),
    );
    expect(await screen.findByRole("button", { name: /Try Again/ })).toBeInTheDocument();
  });
});
