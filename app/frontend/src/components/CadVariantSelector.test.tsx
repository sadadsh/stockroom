import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  CadVariantSelector,
  type CadVariant,
  type CadVariantInventory,
  type CadVariantPair,
} from "./CadVariantSelector";

function variant(overrides: Partial<CadVariant> = {}): CadVariant {
  return {
    id: "ul-shared",
    provider: "Ultra Librarian",
    format: "KiCad 10",
    artifacts: [
      { kind: "symbol", fileName: "Part.kicad_sym" },
      { kind: "footprint", fileName: "Part.kicad_mod" },
      { kind: "model", fileName: "Part.step" },
    ],
    evidenceDigest: "sha256:ul-shared",
    verificationState: "reverified",
    trustRank: 10,
    trustLabel: "Preferred Source",
    trustReason: "The provider evidence was reverified.",
    ...overrides,
  };
}

function inventories(
  activeKicad: string | null = "ul-shared",
  activeAltium: string | null = "ul-shared",
): CadVariantInventory[] {
  return [
    {
      tool: "kicad",
      activeVariantId: activeKicad,
      variants: [
        variant(),
        variant({
          id: "snap-shared",
          provider: "SnapMagic",
          evidenceDigest: "sha256:snap-shared",
          trustRank: 20,
          trustLabel: "Fallback Source",
        }),
      ],
    },
    {
      tool: "altium",
      activeVariantId: activeAltium,
      variants: [
        variant({
          format: "Altium Designer (Native)",
          artifacts: [
            { kind: "symbol", fileName: "Part.SchLib" },
            { kind: "footprint", fileName: "Part.PcbLib" },
          ],
        }),
        variant({
          id: "snap-shared",
          provider: "SnapMagic",
          format: "Altium Designer (Native)",
          artifacts: [
            { kind: "symbol", fileName: "Part.SchLib" },
            { kind: "footprint", fileName: "Part.PcbLib" },
          ],
          evidenceDigest: "sha256:snap-shared",
          trustRank: 20,
          trustLabel: "Fallback Source",
        }),
      ],
    },
  ];
}

function pairs(): CadVariantPair[] {
  return [
    {
      kicadVariantId: "ul-shared",
      altiumVariantId: "ul-shared",
      provider: "Ultra Librarian",
      trustRank: 0,
      verificationState: "reverified",
      trustLabel: "Same-Download Pair",
      trustReason: "Both projections came from one immutable provider manifest.",
    },
    {
      kicadVariantId: "snap-shared",
      altiumVariantId: "snap-shared",
      provider: "SnapMagic",
      trustRank: 1,
      verificationState: "reverified",
      trustLabel: "Same-Download Pair",
      trustReason: "Both projections came from one immutable provider manifest.",
    },
  ];
}

const supplementary = [
  {
    id: "sha256:trace-manifest",
    provider: "DigiKey · TraceParts",
    surface: "DigiKey",
    adapterVersion: "digikey-models/1",
    evidenceDigest: "sha256:trace-manifest",
    canActivate: false as const,
    artifacts: [
      {
        id: "sha256:step",
        fileName: "TPS62130.step",
        sizeBytes: 4096,
        mediaType: "application/octet-stream",
        evidenceDigest: "sha256:step",
        canActivate: false as const,
        downloadUrl: "/api/supplementary/step",
      },
      {
        id: "sha256:drawing",
        fileName: "TPS62130.dxf",
        sizeBytes: 512,
        mediaType: "application/octet-stream",
        evidenceDigest: "sha256:drawing",
        canActivate: false as const,
        downloadUrl: "/api/supplementary/drawing",
      },
    ],
  },
];

describe("CadVariantSelector", () => {
  it("keeps every provider variant visible and marks only the active whole pair", () => {
    render(
      <CadVariantSelector
        inventories={inventories()}
        pairs={pairs()}
        supplementary={[]}
        onActivatePair={vi.fn()}
      />,
    );

    const kicad = screen.getByRole("region", { name: "KiCad CAD Variants" });
    const altium = screen.getByRole("region", { name: "Altium CAD Variants" });
    expect(within(kicad).getAllByRole("article")).toHaveLength(2);
    expect(within(altium).getAllByRole("article")).toHaveLength(2);
    expect(
      within(kicad).getByRole("article", {
        name: "Ultra Librarian KiCad variant, active in pair",
      }),
    ).toHaveAttribute("aria-current", "true");
    expect(
      within(altium).getByRole("article", {
        name: "Ultra Librarian Altium variant, active in pair",
      }),
    ).toHaveAttribute("aria-current", "true");
    expect(screen.getByText("4 Retained")).toBeInTheDocument();
    expect(screen.getAllByText("Reverified")).toHaveLength(4);
    expect(screen.queryByText("Validated")).not.toBeInTheDocument();
    expect(screen.queryByText(/Checks?$/)).not.toBeInTheDocument();
  });

  it("switches both EDAs with one compare-and-switch request and exposes no single-tool control", async () => {
    const onActivatePair = vi.fn();
    render(
      <CadVariantSelector
        inventories={inventories()}
        pairs={pairs()}
        supplementary={[]}
        onActivatePair={onActivatePair}
      />,
    );

    await userEvent.click(
      screen.getByRole("button", {
        name: "Use SnapMagic for KiCad and Altium",
      }),
    );

    expect(onActivatePair).toHaveBeenCalledWith({
      kicadVariantId: "snap-shared",
      altiumVariantId: "snap-shared",
      expectedActiveKicadVariantId: "ul-shared",
      expectedActiveAltiumVariantId: "ul-shared",
    });
    expect(
      within(screen.getByRole("region", { name: "KiCad CAD Variants" })).queryByRole(
        "button",
      ),
    ).not.toBeInTheDocument();
    expect(
      within(screen.getByRole("region", { name: "Altium CAD Variants" })).queryByRole(
        "button",
      ),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(/same-provider, same-download KiCad and Altium pair are reverified/i),
    ).toBeInTheDocument();
  });

  it("locks the pair switch while its atomic activation is pending", () => {
    render(
      <CadVariantSelector
        inventories={inventories()}
        pairs={pairs()}
        supplementary={[]}
        onActivatePair={vi.fn()}
        activatingPair={{
          kicadVariantId: "snap-shared",
          altiumVariantId: "snap-shared",
        }}
      />,
    );

    const running = screen.getByRole("button", {
      name: "Use SnapMagic for KiCad and Altium",
    });
    expect(running).toBeDisabled();
    expect(running).toHaveAttribute("aria-busy", "true");
    expect(running).toHaveTextContent("Switching Both...");
  });

  it("shows split legacy pointers as stored-only and offers no activation fallback", () => {
    render(
      <CadVariantSelector
        inventories={inventories("snap-shared", "ul-shared")}
        pairs={[]}
        supplementary={[]}
        onActivatePair={vi.fn()}
      />,
    );

    expect(screen.getByText(/No activatable pair is retained/i)).toBeInTheDocument();
    expect(screen.getAllByText("Stored Only")).toHaveLength(2);
    expect(screen.getAllByText(/selection is not pair-active/i)).toHaveLength(2);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByText("Active In Pair")).not.toBeInTheDocument();
  });

  it("renders honest empty evidence and pair-conflict states", () => {
    render(
      <CadVariantSelector
        inventories={[
          { tool: "kicad", activeVariantId: "missing", variants: [variant()] },
        ]}
        pairs={[]}
        supplementary={[]}
        onActivatePair={vi.fn()}
        activationError="The CAD pair changed before this switch completed."
      />,
    );

    expect(
      screen.getByText("No reverified Altium variants are retained for this part."),
    ).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "The CAD pair changed before this switch completed.",
    );
  });

  it("lists supplementary originals separately without any activation control", () => {
    render(
      <CadVariantSelector
        inventories={inventories()}
        pairs={pairs()}
        supplementary={supplementary}
        onActivatePair={vi.fn()}
      />,
    );

    const retained = screen.getByRole("region", {
      name: "Supplementary Retained Artifacts",
    });
    const traceParts = within(retained).getByRole("article", {
      name: "DigiKey · TraceParts retained originals",
    });
    expect(within(traceParts).getByText("TPS62130.step")).toBeInTheDocument();
    expect(within(traceParts).getByText("TPS62130.dxf")).toBeInTheDocument();
    expect(within(traceParts).getByText("Not Activatable")).toBeInTheDocument();
    expect(screen.getByText("2 Originals")).toBeInTheDocument();
    expect(within(traceParts).queryByRole("button")).not.toBeInTheDocument();
  });

  it("fails pair activation closed when either variant lacks reverified evidence", () => {
    const withoutEvidence = inventories();
    withoutEvidence[1] = {
      ...withoutEvidence[1],
      variants: withoutEvidence[1].variants.map((candidate) =>
        candidate.id === "snap-shared"
          ? { ...candidate, verificationState: undefined as never }
          : candidate,
      ),
    };

    render(
      <CadVariantSelector
        inventories={withoutEvidence}
        pairs={pairs()}
        supplementary={[]}
        onActivatePair={vi.fn()}
      />,
    );

    expect(
      screen.getAllByText("Verification Evidence Missing").length,
    ).toBeGreaterThanOrEqual(1);
    expect(
      screen.getByRole("button", {
        name: "Use SnapMagic for KiCad and Altium",
      }),
    ).toBeDisabled();
  });
});
