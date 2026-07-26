/**
 * The pulled product photo renders as a REAL image (owner 2026-07-24: "the pulled
 * images dont render") with the two-lane fallback: direct <img> -> backend proxy ->
 * the caller's fallback node. Never a broken-image glyph.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { ApiError, api } from "../api/client";
import { PhotoCard, PhotoTrigger, ProductPhoto, partPhotos, productPhotoUrl } from "./ProductPhoto";

vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return {
    ...actual,
    api: { ...actual.api, productImage: vi.fn() },
  };
});

const mockApi = vi.mocked(api);

function wrap(ui: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

const URL_ = "https://mm.digikey.com/Images/part.jpg";

beforeEach(() => {
  mockApi.productImage.mockResolvedValue(
    new Blob([new Uint8Array([1, 2, 3])], { type: "image/jpeg" }),
  );
});

describe("productPhotoUrl", () => {
  it("reads a plain-string Image spec (candidate / record shape)", () => {
    expect(productPhotoUrl({ Image: URL_ })).toBe(URL_);
  });

  it("reads a Sourced DTO Image spec (EnrichmentResult shape)", () => {
    expect(productPhotoUrl({ Image: { value: URL_, source: "mouser" } })).toBe(URL_);
  });

  it("is empty for junk, non-http values, and absent specs", () => {
    expect(productPhotoUrl(undefined)).toBe("");
    expect(productPhotoUrl({})).toBe("");
    expect(productPhotoUrl({ Image: "not a url" })).toBe("");
    expect(productPhotoUrl({ Image: 42 })).toBe("");
    expect(productPhotoUrl({ Image: { value: null } })).toBe("");
  });
});

describe("ProductPhoto", () => {
  it("renders the direct <img> first and never calls the proxy", () => {
    wrap(<ProductPhoto url={URL_} alt="part photo" />);
    const img = screen.getByRole("img", { name: "part photo" });
    expect(img).toHaveAttribute("src", URL_);
    expect(mockApi.productImage).not.toHaveBeenCalled();
  });

  it("falls back to the proxied blob when the direct hotlink errors", async () => {
    wrap(<ProductPhoto url={URL_} alt="part photo" />);
    fireEvent.error(screen.getByRole("img", { name: "part photo" }));
    await waitFor(() => {
      expect(mockApi.productImage).toHaveBeenCalledWith(URL_);
      const img = screen.getByRole("img", { name: "part photo" });
      expect(img.getAttribute("src") ?? "").toMatch(/^blob:|^data:/);
    });
  });

  it("renders the fallback when both lanes fail", async () => {
    mockApi.productImage.mockRejectedValue(new ApiError(404, "No image at that URL"));
    wrap(<ProductPhoto url={URL_} alt="part photo" fallback={<span>glyph</span>} />);
    fireEvent.error(screen.getByRole("img", { name: "part photo" }));
    await waitFor(() => {
      expect(screen.queryByRole("img")).toBeNull();
      expect(screen.getByText("glyph")).toBeInTheDocument();
    });
  });

  it("renders the fallback (not a broken img) when there is no url", () => {
    wrap(<ProductPhoto url="" alt="part photo" fallback={<span>glyph</span>} />);
    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.getByText("glyph")).toBeInTheDocument();
  });
});

describe("PhotoTrigger + PhotoCard (owner 2026-07-24: hidden until clicked)", () => {
  it("renders no image until the chip is clicked, then opens the viewer card", async () => {
    const user = userEvent.setup();
    wrap(<PhotoTrigger url={URL_} partName="TPD6E05U06RVZR" />);
    // hidden by default: the chip only, no <img> anywhere
    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();

    await user.click(screen.getByRole("button", { name: /View Photo/i }));
    const dialog = screen.getByRole("dialog", { name: /TPD6E05U06RVZR/ });
    expect(dialog).toBeInTheDocument();
    expect(screen.getByRole("img")).toHaveAttribute("src", URL_);
  });

  it("closes on Escape and on the close button", async () => {
    const user = userEvent.setup();
    wrap(<PhotoTrigger url={URL_} partName="X" />);
    await user.click(screen.getByRole("button", { name: /View Photo/i }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();

    await user.click(screen.getByRole("button", { name: /View Photo/i }));
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("renders nothing at all without a url", () => {
    const { container } = wrap(<PhotoTrigger url="" partName="X" />);
    expect(container.querySelector("button")).toBeNull();
  });
});

describe("partPhotos + the carousel", () => {
  it("keeps every distributor's photo, not just the one that won the specs slot", () => {
    // Both adapters write specs["Image"] with setdefault, so the second vendor's genuinely
    // different photograph survives only in alternates. It was reaching the record and then
    // being shown to nobody.
    const shots = partPhotos(
      { Image: { value: "https://mouser.com/a.jpg", source: "mouser" } },
      { Image: [{ value: "https://digikey.com/b.jpg", source: "digikey", confidence: "high" }] },
    );
    // The ORIGINAL guarantee, unchanged: both photographs survive. Asserted as a set so it states
    // "nothing was dropped" without also pinning an order, which is what this test is really for.
    expect(new Set(shots.map((s) => s.url))).toEqual(
      new Set(["https://mouser.com/a.jpg", "https://digikey.com/b.jpg"]),
    );
    // and each names its vendor, because WHICH shot you are looking at is the reason to page
    expect(new Set(shots.map((s) => s.vendor))).toEqual(new Set(["Mouser", "DigiKey"]));
  });

  // RE-BASELINED 2026-07-26, and the order this replaces was correct at the time: it asserted
  // Mouser-then-DigiKey, i.e. `setdefault` arrival order. The owner's complaint is precisely that
  // ("the digikey one is much better than mouser"), so quality order now decides the hero slot.
  it("leads with the higher-quality DigiKey photograph, not whoever won the specs slot", () => {
    const shots = partPhotos(
      { Image: { value: "https://mouser.com/a.jpg", source: "mouser" } },
      { Image: [{ value: "https://digikey.com/b.jpg", source: "digikey", confidence: "high" }] },
    );
    expect(shots.map((s) => s.vendor)).toEqual(["DigiKey", "Mouser"]);
    // the hero slot is the FIRST entry, so this is the thumbnail and the carousel's opening frame
    expect(shots[0].url).toBe("https://digikey.com/b.jpg");
  });

  it("humanises an internal source key rather than showing the lane suffix", () => {
    // "mouser_web" is the scraper lane, not a company; the punch list records it leaking as a
    // vendor name elsewhere in the UI.
    const shots = partPhotos({ Image: { value: "https://x/a.jpg", source: "mouser_web" } }, null);
    expect(shots[0].vendor).toBe("Mouser");
  });

  it("does not page through the same photograph twice", () => {
    // Two sources naming the SAME image is the common case; a carousel of identical shots reads
    // as broken.
    const shots = partPhotos(
      { Image: { value: "https://x/a.jpg", source: "mouser" } },
      { Image: [{ value: "https://x/a.jpg", source: "digikey", confidence: "high" }] },
    );
    expect(shots).toHaveLength(1);
  });

  it("ignores a non-URL value instead of offering a broken slide", () => {
    const shots = partPhotos(
      { Image: { value: "not-a-url", source: "mouser" } },
      { Image: [{ value: 42, source: "digikey", confidence: "high" }] },
    );
    expect(shots).toEqual([]);
  });

  it("shows a counter and pagers only when there is more than one photo", () => {
    const { rerender } = wrap(
      <PhotoCard
        open
        photos={[{ url: "https://x/a.jpg", vendor: "Mouser" }]}
        partName="P"
        onClose={() => {}}
      />,
    );
    expect(document.querySelector('[data-dev-id="preview.photo-count"]')).toBeNull();
    expect(document.querySelector('[data-dev-id="preview.photo-next"]')).toBeNull();

    rerender(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <PhotoCard
          open
          photos={[
            { url: "https://x/a.jpg", vendor: "Mouser" },
            { url: "https://x/b.jpg", vendor: "DigiKey" },
          ]}
          partName="P"
          onClose={() => {}}
        />
      </QueryClientProvider>,
    );
    expect(document.querySelector('[data-dev-id="preview.photo-count"]')!.textContent).toBe("1 / 2");
    expect(document.querySelector('[data-dev-id="preview.photo-vendor"]')!.textContent).toBe("Mouser");
  });

  it("pages to the next photo and names its vendor", async () => {
    const user = userEvent.setup();
    wrap(
      <PhotoCard
        open
        photos={[
          { url: "https://x/a.jpg", vendor: "Mouser" },
          { url: "https://x/b.jpg", vendor: "DigiKey" },
        ]}
        partName="P"
        onClose={() => {}}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Next Photo" }));
    expect(document.querySelector('[data-dev-id="preview.photo-count"]')!.textContent).toBe("2 / 2");
    expect(document.querySelector('[data-dev-id="preview.photo-vendor"]')!.textContent).toBe("DigiKey");
    // wraps around rather than dead-ending on the last slide
    await user.click(screen.getByRole("button", { name: "Next Photo" }));
    expect(document.querySelector('[data-dev-id="preview.photo-count"]')!.textContent).toBe("1 / 2");
  });
});
