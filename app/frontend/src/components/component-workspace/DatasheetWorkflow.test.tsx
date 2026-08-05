/**
 * The datasheet workflow, across every shape a real datasheet actually takes.
 *
 * The bug this suite exists to prevent from returning was small and expensive: the header button
 * rendered because a FILE existed and the handler only knew how to open a URL, so pressing it on a
 * component whose datasheet was on disk did nothing at all. Every case below is one of the shapes
 * that has to work - and the last three are the ones that used to produce an empty grey pane.
 *
 * A failure is a STATE the viewer holds, not a toast it fires. It names what failed, keeps the
 * viewer open, and offers Retry and the source page beside it, because "the manufacturer's own URL
 * still works" is exactly what a person needs when our copy does not.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { ApiError, api } from "../../api/client";
import { cadVariantApi } from "../../api/cadVariantClient";
import type { ComponentDossier } from "../../api/dossierTypes";
import { devIdSelector } from "../../lib/componentDevIds";
import { ThemeProvider } from "../../lib/theme";
import { ToastProvider } from "../../lib/toast";
import {
  defaultUiSession,
  openComponentInSession,
  resetUiSessionForTests,
} from "../../lib/uiSession";
import { makeDocument, makeDossierWith } from "../../test/dossierFixture";
import { FAIL_MARKER, STUB_PAGE_COUNT } from "../../test/reactPdfStub";
import { ComponentWorkspace } from "./ComponentWorkspace";
import {
  openKindFor,
  otherDocumentTargets,
  preferredTarget,
  revisionLabel,
  revisionTargets,
} from "./datasheetWorkflow";

vi.mock("../../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../../api/client")>();
  return {
    ...actual,
    api: {
      partDossier: vi.fn(),
      partHistory: vi.fn(),
      partDetail: vi.fn(),
      facets: vi.fn(),
      previewSvg: vi.fn(),
      modelGlb: vi.fn(),
      landPattern: vi.fn(),
      documentFile: vi.fn(),
      refreshSourcing: vi.fn(),
    },
  };
});

vi.mock("../../api/cadVariantClient", async (importActual) => {
  const actual = await importActual<typeof import("../../api/cadVariantClient")>();
  return {
    ...actual,
    cadVariantApi: { inventory: vi.fn(), activatePair: vi.fn() },
  };
});

vi.mock("../../lib/threeScene", () => ({
  mountModelScene: vi.fn(() => ({
    dispose: vi.fn(),
    fit: vi.fn(),
    setView: vi.fn(),
    setSpin: vi.fn(),
    setLandPattern: vi.fn(),
    setRenderMode: vi.fn(),
    setLayers: vi.fn(),
    setPlacementMode: vi.fn(),
    modelInfo: vi.fn(() => null),
  })),
}));

const mockApi = vi.mocked(api);
const mockCadVariantApi = vi.mocked(cadVariantApi);
const ID = "lm358";

/** Bytes that make the stubbed pdf.js report a broken document. */
function pdfBytes(marker = ""): Blob {
  return new Blob([`%PDF-1.7 ${marker}`], { type: "application/pdf" });
}

beforeEach(() => {
  window.localStorage.clear();
  mockApi.previewSvg.mockResolvedValue(new Blob(["<svg/>"], { type: "image/svg+xml" }));
  mockApi.modelGlb.mockResolvedValue(new Uint8Array([0x67, 0x6c, 0x54, 0x46]).buffer);
  mockApi.landPattern.mockRejectedValue(new ApiError(404, "no footprint"));
  mockApi.partHistory.mockResolvedValue({ commits: [], count: 0 });
  mockApi.documentFile.mockResolvedValue(pdfBytes());
  mockCadVariantApi.inventory.mockResolvedValue({
    partId: ID,
    inventories: [],
    pairs: [],
    supplementary: [],
  });
  mockApi.facets.mockResolvedValue({
    by_category: { ICs: 1 },
    by_manufacturer: {},
    complete: 1,
    incomplete: 0,
  });
  vi.spyOn(window, "open").mockImplementation(() => null);
});

function provide(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <ToastProvider>{ui}</ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

async function open(dossier: ComponentDossier) {
  resetUiSessionForTests(openComponentInSession(defaultUiSession(), ID));
  mockApi.partDossier.mockResolvedValue(dossier);
  const view = provide(<ComponentWorkspace componentId={ID} />);
  await waitFor(() =>
    expect(document.querySelector(devIdSelector("component-browser.header-mpn"))).not.toBeNull(),
  );
  return view;
}

function node(devId: string): HTMLElement {
  return document.querySelector<HTMLElement>(devIdSelector(devId))!;
}

/** One preferred datasheet, plus whatever else the case is about. */
function withDocuments(...items: ReturnType<typeof makeDocument>[]) {
  return makeDossierWith({ documents: items });
}

describe("which document the Datasheet action opens", () => {
  it("prefers the stored bytes over the URL for the same copy", () => {
    const both = makeDocument({
      localPath: "datasheets/lm358.pdf",
      remoteUrl: "https://ti.example.invalid/lm358.pdf",
    });
    expect(openKindFor(both)).toBe("file");
  });

  it("fetches a PDF that exists only as a URL", () => {
    expect(openKindFor(makeDocument({ localPath: "" }))).toBe("remote");
  });

  it("treats an HTML resource as a page, never as a PDF pane", () => {
    expect(
      openKindFor(
        makeDocument({
          documentType: "datasheet_page",
          documentTypeLabel: "Datasheet Page",
          localPath: "",
          remoteUrl: "https://ti.example.invalid/product/LM358",
          mimeType: "text/html",
        }),
      ),
    ).toBe("page");
    // And a `datasheet` whose only link is not a PDF is a page too: calling it a document would
    // promise a file that does not exist.
    expect(
      openKindFor(
        makeDocument({ localPath: "", remoteUrl: "https://x.invalid/p", mimeType: "text/html" }),
      ),
    ).toBe("page");
  });

  it("separates the revisions of one document from every other document", () => {
    const dossier = withDocuments(
      makeDocument({ title: "Datasheet", revision: "F", isPreferred: true, isCurrent: true }),
      makeDocument({ title: "Datasheet", revision: "E", localPath: "old.pdf", isCurrent: false }),
      makeDocument({
        documentType: "package_drawing",
        documentTypeLabel: "Package Drawing",
        title: "SOIC-8 Outline",
        localPath: "",
        remoteUrl: "https://ti.example.invalid/soic8.pdf",
      }),
    );
    expect(preferredTarget(dossier.documents)!.document.revision).toBe("F");
    expect(revisionTargets(dossier.documents).map((item) => revisionLabel(item.document))).toEqual([
      "E",
    ]);
    expect(
      otherDocumentTargets(dossier.documents).map((item) => item.document.title),
    ).toEqual(["SOIC-8 Outline"]);
  });

  it("falls back to the retrieval date when a revision carries no revision string", () => {
    expect(revisionLabel(makeDocument({ revision: "", retrievedAt: "2026-08-01T00:00:00Z" }))).toBe(
      "2026-08-01",
    );
  });
});

describe("the Datasheet control", () => {
  it("states Datasheet Missing with a real action when there is no datasheet at all", async () => {
    await open(makeDossierWith({}));
    expect(node("component-browser.datasheet-missing")).toHaveTextContent("Datasheet Missing");
    expect(node("component-browser.datasheet-find")).toBeEnabled();
    expect(document.querySelector(devIdSelector("component-browser.datasheet-more"))).toBeNull();
  });

  it("is a plain button, not a split button, when there is only one document", async () => {
    await open(withDocuments(makeDocument({ isPreferred: true })));
    expect(node("component-browser.header-datasheet")).toBeEnabled();
    // An arrow that opens a menu of nothing is a dead click path.
    expect(document.querySelector(devIdSelector("component-browser.datasheet-more"))).toBeNull();
  });

  it("becomes a split button whose menu lists the revisions and the other documents", async () => {
    const user = userEvent.setup();
    await open(
      withDocuments(
        makeDocument({ title: "Datasheet", revision: "F", isPreferred: true }),
        makeDocument({ title: "Datasheet", revision: "E", localPath: "old.pdf" }),
        makeDocument({
          documentType: "pcn",
          documentTypeLabel: "Product Change Notice",
          title: "PCN-20260701",
          localPath: "",
          remoteUrl: "https://ti.example.invalid/pcn.pdf",
        }),
      ),
    );
    await user.click(node("component-browser.datasheet-more"));
    const menu = node("component-browser.datasheet-menu");
    expect(within(menu).getAllByRole("menuitem").map((item) => item.textContent?.trim())).toEqual([
      "Current DatasheetDatasheet",
      "Revision EDatasheet",
      "PCN-20260701Product Change Notice",
    ]);
  });
});

describe("the datasheet viewer", () => {
  it("opens the stored file through the documents endpoint and shows the first page", async () => {
    const user = userEvent.setup();
    const only = makeDocument({ isPreferred: true });
    await open(withDocuments(only));
    await user.click(node("component-browser.header-datasheet"));

    await waitFor(() => expect(mockApi.documentFile).toHaveBeenCalledWith(ID, only.id));
    const page = await screen.findByTestId("pdf-page");
    expect(page.dataset.pageNumber).toBe("1");
  });

  it("fetches the document the person chose even after the list order changes", async () => {
    // The failure this guards against is silent: with position addressing, a revision arriving
    // between the render and the click shifts the target down the list, the endpoint is asked for
    // whatever now sits at that position, and a DIFFERENT datasheet opens looking entirely correct.
    const user = userEvent.setup();
    const wanted = makeDocument({ isPreferred: true, revision: "C" });
    const arrivesFirst = makeDocument({ revision: "D", localPath: "datasheets/lm358-d.pdf" });

    await open(makeDossierWith({ documents: [wanted, arrivesFirst] }));
    // The same response, re-ordered: `wanted` is no longer at position 0.
    mockApi.partDossier.mockResolvedValue(
      makeDossierWith({ documents: [arrivesFirst, wanted] }),
    );
    await user.click(node("component-browser.header-datasheet"));

    await waitFor(() => expect(mockApi.documentFile).toHaveBeenCalledWith(ID, wanted.id));
    expect(mockApi.documentFile).not.toHaveBeenCalledWith(ID, arrivesFirst.id);
    expect(wanted.id).not.toEqual(arrivesFirst.id);
  });

  it("loads a URL-only datasheet from the URL rather than the file endpoint", async () => {
    const user = userEvent.setup();
    await open(withDocuments(makeDocument({ localPath: "", isPreferred: true })));
    await user.click(node("component-browser.header-datasheet"));

    await screen.findByTestId("pdf-page");
    expect(mockApi.documentFile).not.toHaveBeenCalled();
  });

  it("navigates by page, by the document's own outline, and zooms and rotates", async () => {
    const user = userEvent.setup();
    await open(withDocuments(makeDocument({ isPreferred: true })));
    await user.click(node("component-browser.header-datasheet"));
    await screen.findByTestId("pdf-page");

    await user.click(node("component-browser.datasheet-next"));
    expect(node("component-browser.datasheet-page-number")).toHaveTextContent("2");

    await user.click(node("component-browser.datasheet-previous"));
    expect(node("component-browser.datasheet-page-number")).toHaveTextContent("1");

    // A real table of contents: the outline names a section and lands on its page.
    await user.click(screen.getByTestId("pdf-outline-item"));
    expect(node("component-browser.datasheet-page-number")).toHaveTextContent("2");

    await user.click(node("component-browser.datasheet-zoom-in"));
    expect(node("component-browser.datasheet-zoom")).toHaveTextContent("125%");
    await user.click(node("component-browser.datasheet-zoom-out"));
    expect(node("component-browser.datasheet-zoom")).toHaveTextContent("100%");

    await user.click(node("component-browser.datasheet-rotate"));
    expect(screen.getByTestId("pdf-page").dataset.rotate).toBe("90");
  });

  it("stops the page stepper at the ends rather than asking for a page that is not there", async () => {
    const user = userEvent.setup();
    await open(withDocuments(makeDocument({ isPreferred: true })));
    await user.click(node("component-browser.header-datasheet"));
    await screen.findByTestId("pdf-page");

    expect(node("component-browser.datasheet-previous")).toBeDisabled();
    for (let step = 1; step < STUB_PAGE_COUNT; step += 1) {
      await user.click(node("component-browser.datasheet-next"));
    }
    expect(node("component-browser.datasheet-next")).toBeDisabled();
  });

  it("labels an HTML resource as a page and opens it where it lives", async () => {
    const user = userEvent.setup();
    await open(
      withDocuments(
        makeDocument({
          documentType: "datasheet_page",
          documentTypeLabel: "Datasheet Page",
          title: "LM358 Product Page",
          localPath: "",
          remoteUrl: "https://ti.example.invalid/product/LM358",
          mimeType: "text/html",
          host: "ti.example.invalid",
          isPreferred: true,
        }),
      ),
    );
    await user.click(node("component-browser.header-datasheet"));

    const resource = await waitFor(() => node("component-browser.datasheet-page-resource"));
    expect(resource).toHaveTextContent("Datasheet Page");
    expect(resource).toHaveTextContent(/web page rather than a PDF/);
    expect(screen.queryByTestId("pdf-page")).toBeNull();

    await user.click(node("component-browser.datasheet-open-page"));
    expect(window.open).toHaveBeenCalledWith(
      "https://ti.example.invalid/product/LM358",
      "_blank",
      "noreferrer",
    );
  });

  it("says WHAT failed when the stored file is no longer on disk, and offers the URL", async () => {
    const user = userEvent.setup();
    mockApi.documentFile.mockRejectedValue(new ApiError(404, "datasheets/lm358.pdf is not on disk"));
    await open(withDocuments(makeDocument({ isPreferred: true })));
    await user.click(node("component-browser.header-datasheet"));

    const failure = await waitFor(() => node("component-browser.datasheet-failed"));
    expect(failure).toHaveTextContent("The datasheet could not be opened");
    expect(node("component-browser.datasheet-failure-reason")).toHaveTextContent(
      "datasheets/lm358.pdf is not on disk",
    );
    // The viewer STAYS OPEN with both next steps beside the reason - never an empty grey pane,
    // and never a toast that takes the surface away.
    expect(node("component-browser.datasheet-retry")).toBeEnabled();
    await user.click(node("component-browser.datasheet-open-source"));
    expect(window.open).toHaveBeenCalledWith(
      "https://ti.example.invalid/lm358.pdf",
      "_blank",
      "noreferrer",
    );
  });

  it("retries the fetch in place, and recovers when the second attempt works", async () => {
    const user = userEvent.setup();
    mockApi.documentFile
      .mockRejectedValueOnce(new ApiError(0, "Network error"))
      .mockResolvedValueOnce(pdfBytes());
    await open(withDocuments(makeDocument({ isPreferred: true })));
    await user.click(node("component-browser.header-datasheet"));

    await waitFor(() => expect(node("component-browser.datasheet-failed")).not.toBeNull());
    await user.click(node("component-browser.datasheet-retry"));
    await screen.findByTestId("pdf-page");
  });

  it("reports a PDF that loads but cannot be parsed, rather than rendering nothing", async () => {
    const user = userEvent.setup();
    mockApi.documentFile.mockResolvedValue(pdfBytes(FAIL_MARKER));
    await open(withDocuments(makeDocument({ isPreferred: true })));
    await user.click(node("component-browser.header-datasheet"));

    await waitFor(() =>
      expect(node("component-browser.datasheet-failure-reason")).toHaveTextContent(
        "Invalid PDF structure.",
      ),
    );
  });

  it("opens a document from the sourcing column's own row, not only from the header", async () => {
    const user = userEvent.setup();
    const note = makeDocument({
      documentType: "application_note",
      documentTypeLabel: "Application Note",
      title: "AN-31 Op Amp Circuits",
      localPath: "notes/an31.pdf",
      remoteUrl: "",
    });
    await open(withDocuments(makeDocument({ isPreferred: true }), note));
    const rows = document.querySelectorAll<HTMLElement>(
      '[data-dev-id="component-browser.document-row"]',
    );
    await user.click(within(rows[1]).getByRole("button", { name: "Open AN-31 Op Amp Circuits" }));
    await waitFor(() => expect(mockApi.documentFile).toHaveBeenCalledWith(ID, note.id));
  });

  it("closes on Escape and leaves the three columns exactly where they were", async () => {
    const user = userEvent.setup();
    await open(withDocuments(makeDocument({ isPreferred: true })));
    await user.click(node("component-browser.header-datasheet"));
    await screen.findByTestId("pdf-page");

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByTestId("pdf-page")).toBeNull());
    // The reading surface never went anywhere: this is a window ON the workspace, not a
    // replacement for it.
    expect(document.querySelectorAll("[data-workspace-column]")).toHaveLength(3);
  });
});
