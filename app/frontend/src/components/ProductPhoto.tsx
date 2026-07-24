/**
 * The pulled product photograph (specs["Image"], a vendor CDN URL), rendered as a real
 * image with a two-lane fallback: the direct <img> first (zero backend load), and when
 * the CDN refuses the hotlink (Mouser sits behind Akamai) the backend image proxy
 * (/api/enrich/image, disk-cached) via an authenticated blob. When both lanes fail the
 * `fallback` renders instead - never a broken-image glyph.
 */
import { useEffect, useState, type ReactNode } from "react";
import { useProductImage } from "../api/queries";
import { useObjectUrl } from "../lib/useObjectUrl";

/** The photo URL out of a spec bag - either shape: a plain string (a candidate's or a
 * committed record's specs) or a Sourced DTO ({value}) straight off an EnrichmentResult. */
export function productPhotoUrl(
  specs: Record<string, unknown> | null | undefined,
): string {
  const raw = (specs ?? {})["Image"];
  const v =
    raw != null && typeof raw === "object" ? (raw as { value?: unknown }).value : raw;
  return typeof v === "string" && /^https?:\/\//i.test(v.trim()) ? v.trim() : "";
}

export function ProductPhoto({
  url,
  alt,
  className,
  fallback,
}: {
  url: string;
  alt: string;
  className?: string;
  fallback?: ReactNode;
}) {
  const [direct, setDirect] = useState(true); // lane 1: the plain <img src>
  const [dead, setDead] = useState(false); // both lanes failed: the fallback
  // a different part's photo resets the lanes (state must never leak across urls)
  useEffect(() => {
    setDirect(true);
    setDead(false);
  }, [url]);
  const proxy = useProductImage(url, !direct && !dead);
  const proxied = useObjectUrl(proxy.data ?? null);

  if (!url || dead || (!direct && proxy.isError)) return <>{fallback ?? null}</>;
  if (!direct && proxy.isLoading) {
    return <div className="h-full w-full animate-pulse bg-raise2" aria-hidden="true" />;
  }
  const src = direct ? url : proxied;
  if (!src) return <>{fallback ?? null}</>;
  return (
    <img
      src={src}
      alt={alt}
      draggable={false}
      loading="lazy"
      className={className ?? "h-full w-full object-contain"}
      onError={() => (direct ? setDirect(false) : setDead(true))}
    />
  );
}
