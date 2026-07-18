/**
 * The live monochrome preview thumbnail shown inside a Files card (M6d). It renders the
 * real symbol/footprint (fetched in the ?bw variant, re-tinted to the theme) at a fixed
 * fit-to-box size, non-interactive; the pan/zoom lives in the expanded PreviewModal. If
 * the render is not available on this machine (no kicad-cli, or an error) it falls back
 * to the line-art glyph so the card still reads as "linked", never a broken image.
 */
import type { ReactNode } from "react";
import { usePreviewSvg } from "../api/queries";
import { useObjectUrl } from "../lib/useObjectUrl";

export function PreviewImage({
  kind,
  partId,
  fallback,
}: {
  kind: "symbol" | "footprint";
  partId: string;
  fallback: ReactNode;
}) {
  const query = usePreviewSvg(kind, partId);
  const url = useObjectUrl(query.data);

  if (query.isError || (!query.isLoading && !url)) {
    // linked, but no live render here (kicad-cli absent / render failed): the glyph
    return <>{fallback}</>;
  }
  if (!url) {
    return <div className="h-[52px] w-[52px] animate-pulse rounded-control bg-raise2" />;
  }
  return (
    <img
      src={url}
      alt={`${kind} preview`}
      draggable={false}
      // Fit-to-box and object-contain so the small-intrinsic KiCad SVG upscales without
      // clipping. A footprint's bounding box is TIGHT (courtyard hugs the pads), so it would
      // otherwise fill the whole tile - give it generous padding so it sits centered with
      // breathing room; a symbol already carries its own whitespace, so it needs less.
      className={
        "h-full w-full object-contain " + (kind === "footprint" ? "p-10" : "p-3")
      }
      // The KiCad SVGs are black line-art; invert(0.66) turns black -> the SAME neutral gray
      // (~#a8a8ac) the 3D model renders in, so the symbol / footprint / 3D read as one set on
      // both themes (a mid gray shows on the light card AND the dark card).
      style={{ filter: "invert(0.66)" }}
    />
  );
}
