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
  status: "ok",
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

// An MPN no decoder knows (a Wurth part): the preview asks for a manual kind + package.
const NEEDS: PassivePreview = {
  status: "needs_input",
  mpn: "560112116151",
  manufacturer: "Wurth Elektronik",
  suggested_kind: null,
  packages: ["0402", "0603", "0805", "1206", "1210"],
  message: "could not decode '560112116151'; choose a kind and package to add it",
};

// The record the backend builds once kind + package are picked.
const MANUAL_OK: PassivePreview = {
  status: "ok",
  record: {
    ...PREVIEW.record,
    display_name: "4.7 µH 1210 Inductor",
    category: "Inductors",
    description: "Inductor, 4.7 µH, 1210",
    mpn: "560112116151",
    manufacturer: "Wurth Elektronik",
    symbol: { lib: "Device", name: "L" },
    footprint: { lib: "Inductor_SMD", name: "L_1210_3225Metric" },
    purchase: [
      {
        vendor: "Mouser",
        url: "https://www.mouser.com/c/?q=560112116151",
        price_breaks: [],
        stock: null,
        currency: "",
        fetched_at: "",
      },
    ],
    specs: {
      Inductance: "4.7 µH",
      Package: "1210",
      Symbol: "Device:L",
      Footprint: "Inductor_SMD:L_1210_3225Metric",
      "3D Model": "Inductor_SMD.3dshapes/L_1210_3225Metric.wrl",
    },
  } as PartDetail,
  gaps: [],
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

test("an undecodable MPN reveals manual pickers and adds with the picked kind and package", async () => {
  mockApi.passivePreview.mockResolvedValueOnce(NEEDS).mockResolvedValue(MANUAL_OK);
  mockApi.passiveAdd.mockResolvedValue({
    ...(MANUAL_OK as { record: PartDetail }).record,
    id: "560112116151",
  } as PartDetail);
  wrap(<PassiveAddCard toast={() => {}} />);

  await userEvent.type(
    screen.getByLabelText("Passive MPN or Mouser URL"),
    "560112116151",
  );
  await userEvent.click(screen.getByRole("button", { name: "Preview" }));

  // decode missed -> the manual pickers appear (kind + package)
  await waitFor(() => screen.getByLabelText("Kind"));
  await userEvent.selectOptions(screen.getByLabelText("Kind"), "inductor");
  await userEvent.selectOptions(screen.getByLabelText("Package"), "1210");

  // re-preview with the picks builds a real record
  await userEvent.click(screen.getByRole("button", { name: "Preview" }));
  await waitFor(() => screen.getByRole("button", { name: "Add To Library" }));
  expect(
    screen.getByText("Inductor_SMD:L_1210_3225Metric"),
  ).toBeInTheDocument();

  await userEvent.type(
    screen.getByLabelText("Datasheet URL"),
    "https://www.we-online.com/x.pdf",
  );
  await userEvent.click(screen.getByRole("button", { name: "Add To Library" }));

  await waitFor(() => expect(mockApi.passiveAdd).toHaveBeenCalled());
  expect(mockApi.passiveAdd).toHaveBeenCalledWith(
    expect.objectContaining({
      input: "560112116151",
      kind: "inductor",
      package: "1210",
    }),
  );
});

test("changing a picker after preview hides Add until re-previewed", async () => {
  mockApi.passivePreview.mockResolvedValueOnce(NEEDS).mockResolvedValue(MANUAL_OK);
  wrap(<PassiveAddCard toast={() => {}} />);
  await userEvent.type(
    screen.getByLabelText("Passive MPN or Mouser URL"),
    "560112116151",
  );
  await userEvent.click(screen.getByRole("button", { name: "Preview" }));
  await waitFor(() => screen.getByLabelText("Kind"));
  await userEvent.selectOptions(screen.getByLabelText("Kind"), "inductor");
  await userEvent.selectOptions(screen.getByLabelText("Package"), "1210");
  await userEvent.click(screen.getByRole("button", { name: "Preview" }));
  await waitFor(() => screen.getByRole("button", { name: "Add To Library" }));

  // change the package without re-previewing: the shown record is now stale, so Add
  // must disappear (it would otherwise commit a part different from what is shown)
  await userEvent.selectOptions(screen.getByLabelText("Package"), "0805");
  expect(
    screen.queryByRole("button", { name: "Add To Library" }),
  ).not.toBeInTheDocument();
});

test("editing the MPN after picking clears the stale manual picks", async () => {
  mockApi.passivePreview.mockResolvedValueOnce(NEEDS).mockResolvedValue(MANUAL_OK);
  wrap(<PassiveAddCard toast={() => {}} />);
  await userEvent.type(
    screen.getByLabelText("Passive MPN or Mouser URL"),
    "560112116151",
  );
  await userEvent.click(screen.getByRole("button", { name: "Preview" }));
  await waitFor(() => screen.getByLabelText("Kind"));
  await userEvent.selectOptions(screen.getByLabelText("Kind"), "inductor");

  // editing the MPN invalidates the pickers made for the old part: they must reset,
  // so a fresh decodable MPN is never coerced into the stale kind/package
  await userEvent.type(screen.getByLabelText("Passive MPN or Mouser URL"), "X");
  expect(screen.queryByLabelText("Kind")).not.toBeInTheDocument();
});
