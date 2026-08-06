import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  cadVariantApi,
  CadVariantApiError,
  type CadVariantDocument,
} from "../api/cadVariantClient";
import { CadVariantSection } from "./CadVariantSection";

vi.mock("../api/cadVariantClient", async (importActual) => {
  const actual = await importActual<typeof import("../api/cadVariantClient")>();
  return {
    ...actual,
    cadVariantApi: {
      inventory: vi.fn(),
      activatePair: vi.fn(),
    },
  };
});

const mockCadVariantApi = vi.mocked(cadVariantApi);

function document(activeVariantId: string | null = "snap-shared"): CadVariantDocument {
  return {
    partId: "lm358",
    supplementary: [],
    pairs: [
      {
        kicadVariantId: "ul-shared",
        altiumVariantId: "ul-shared",
        provider: "Ultra Librarian",
        trustRank: 0,
        verificationState: "reverified",
        trustLabel: "Same-Download Pair",
      },
      {
        kicadVariantId: "snap-shared",
        altiumVariantId: "snap-shared",
        provider: "SnapMagic",
        trustRank: 1,
        verificationState: "reverified",
        trustLabel: "Same-Download Pair",
      },
    ],
    inventories: [
      {
        tool: "kicad",
        activeVariantId,
        variants: [
          {
            id: "ul-shared",
            provider: "Ultra Librarian",
            format: "KiCad 10",
            artifacts: [
              { kind: "symbol", fileName: "LM358.kicad_sym" },
              { kind: "footprint", fileName: "LM358.kicad_mod" },
              { kind: "model", fileName: "LM358.step" },
            ],
            evidenceDigest: "sha256:ul-shared",
            verificationState: "reverified",
            trustRank: 10,
            trustLabel: "Preferred Source",
          },
          {
            id: "snap-shared",
            provider: "SnapMagic",
            format: "KiCad 10",
            artifacts: [
              { kind: "symbol", fileName: "LM358.kicad_sym" },
              { kind: "footprint", fileName: "LM358.kicad_mod" },
              { kind: "model", fileName: "LM358.step" },
            ],
            evidenceDigest: "sha256:snap-shared",
            verificationState: "reverified",
            trustRank: 20,
            trustLabel: "Fallback Source",
          },
        ],
      },
      {
        tool: "altium",
        activeVariantId,
        variants: [
          {
            id: "ul-shared",
            provider: "Ultra Librarian",
            format: "Altium Designer (Native)",
            artifacts: [
              { kind: "symbol", fileName: "LM358.SchLib" },
              { kind: "footprint", fileName: "LM358.PcbLib" },
            ],
            evidenceDigest: "sha256:ul-shared",
            verificationState: "reverified",
            trustRank: 10,
            trustLabel: "Preferred Source",
          },
          {
            id: "snap-shared",
            provider: "SnapMagic",
            format: "Altium Designer (Native)",
            artifacts: [
              { kind: "symbol", fileName: "LM358.SchLib" },
              { kind: "footprint", fileName: "LM358.PcbLib" },
            ],
            evidenceDigest: "sha256:snap-shared",
            verificationState: "reverified",
            trustRank: 20,
            trustLabel: "Fallback Source",
          },
        ],
      },
    ],
  };
}

function wrap(ui: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>,
    ),
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mockCadVariantApi.inventory.mockResolvedValue(document());
  mockCadVariantApi.activatePair.mockResolvedValue(document("ul-shared"));
});

describe("CadVariantSection", () => {
  it("does not fetch until the selected part's Representations view is active", async () => {
    const view = wrap(<CadVariantSection partId="lm358" enabled={false} />);

    expect(mockCadVariantApi.inventory).not.toHaveBeenCalled();
    view.rerender(
      <QueryClientProvider client={view.queryClient}>
        <CadVariantSection partId="lm358" enabled />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("4 Retained")).toBeInTheDocument();
    expect(mockCadVariantApi.inventory).toHaveBeenCalledTimes(1);
    expect(mockCadVariantApi.inventory).toHaveBeenCalledWith("lm358");
  });

  it("switches one same-download pair and refreshes inventory plus part detail", async () => {
    mockCadVariantApi.inventory
      .mockResolvedValueOnce(document())
      .mockResolvedValue(document("ul-shared"));
    const { queryClient } = wrap(
      <CadVariantSection partId="lm358" enabled />,
    );
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    await userEvent.click(
      await screen.findByRole("button", {
        name: "Use Ultra Librarian for KiCad and Altium",
      }),
    );

    expect(mockCadVariantApi.activatePair).toHaveBeenCalledWith("lm358", {
      kicadVariantId: "ul-shared",
      altiumVariantId: "ul-shared",
      expectedActiveKicadVariantId: "snap-shared",
      expectedActiveAltiumVariantId: "snap-shared",
    });
    await waitFor(() =>
      expect(invalidate).toHaveBeenCalledWith({
        queryKey: ["part", "lm358"],
      }),
    );
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: ["cad-variants", "lm358"],
    });
    expect(await screen.findByText("Active In Both")).toBeInTheDocument();
  });

  it("surfaces a stale pair switch and refetches both latest pointers", async () => {
    mockCadVariantApi.activatePair.mockRejectedValue(
      new CadVariantApiError(409, "active pair changed"),
    );
    wrap(<CadVariantSection partId="lm358" enabled />);

    await userEvent.click(
      await screen.findByRole("button", {
        name: "Use Ultra Librarian for KiCad and Altium",
      }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The active CAD pair changed before this switch completed. The latest choices are loading.",
    );
    await waitFor(() =>
      expect(mockCadVariantApi.inventory).toHaveBeenCalledTimes(2),
    );
  });

  it("offers an in-place retry after an inventory read fails", async () => {
    mockCadVariantApi.inventory
      .mockRejectedValueOnce(new Error("evidence store is unavailable"))
      .mockResolvedValueOnce(document());
    wrap(<CadVariantSection partId="lm358" enabled />);

    // A written sentence, not the query's own exception appended to a prefix: "evidence store is
    // unavailable" is a transport string, and the retry beside it is what a person can act on.
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The retained CAD variants could not be read.");
    expect(alert).not.toHaveTextContent("evidence store is unavailable");
    await userEvent.click(screen.getByRole("button", { name: "Rerun" }));
    expect(await screen.findByText("4 Retained")).toBeInTheDocument();
  });
});
