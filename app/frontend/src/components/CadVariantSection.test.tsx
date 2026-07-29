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
      activate: vi.fn(),
    },
  };
});

const mockCadVariantApi = vi.mocked(cadVariantApi);

function document(activeVariantId: string | null = "snap-kicad"): CadVariantDocument {
  return {
    partId: "lm358",
    inventories: [
      {
        tool: "kicad",
        activeVariantId,
        variants: [
          {
            id: "ul-kicad",
            provider: "Ultra Librarian",
            format: "KiCad 10",
            artifacts: [
              { kind: "symbol", fileName: "LM358.kicad_sym" },
              { kind: "footprint", fileName: "LM358.kicad_mod" },
              { kind: "model", fileName: "LM358.step" },
            ],
            evidenceDigest: "sha256:ul-kicad",
            validationChecks: 12,
            trustRank: 10,
            trustLabel: "Manufacturer Verified",
          },
          {
            id: "snap-kicad",
            provider: "SnapMagic",
            format: "KiCad 10",
            artifacts: [
              { kind: "symbol", fileName: "LM358.kicad_sym" },
              { kind: "footprint", fileName: "LM358.kicad_mod" },
              { kind: "model", fileName: "LM358.step" },
            ],
            evidenceDigest: "sha256:snap-kicad",
            validationChecks: 10,
            trustRank: 20,
            trustLabel: "Validated Fallback",
          },
        ],
      },
      {
        tool: "altium",
        activeVariantId: "ul-altium",
        variants: [
          {
            id: "ul-altium",
            provider: "Ultra Librarian",
            format: "Altium Designer (Native)",
            artifacts: [
              { kind: "symbol", fileName: "LM358.SchLib" },
              { kind: "footprint", fileName: "LM358.PcbLib" },
            ],
            evidenceDigest: "sha256:ul-altium",
            validationChecks: 11,
            trustRank: 10,
            trustLabel: "Manufacturer Verified",
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
  mockCadVariantApi.activate.mockResolvedValue(document("ul-kicad"));
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

    expect(await screen.findByText("3 Retained")).toBeInTheDocument();
    expect(mockCadVariantApi.inventory).toHaveBeenCalledTimes(1);
    expect(mockCadVariantApi.inventory).toHaveBeenCalledWith("lm358");
  });

  it("activates one coherent tool bundle and refreshes inventory plus part detail", async () => {
    mockCadVariantApi.inventory
      .mockResolvedValueOnce(document())
      .mockResolvedValue(document("ul-kicad"));
    const { queryClient } = wrap(
      <CadVariantSection partId="lm358" enabled />,
    );
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    await userEvent.click(
      await screen.findByRole("button", {
        name: "Use Ultra Librarian variant for KiCad",
      }),
    );

    expect(mockCadVariantApi.activate).toHaveBeenCalledWith("lm358", {
      tool: "kicad",
      variantId: "ul-kicad",
      expectedActiveVariantId: "snap-kicad",
    });
    await waitFor(() =>
      expect(invalidate).toHaveBeenCalledWith({
        queryKey: ["part", "lm358"],
      }),
    );
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: ["cad-variants", "lm358"],
    });
    expect(
      await screen.findByRole("article", {
        name: "Ultra Librarian KiCad variant, active",
      }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("article")).toHaveLength(3);
  });

  it("surfaces a stale compare-and-switch and refetches the latest pointer", async () => {
    mockCadVariantApi.activate.mockRejectedValue(
      new CadVariantApiError(409, "active variant changed"),
    );
    wrap(<CadVariantSection partId="lm358" enabled />);

    await userEvent.click(
      await screen.findByRole("button", {
        name: "Use Ultra Librarian variant for KiCad",
      }),
    );

    expect(
      await screen.findByRole("alert"),
    ).toHaveTextContent(
      "The active variant changed before this switch completed. The latest choices are loading.",
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

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not read CAD variants. evidence store is unavailable",
    );
    await userEvent.click(screen.getByRole("button", { name: "Try Again" }));
    expect(await screen.findByText("3 Retained")).toBeInTheDocument();
  });
});
