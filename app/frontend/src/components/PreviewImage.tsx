/**
 * The live monochrome preview thumbnail shown inside a Files card (M6d). It renders the
 * real symbol/footprint (fetched in the ?bw variant, re-tinted to the theme) at a fixed
 * fit-to-box size, non-interactive; the pan/zoom lives in the expanded PreviewModal. If
 * the render is not available on this machine (no kicad-cli, or an error) it falls back
 * to the line-art glyph so the card still reads as "linked", never a broken image.
 */
import type { ReactNode } from "react";
import { usePreviewSvg } from "../api/queries";
import { useTheme } from "../lib/theme";
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
  const { theme } = useTheme();

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
      // clipping. The backend refits every preview's viewBox to the art it actually draws and
      // bakes a 2% margin in, so the SVG arrives already framed and the tile owes it very little.
      // The footprint used to carry `p-10` on the belief that its box hugged the pads and would
      // otherwise fill the tile. The box did NOT hug the pads (kicad-cli sized it from undrawn
      // silkscreen and text), and 80px of padding inside a 111px tile left 31px to draw in - so
      // the "footprint preview is a near-invisible sliver" complaint was mostly THIS, not the
      // render. It keeps LESS padding than the symbol because a land pattern is sparse line-and-pad
      // art that needs every pixel to read, while a symbol carries its own internal whitespace.
      className={"h-full w-full object-contain " + (kind === "footprint" ? "p-1" : "p-3")}
      // The KiCad SVGs are black line-art, so they invert for a dark surface and are left ALONE on
      // a light one - the same rule StockAssetPreview, SvgViewport and SvgDiffViewport already use.
      //
      // This was `invert(0.66)`, unconditionally, on the belief (stated in the comment it replaces)
      // that one mid gray "shows on the light card AND the dark card" and made symbol / footprint /
      // 3D read as one set. MEASURED on the owner's real Windows window 2026-07-25, that belief is
      // false: black line-art landed at rgb(162), which is 2.34:1 against the light card - under the
      // 3:1 non-text floor of WCAG 1.4.11 - and the symbol's dominant stroke reached rgb(234), i.e.
      // 1.10:1, invisible. The SAME asset in the modal measured 14.87:1, a 6.3x spread on one asset
      // between two surfaces. The constant only ever worked on dark (6.41:1 there).
      //
      // REJECTED: keeping a partial invert and merely making it theme-conditional. It would preserve
      // the tonal match with the 3D model's neutral gray, but it buys that by holding the 2D art
      // below the contrast floor, and it would still disagree with the modal that shows the very
      // same file. Matching the 3D model is the weakest of the three consistency goals and it is
      // fixable at the 3D MATERIAL, which is where a tone decision belongs - not by desaturating
      // line-art whose whole job is to be read.
      style={{ filter: theme === "dark" ? "invert(1)" : "none" }}
    />
  );
}
