/**
 * The `react-pdf` stand-in the test environment resolves instead of the real library.
 *
 * pdf.js needs `DOMMatrix`, `Path2D` and a real canvas, none of which jsdom has - importing the
 * library at all throws before a single assertion runs. Polyfilling enough of the browser to make
 * it render would test pdf.js, which is not ours to test; what IS ours is the viewer's own state
 * machine, and this stub is exactly the surface that machine talks to.
 *
 * It honours the library's real contract: `Document` reports success or failure through the same
 * two callbacks, `Page` renders its number, scale and rotation so a test can assert the controls
 * actually moved them, and `Outline` calls back with a page number so table-of-contents navigation
 * can be exercised. A `file` whose bytes begin with the marker below fails instead, which is how a
 * test reaches the failure branch without inventing a network.
 */
import { useEffect, type ReactNode } from "react";

/** A test asks for a load failure by handing the viewer these bytes. */
export const FAIL_MARKER = "STOCKROOM_TEST_PDF_FAILURE";

/** How many pages the stub reports. Fixed, so page navigation has somewhere to go. */
export const STUB_PAGE_COUNT = 3;

export const pdfjs = {
  GlobalWorkerOptions: { workerSrc: "" },
  version: "test",
};

function isFailure(file: unknown): boolean {
  if (file && typeof file === "object" && "url" in (file as Record<string, unknown>)) {
    return String((file as { url: string }).url).includes(FAIL_MARKER);
  }
  if (file && typeof file === "object" && "data" in (file as Record<string, unknown>)) {
    const data = (file as { data: ArrayBuffer }).data;
    try {
      return new TextDecoder().decode(new Uint8Array(data)).includes(FAIL_MARKER);
    } catch {
      return false;
    }
  }
  return false;
}

export function Document({
  file,
  onLoadSuccess,
  onLoadError,
  children,
  className,
}: {
  file: unknown;
  onLoadSuccess?: (pdf: { numPages: number }) => void;
  onLoadError?: (error: Error) => void;
  children?: ReactNode;
  className?: string;
  [key: string]: unknown;
}) {
  const failed = isFailure(file);
  useEffect(() => {
    if (failed) onLoadError?.(new Error("Invalid PDF structure."));
    else onLoadSuccess?.({ numPages: STUB_PAGE_COUNT });
    // The identity of the file is the only trigger; the callbacks are fresh every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [failed, file]);
  return (
    <div data-testid="pdf-document" className={className}>
      {children}
    </div>
  );
}

export function Page({
  pageNumber,
  scale,
  rotate,
}: {
  pageNumber: number;
  scale?: number;
  rotate?: number;
  [key: string]: unknown;
}) {
  return (
    <div
      data-testid="pdf-page"
      data-page-number={pageNumber}
      data-scale={scale}
      data-rotate={rotate}
    />
  );
}

export function Outline({
  onItemClick,
}: {
  onItemClick?: (item: { pageNumber: number }) => void;
  [key: string]: unknown;
}) {
  return (
    <button
      type="button"
      data-testid="pdf-outline-item"
      onClick={() => onItemClick?.({ pageNumber: 2 })}
    >
      Electrical Characteristics
    </button>
  );
}

export default { Document, Page, Outline, pdfjs };
