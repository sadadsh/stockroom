import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { IconBrowser } from "./IconBrowser";

const registry = vi.hoisted(() => {
  const fontAwesome = Array.from({ length: 501 }, (_, index) => ({
    id: `font-awesome.solid.icon-${index}`,
    label: `Icon ${index}`,
    family: "Font Awesome solid",
    category: "interface" as const,
    terms: ["test"],
    viewBox: "0 0 24 24",
    body: '<path d="M2 2h20v20H2z" />',
  }));
  const lucide = [{
    id: "lucide.only",
    label: "Lucide Only",
    family: "Lucide",
    category: "interface" as const,
    terms: ["lucide-only"],
    viewBox: "0 0 24 24",
    body: '<path d="M3 12h18" />',
  }];
  const load = vi.fn(async (family?: string) => {
    if (family === "Font Awesome") return fontAwesome;
    if (family === "Lucide") return lucide;
    return [...fontAwesome, ...lucide];
  });
  const search = vi.fn((query: string, family: string, entries: readonly typeof fontAwesome[number][]) => {
    const terms = query.toLowerCase().trim().split(/\s+/).filter(Boolean);
    return entries.filter((entry) => {
      const inFamily = family === "Font Awesome"
        ? entry.family.startsWith("Font Awesome ")
        : entry.family === family;
      if (family && !inFamily) return false;
      const haystack = [entry.label, entry.family, ...entry.terms].join(" ").toLowerCase();
      return terms.every((term) => haystack.includes(term));
    });
  });
  return { fontAwesome, lucide, load, search };
});

vi.mock("../../design-studio/offlineIconRegistry", () => ({
  DEFAULT_OFFLINE_ICON_FAMILY: "Font Awesome",
  fontAwesomeCatalogEntries: () => registry.fontAwesome,
  loadOfflineIconCollections: registry.load,
  offlineIconFamilies: () => ["Font Awesome", "Lucide", "Phosphor", "Material Symbols"],
  searchOfflineIcons: registry.search,
}));

describe("IconBrowser", () => {
  it("pages through the complete result set instead of silently truncating it", async () => {
    render(<IconBrowser targetViewBox="0 0 24 24" onSelect={vi.fn()} />);
    const user = userEvent.setup();
    const results = screen.getByLabelText("Icon Search Results");

    expect(await within(results).findAllByRole("button", { name: /^Select Icon/ })).toHaveLength(200);
    expect(screen.getByText(/501 offline icons/)).toHaveTextContent("200 of 501 icons shown");
    await user.click(screen.getByRole("button", { name: "Show More Icons" }));
    expect(within(results).getAllByRole("button", { name: /^Select Icon/ })).toHaveLength(400);
    await user.click(screen.getByRole("button", { name: "Show More Icons" }));

    expect(within(results).getAllByRole("button", { name: /^Select Icon/ })).toHaveLength(501);
    expect(screen.getByText(/501 offline icons/)).toHaveTextContent("501 of 501 icons shown");
    expect(screen.queryByRole("button", { name: "Show More Icons" })).not.toBeInTheDocument();
  }, 15_000);

  it("starts in one catalogue and loads only that default family", async () => {
    render(<IconBrowser targetViewBox="0 0 24 24" onSelect={vi.fn()} />);

    await waitFor(() => expect(registry.load).toHaveBeenCalledWith("Font Awesome"));
    expect(screen.getByRole("combobox", { name: "Icon Catalog" })).toHaveValue("Font Awesome");
    expect(await screen.findByRole("button", { name: "Select Icon 0 from Font Awesome solid" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Select Lucide Only from Lucide" })).not.toBeInTheDocument();
  });

  it("loads the selected family and replaces the active search scope", async () => {
    const user = userEvent.setup();
    render(<IconBrowser targetViewBox="0 0 24 24" onSelect={vi.fn()} />);
    const family = screen.getByRole("combobox", { name: "Icon Catalog" });
    await screen.findByRole("button", { name: "Select Icon 0 from Font Awesome solid" });

    await user.selectOptions(family, "Lucide");

    expect(await screen.findByRole("button", { name: "Select Lucide Only from Lucide" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Select Icon 0 from Font Awesome solid" })).not.toBeInTheDocument();
    expect(registry.load.mock.calls.map(([selected]) => selected)).toEqual(["Font Awesome", "Lucide"]);
  });

  it("never returns another catalogue's matches in active-family search", async () => {
    const user = userEvent.setup();
    render(<IconBrowser targetViewBox="0 0 24 24" onSelect={vi.fn()} />);
    const search = screen.getByRole("searchbox", { name: "Search Icon Catalog" });
    await screen.findByRole("button", { name: "Select Icon 0 from Font Awesome solid" });

    await user.type(search, "lucide-only");
    expect(screen.queryByRole("button", { name: "Select Lucide Only from Lucide" })).not.toBeInTheDocument();

    await user.selectOptions(screen.getByRole("combobox", { name: "Icon Catalog" }), "Lucide");
    expect(await screen.findByRole("button", { name: "Select Lucide Only from Lucide" })).toBeVisible();
  });
});
