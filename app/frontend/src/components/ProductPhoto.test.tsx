/**
 * The pulled product photo renders as a REAL image (owner 2026-07-24: "the pulled
 * images dont render") with the two-lane fallback: direct <img> -> backend proxy ->
 * the caller's fallback node. Never a broken-image glyph.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { ApiError, api } from "../api/client";
import { ProductPhoto, productPhotoUrl } from "./ProductPhoto";

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
