import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { EnrichmentResult } from "../api/types";
import { PulledDepth } from "./PulledDepth";

function sf(value: unknown) {
  return { value, source: "mouser_web", confidence: "medium" };
}

const FULL: EnrichmentResult = {
  category: "Resistors",
  mpn: sf("ERJ-P03F1101V"),
  manufacturer: sf("Panasonic"),
  description: null,
  datasheet_url: null,
  stock: sf(5616),
  package: null,
  lifecycle: sf("Active"),
  lead_time: sf("15 Weeks"),
  product_url: sf("https://www.mouser.com/x"),
  dist_pns: { mouser: "667-ERJ-P03F1101V" },
  price_breaks: [
    { qty: 1, price: 0.31, currency: "USD" },
    { qty: 10, price: 0.163, currency: "USD" },
    { qty: 1000, price: 0.063, currency: "USD" },
    { qty: 25000, price: 0.043, currency: "USD" },
  ],
  specs: {},
  add_plan: null,
  schema_version: 1,
};

describe("PulledDepth", () => {
  it("surfaces the stock, lead time, lifecycle and best price the lookup pulled", () => {
    render(<PulledDepth result={FULL} />);
    expect(screen.getByText("5,616 in stock")).toBeInTheDocument();
    expect(screen.getByText("15 Weeks")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    // best price = the lowest unit price across the ladder (the high-quantity break).
    expect(screen.getByText("From $0.043 / ea")).toBeInTheDocument();
  });

  it("renders the full price-break ladder with thousands-separated quantities", () => {
    render(<PulledDepth result={FULL} />);
    expect(screen.getByText("25,000")).toBeInTheDocument();
    expect(screen.getByText("1,000")).toBeInTheDocument();
    // a clean sub-dollar price keeps its precision and drops trailing zeros.
    expect(screen.getByText("$0.31")).toBeInTheDocument();
    expect(screen.getByText("$0.063")).toBeInTheDocument();
  });

  it("renders nothing when a lookup carried no sourcing depth", () => {
    const empty: EnrichmentResult = {
      ...FULL,
      stock: null,
      lifecycle: null,
      lead_time: null,
      price_breaks: [],
    };
    const { container } = render(<PulledDepth result={empty} />);
    expect(container).toBeEmptyDOMElement();
  });
});
