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
import { useTheme } from "../lib/theme";

export function PreviewImage({
  kind,
  partId,
  fallback,
}: {
  kind: "symbol" | "footprint";
  partId: string;
  fallback: ReactNode;
}) {
  const query = usePreviewSvg(kind, partId, true);
  const { theme } = useTheme();
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
      className="max-h-[92px] max-w-[86%] object-contain"
      style={{ filter: theme === "dark" ? "invert(1)" : "none" }}
    />
  );
}
