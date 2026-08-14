import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { OfficialApiDataView } from "../../api/dossierTypes";
import { OfficialApiDataSection } from "./OfficialApiDataSection";

const DATA: OfficialApiDataView = {
  providerCount: 2,
  fieldCount: 4,
  providers: [
    {
      provider: "mouser",
      providerLabel: "Mouser",
      state: "success",
      fetchedAt: "2026-08-14T12:00:00Z",
      payloadRef: "sourced/id/mouser.json",
      fieldCount: 2,
      rows: [
        {
          path: "/SearchResults/Parts/0/PriceBreaks/0/Price",
          endpoint: "SearchResults",
          kind: "string",
          value: "$1.23",
          displayValue: "$1.23",
        },
        {
          path: "/SearchResults/Parts/0/FactoryStock",
          endpoint: "SearchResults",
          kind: "null",
          value: null,
          displayValue: "null",
        },
      ],
    },
    {
      provider: "digikey",
      providerLabel: "DigiKey",
      state: "success",
      fetchedAt: "2026-08-14T12:01:00Z",
      payloadRef: "sourced/id/digikey.json",
      fieldCount: 2,
      rows: [
        {
          path: "/product_details/Product/Parameters/0/ParameterText",
          endpoint: "product_details",
          kind: "string",
          value: "Bandwidth",
          displayValue: "Bandwidth",
        },
        {
          path: "/media/MediaLinks",
          endpoint: "media",
          kind: "array",
          value: [],
          displayValue: "[]",
        },
      ],
    },
  ],
};

describe("complete official API data", () => {
  it("keeps both providers, exact paths, explicit nulls, and empty containers", async () => {
    const user = userEvent.setup();
    render(<OfficialApiDataSection data={DATA} />);
    await user.click(screen.getByText("Mouser"));
    await user.click(screen.getByText("SearchResults"));
    expect(screen.getByText("/SearchResults/Parts/0/FactoryStock")).toBeInTheDocument();
    expect(screen.getByText("null")).toBeInTheDocument();

    await user.click(screen.getByText("DigiKey"));
    await user.click(screen.getByText("media"));
    expect(screen.getByText("/media/MediaLinks")).toBeInTheDocument();
    expect(screen.getByText("[]")).toBeInTheDocument();
  });

  it("paginates large endpoint disclosures so only one bounded page mounts", async () => {
    const user = userEvent.setup();
    const rows: OfficialApiDataView["providers"][number]["rows"] = Array.from(
      { length: 250 },
      (_, index) => ({
      path: `/Products/${index}`,
      endpoint: "Products",
      kind: "number",
      value: index,
        displayValue: String(index),
      }),
    );
    const data: OfficialApiDataView = {
      providerCount: 1,
      fieldCount: rows.length,
      providers: [{
        provider: "digikey",
        providerLabel: "DigiKey",
        state: "success",
        fetchedAt: "2026-08-14T12:01:00Z",
        payloadRef: "sourced/id/digikey.json",
        fieldCount: rows.length,
        rows,
      }],
    };

    render(<OfficialApiDataSection data={data} />);
    await user.click(screen.getByText("DigiKey"));
    await user.click(screen.getByText("Products"));
    expect(document.querySelectorAll('[data-dev-id="component-browser.official-api-row"]')).toHaveLength(100);
    expect(screen.getByText("/Products/0")).toBeInTheDocument();
    expect(screen.queryByText("/Products/100")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(document.querySelectorAll('[data-dev-id="component-browser.official-api-row"]')).toHaveLength(100);
    expect(screen.getByText("/Products/100")).toBeInTheDocument();
    expect(screen.queryByText("/Products/0")).toBeNull();
  });

  it("searches every provider path and value without changing the retained total", async () => {
    const user = userEvent.setup();
    render(<OfficialApiDataSection data={DATA} />);
    await user.type(screen.getByRole("searchbox", { name: "Search official API data" }), "Bandwidth");

    const section = document.querySelector<HTMLElement>(
      '[data-dev-id="component-browser.official-api-data"]',
    )!;
    expect(within(section).getByText("Bandwidth")).toBeInTheDocument();
    expect(within(section).queryByText("$1.23")).toBeNull();
    expect(within(section).getByText("4")).toBeInTheDocument();
  });
});
