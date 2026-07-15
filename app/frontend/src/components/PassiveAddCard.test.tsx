import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { api } from "../api/client";
import type { PartDetail, PassivePreview } from "../api/types";
import { ToastProvider } from "../lib/toast";
import { PassiveAddCard } from "./PassiveAddCard";

vi.mock("../api/client", async (im) => {
  const actual = await im<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      facets: vi.fn(),
      passivePreview: vi.fn(),
      passiveAdd: vi.fn(),
    },
  };
});
const mockApi = vi.mocked(api);

const PREVIEW: PassivePreview = {
  record: {
    id: "",
    display_name: "ERJ-P03F1101V",
    category: "Resistors",
    description: "Resistor, 1.1 kOhm, 1%, 0603",
    tags: [],
    mpn: "ERJ-P03F1101V",
    manufacturer: "Panasonic",
    passive: true,
    datasheet: null,
    purchase: [
      {
        vendor: "Mouser",
        url: "https://www.mouser.com/en/ProductDetail/Panasonic/ERJ-P03F1101V",
        price_breaks: [],
        stock: null,
        currency: "",
        fetched_at: "",
      },
    ],
    symbol: { lib: "Device", name: "R" },
    footprint: { lib: "Resistor_SMD", name: "R_0603_1608Metric" },
    model: null,
    provenance: null,
    hashes: null,
    enrichment: {},
    specs: {
      Resistance: "1.1 kOhm",
      Tolerance: "1%",
      Package: "0603",
      Power: "0.2 W",
      Symbol: "Device:R",
      Footprint: "Resistor_SMD:R_0603_1608Metric",
      "3D Model": "Resistor_SMD.3dshapes/R_0603_1608Metric.wrl",
    },
  } as PartDetail,
  gaps: ["datasheet"],
  stock_present: true,
};

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>{node}</ToastProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockApi.facets.mockResolvedValue({
    by_category: { Resistors: 3, ICs: 5 },
    by_manufacturer: { Panasonic: 2, Yageo: 1 },
    complete: 6,
    incomplete: 2,
  });
  mockApi.passivePreview.mockResolvedValue(PREVIEW);
  mockApi.passiveAdd.mockResolvedValue({
    ...PREVIEW.record,
    id: "erj_p03f1101v",
  } as PartDetail);
});

test("previewing a passive shows decoded description and referenced stock assets", async () => {
  wrap(<PassiveAddCard toast={() => {}} />);
  await userEvent.type(
    screen.getByLabelText("Passive MPN or Mouser URL"),
    "ERJ-P03F1101V",
  );
  await userEvent.click(screen.getByRole("button", { name: "Preview" }));

  await waitFor(() =>
    expect(screen.getByText("Resistor, 1.1 kOhm, 1%, 0603")).toBeInTheDocument(),
  );
  expect(screen.getByText("Device:R")).toBeInTheDocument();
  expect(
    screen.getByText("Resistor_SMD:R_0603_1608Metric"),
  ).toBeInTheDocument();
  // the Mouser buy-link is surfaced verbatim
  expect(
    screen.getByText(
      "https://www.mouser.com/en/ProductDetail/Panasonic/ERJ-P03F1101V",
    ),
  ).toBeInTheDocument();
  // datasheet is the one honest gap
  expect(screen.getByText(/Still needed to add: datasheet/)).toBeInTheDocument();
});

test("filling the datasheet URL and adding calls passiveAdd with it", async () => {
  wrap(<PassiveAddCard toast={() => {}} />);
  await userEvent.type(
    screen.getByLabelText("Passive MPN or Mouser URL"),
    "ERJ-P03F1101V",
  );
  await userEvent.click(screen.getByRole("button", { name: "Preview" }));
  await waitFor(() => screen.getByRole("button", { name: "Add To Library" }));

  await userEvent.type(
    screen.getByLabelText("Datasheet URL"),
    "https://industrial.panasonic.com/x.pdf",
  );
  await userEvent.click(screen.getByRole("button", { name: "Add To Library" }));

  await waitFor(() => expect(mockApi.passiveAdd).toHaveBeenCalled());
  expect(mockApi.passiveAdd).toHaveBeenCalledWith(
    expect.objectContaining({
      input: "ERJ-P03F1101V",
      datasheet_url: "https://industrial.panasonic.com/x.pdf",
    }),
  );
});
