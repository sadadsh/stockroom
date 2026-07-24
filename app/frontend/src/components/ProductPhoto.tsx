/**
 * The pulled product photograph (specs["Image"], a vendor CDN URL). HIDDEN by default
 * (owner 2026-07-24): surfaces render a small PhotoTrigger ("Photo" chip), and clicking
 * it opens the PhotoCard - a scrim dialog with the image large. The image itself loads
 * with a two-lane fallback: the direct <img> first (zero backend load), then the backend
 * image proxy (/api/enrich/image, disk-cached) via an authenticated blob when the CDN
 * refuses the hotlink (Mouser sits behind Akamai). When both lanes fail the `fallback`
 * renders instead - never a broken-image glyph.
 */
import { useEffect, useState, type ReactNode } from "react";
import { useProductImage } from "../api/queries";
import { useModalDismiss } from "../lib/useModalDismiss";
import { useObjectUrl } from "../lib/useObjectUrl";
import { Text } from "../lib/copy";

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

/** The click-to-view affordance: a quiet "Photo" chip that opens the PhotoCard. Renders
 * nothing at all without a url, so surfaces can pass the raw productPhotoUrl result. */
export function PhotoTrigger({
  url,
  partName,
  devId,
}: {
  url: string;
  partName: string;
  devId?: string;
}) {
  const [open, setOpen] = useState(false);
  if (!url) return null;
  return (
    <>
      <button
        type="button"
        data-dev-id={devId}
        onClick={() => setOpen(true)}
        aria-label={`View Photo of ${partName || "this part"}`}
        className="inline-flex flex-none items-center gap-1.5 rounded-control border border-line bg-raise px-2 py-1 text-2xs font-medium text-t2 transition-colors hover:border-line2 hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc"
      >
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <rect x="3" y="5" width="18" height="14" rx="2" />
          <circle cx="9" cy="11" r="2" />
          <path d="m21 15-3.5-3.5L13 16l-2-2-5 5" />
        </svg>
        <Text id="photo.trigger">Photo</Text>
      </button>
      <PhotoCard open={open} url={url} partName={partName} onClose={() => setOpen(false)} />
    </>
  );
}

/** The viewer: the PreviewModal scrim idiom (Esc / scrim-click / X to close, focus
 * trapped + restored) with the photograph large on the stage. */
export function PhotoCard({
  open,
  url,
  partName,
  onClose,
}: {
  open: boolean;
  url: string;
  partName: string;
  onClose: () => void;
}) {
  const dialogRef = useModalDismiss(open, onClose);
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-[110] flex items-center justify-center bg-black/50 p-4"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        data-dev-id="preview.photo"
        role="dialog"
        aria-modal="true"
        aria-label={`Photo of ${partName || "this part"}`}
        tabIndex={-1}
        className="flex max-h-[80vh] w-full max-w-[560px] flex-col overflow-hidden rounded-card border border-line2 bg-popover shadow-pop outline-none"
      >
        <div className="flex h-[38px] flex-none items-center gap-3 border-b border-line bg-band px-4">
          <span className="min-w-0 flex-1 truncate text-sm font-semibold text-t1">
            {partName || <Text id="photo.title">Product Photo</Text>}
          </span>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="flex h-7 w-7 flex-none items-center justify-center rounded-control text-t3 transition-colors hover:bg-raise2 hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-acc"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div className="flex min-h-[280px] items-center justify-center bg-stage p-6">
          <ProductPhoto
            key={url}
            url={url}
            alt={`Photo of ${partName || "this part"}`}
            className="max-h-[60vh] w-full object-contain"
            fallback={
              <span className="text-sm text-t3">
                <Text id="photo.unavailable">The vendor did not serve this photo.</Text>
              </span>
            }
          />
        </div>
      </div>
    </div>
  );
}
