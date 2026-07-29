import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  CadVariantSelector,
  type CadVariant,
  type CadVariantInventory,
} from "./CadVariantSelector";

function variant(overrides: Partial<CadVariant> = {}): CadVariant {
  return {
    id: "ul-native",
    provider: "Ultra Librarian",
    format: "Altium Designer (Native)",
    artifacts: [
      { kind: "symbol", fileName: "Part.SchLib" },
      { kind: "footprint", fileName: "Part.PcbLib" },
      { kind: "model", fileName: "Part.step" },
    ],
    evidenceDigest: "aabbccddeeff00112233445566778899",
    validationChecks: 12,
    trustRank: 10,
    trustLabel: "Manufacturer Verified",
    trustReason: "The provider publishes manufacturer-authorized CAD.",
    ...overrides,
  };
}

function inventories(): CadVariantInventory[] {
  return [
    {
      tool: "kicad",
      activeVariantId: "snap-kicad",
      variants: [
        variant({
          id: "snap-kicad",
          provider: "SnapMagic",
          format: "KiCad 9",
          trustRank: 20,
          trustLabel: "Validated Fallback",
        }),
        variant({
          id: "ul-kicad",
          format: "KiCad 10",
          artifacts: [
            { kind: "symbol", fileName: "Part.kicad_sym" },
            { kind: "footprint", fileName: "Part.kicad_mod" },
            { kind: "model", fileName: "Part.step" },
          ],
        }),
      ],
    },
    {
      tool: "altium",
      activeVariantId: "ul-native",
      variants: [variant()],
    },
  ];
}

describe("CadVariantSelector", () => {
  it("shows every retained KiCad and Altium variant with the active pointer separate", () => {
    render(<CadVariantSelector inventories={inventories()} onActivate={vi.fn()} />);

    const kicad = screen.getByRole("region", { name: "KiCad CAD Variants" });
    expect(within(kicad).getAllByRole("article")).toHaveLength(2);
    expect(
      within(kicad).getByText(
        (_text, node) =>
          node?.tagName === "SPAN" &&
          node.classList.contains("ml-auto") &&
          node.textContent === "Active: SnapMagic",
      ),
    ).toBeInTheDocument();
    expect(
      within(kicad).getByRole("article", { name: "SnapMagic KiCad variant, active" }),
    ).toHaveAttribute("aria-current", "true");

    const altium = screen.getByRole("region", { name: "Altium CAD Variants" });
    expect(within(altium).getByText("Altium Designer (Native)")).toBeInTheDocument();
    expect(
      within(altium).getByRole("article", {
        name: "Ultra Librarian Altium variant, active",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("3 Retained")).toBeInTheDocument();
  });

  it("orders by supplied trust policy, making Ultra Librarian preferred without hard-coding it", () => {
    render(<CadVariantSelector inventories={inventories()} onActivate={vi.fn()} />);

    const kicad = screen.getByRole("region", { name: "KiCad CAD Variants" });
    const rows = within(kicad).getAllByRole("article");
    expect(rows[0]).toHaveAccessibleName("Ultra Librarian KiCad variant");
    expect(within(rows[0]).getByText("Preferred")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Fallback")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Active")).toBeInTheDocument();
  });

  it("requests a compare-and-switch activation without mutating or removing variants", async () => {
    const onActivate = vi.fn();
    render(<CadVariantSelector inventories={inventories()} onActivate={onActivate} />);

    await userEvent.click(
      screen.getByRole("button", { name: "Use Ultra Librarian variant for KiCad" }),
    );

    expect(onActivate).toHaveBeenCalledWith({
      tool: "kicad",
      variantId: "ul-kicad",
      expectedActiveVariantId: "snap-kicad",
    });
    expect(screen.getAllByRole("article")).toHaveLength(3);
    expect(
      screen.getByText(/Switching keeps every downloaded variant and its evidence/i),
    ).toBeInTheDocument();
  });

  it("locks competing selections while a switch is pending and names the running action", () => {
    const data = inventories();
    data[1].variants = [
      ...data[1].variants,
      variant({
        id: "snap-altium",
        provider: "SnapMagic",
        trustRank: 20,
        trustLabel: "Validated Fallback",
      }),
    ];
    render(
      <CadVariantSelector
        inventories={data}
        onActivate={vi.fn()}
        activating={{ tool: "kicad", variantId: "ul-kicad" }}
      />,
    );

    const running = screen.getByRole("button", {
      name: "Use Ultra Librarian variant for KiCad",
    });
    expect(running).toBeDisabled();
    expect(running).toHaveAttribute("aria-busy", "true");
    expect(running).toHaveTextContent("Switching...");
    expect(
      screen.getByRole("button", { name: "Use SnapMagic variant for Altium" }),
    ).toBeDisabled();
  });

  it("renders honest empty and stale-pointer states", () => {
    render(
      <CadVariantSelector
        inventories={[
          { tool: "kicad", activeVariantId: "missing", variants: [variant()] },
        ]}
        onActivate={vi.fn()}
        activationError="The library changed before this switch completed."
      />,
    );

    expect(
      screen.getByText("The active KiCad variant is unavailable. Choose a retained variant."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("No validated Altium variants are retained for this part."),
    ).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "The library changed before this switch completed.",
    );
  });
});
