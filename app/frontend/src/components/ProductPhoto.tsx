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
import { orderPhotos } from "../lib/sourcingOrder";
import { useObjectUrl } from "../lib/useObjectUrl";
import { Text } from "../lib/copy";
import type { SourcedAlternate } from "../api/types";

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

/** One photograph on offer, and which distributor served it. */
export interface PartPhoto {
  url: string;
  /** The distributor that supplied it, already humanised. Empty when nothing named it. */
  vendor: string;
}

// Internal source keys carry a lane suffix a person should never read ("mouser_web" is the
// scraper lane, not a company). The vendor labels are deliberately NOT a hardcoded map of every
// distributor: any unknown source is title-cased, so a new adapter shows a sensible name instead
// of nothing on the day it lands.
function vendorLabel(source: string): string {
  const base = (source || "").split("_")[0].trim();
  if (!base) return "";
  if (base.toLowerCase() === "digikey") return "DigiKey";
  if (base.toLowerCase() === "lcsc") return "LCSC";
  return base.charAt(0).toUpperCase() + base.slice(1);
}

/**
 * EVERY photograph on record for this part, in-force first, then each distributor that offered a
 * different one.
 *
 * These are real, already-stored answers, not a second fetch: both distributor adapters write
 * `specs["Image"]` with `setdefault`, so the first source wins the slot and the rest are preserved
 * as spec conflicts (`record.alternates["Image"]`) by the Batch 3 machinery. Before this, that
 * second and third photo were carried all the way into the record and then shown to nobody.
 *
 * Deduplicated by URL, because two sources naming the SAME image is the common case and a carousel
 * that pages through three identical photographs reads as broken.
 */
export function partPhotos(
  specs: Record<string, unknown> | null | undefined,
  // The record's REAL alternates type, not a structural stand-in: a hand-written shape here would
  // silently stop matching the day the DTO grows a field, and it already rejected a valid caller.
  alternates?: Record<string, SourcedAlternate[]> | null,
): PartPhoto[] {
  const out: PartPhoto[] = [];
  const seen = new Set<string>();
  const push = (url: string, source: string) => {
    const clean = url.trim();
    if (!clean || seen.has(clean)) return;
    seen.add(clean);
    out.push({ url: clean, vendor: vendorLabel(source) });
  };

  const hero = productPhotoUrl(specs);
  // The in-force photo's own origin, when the spec bag kept it as a Sourced DTO.
  const raw = (specs ?? {})["Image"];
  const heroSource =
    raw != null && typeof raw === "object" ? String((raw as { source?: unknown }).source ?? "") : "";
  if (hero) push(hero, heroSource);

  for (const alt of (alternates ?? {})["Image"] ?? []) {
    const v = alt?.value;
    if (typeof v === "string" && /^https?:\/\//i.test(v.trim())) push(v, alt.source ?? "");
  }
  // Quality order, not arrival order. Which adapter won the `specs["Image"]` slot is a race decided
  // by `setdefault`, so the in-force photo was simply whoever answered first - and the owner's
  // complaint (2026-07-26) is exactly that: the DigiKey photograph is much better than the Mouser
  // one, and Mouser was winning the hero slot. Sorted here rather than at the call site so the
  // carousel, the thumbnail and any future consumer all agree on which image leads.
  return orderPhotos(out);
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
  photos,
  partName,
  devId,
  // The visible text. Defaults to the noun, because in the Add flows this chip stands alone and has
  // to say WHAT it opens. Where a label already supplies the noun (the detail panel's PRODUCT PHOTO
  // row), the caller passes the verb instead, so the label labels and the button acts - rather than
  // the two of them saying "photo" twice.
  label = "Photo",
  // "chip" is the original inline affordance, still right where the control sits inside a dense row
  // of other controls (the Add flows). "panel" is a real, substantial control: the owner's note was
  // that the photo of the actual part was reachable only through a 24px chip that read as a
  // footnote, on a sheet whose whole subject is that part.
  variant = "chip",
}: {
  url?: string;
  photos?: PartPhoto[];
  partName: string;
  devId?: string;
  label?: string;
  variant?: "chip" | "panel";
}) {
  const [open, setOpen] = useState(false);
  const shots: PartPhoto[] = photos && photos.length ? photos : url ? [{ url, vendor: "" }] : [];
  if (!shots.length) return null;
  const count = shots.length;
  const card = (
    <PhotoCard open={open} photos={shots} partName={partName} onClose={() => setOpen(false)} />
  );

  if (variant === "panel") {
    // OWNER, 2026-07-26, two asks about this one control: "product photos: do not show the source"
    // and "just a View Photos BUTTON, with an icon". So the card that used to sit here - a 48px
    // thumbnail, the count, the vendor line and a chevron - is now a button carrying a camera and
    // the verb. The vendor is gone entirely: it named WHOSE photograph it was, which is a fact
    // about sourcing rather than about the part, and the viewer itself still shows it per photo.
    // The thumbnail goes with it because the ask was "just a button"; the icon is what says what
    // opens. Full width, because it is the whole row's control rather than a chip inside one.
    return (
      <>
        <button
          type="button"
          data-dev-id={devId}
          onClick={() => setOpen(true)}
          aria-label={
            count > 1
              ? `View ${count} Photos of ${partName || "this part"}`
              : `View Photo of ${partName || "this part"}`
          }
          className="group flex h-8 w-full items-center gap-2 rounded-control border border-line bg-field px-3 text-xs font-medium text-t1 transition-colors hover:border-line2 hover:bg-raise2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc"
        >
          {/* Anatomy DELIBERATELY matched to the CAD row directly beneath it: glyph and label on the
              left, affordance on the right. Measured on the first cut, which centred its content and
              set the label in `text-t2`: it was the only centred control between two label-left /
              value-right neighbours, and in light theme its label measured rgb(90,90,90) against the
              rgb(18,18,36) of the STATUS word beside it - so the one ACTION in the stack was the
              quietest text in it. */}
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true" className="flex-none text-t3 transition-colors group-hover:text-t1">
            <rect x="3" y="5" width="18" height="14" rx="2" />
            <circle cx="9" cy="11" r="2" />
            <path d="m21 15-3.5-3.5L13 16l-2-2-5 5" />
          </svg>
          {count > 1 ? `View ${count} Photos` : "View Photo"}
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true" className="ml-auto flex-none text-t3 transition-colors group-hover:text-t1">
            <path d="M9 18l6-6-6-6" />
          </svg>
        </button>
        {card}
      </>
    );
  }

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
        {label}
      </button>
      {card}
    </>
  );
}

/** The viewer: the PreviewModal scrim idiom (Esc / scrim-click / X to close, focus
 * trapped + restored) with the photograph large on the stage.
 *
 * Takes EVERY photo on record and pages through them (owner, 2026-07-25). A part carried by two
 * distributors usually has two genuinely different photographs - one may show the marking, the
 * other the pin 1 chamfer - and only the first was ever reachable. With a single photo it renders
 * exactly as it used to: no counter, no arrows, nothing to dismiss. */
export function PhotoCard({
  open,
  url,
  photos,
  partName,
  onClose,
}: {
  open: boolean;
  /** The single-photo form, kept so existing callers (the Add flows) are unchanged. */
  url?: string;
  /** The full set. Wins over `url` when both are given. */
  photos?: PartPhoto[];
  partName: string;
  onClose: () => void;
}) {
  const dialogRef = useModalDismiss(open, onClose);
  const shots: PartPhoto[] =
    photos && photos.length ? photos : url ? [{ url, vendor: "" }] : [];
  const [at, setAt] = useState(0);
  // A different part (or a refreshed set) must never open on a stale index: paging to photo 3 and
  // reopening on a part with one photo would otherwise render an empty stage.
  const key = shots.map((s) => s.url).join("|");
  useEffect(() => {
    setAt(0);
  }, [key, open]);

  const count = shots.length;
  const index = count ? Math.min(at, count - 1) : 0;
  const step = (delta: number) => setAt((i) => (count ? (i + delta + count) % count : 0));

  if (!open || !count) return null;
  const shot = shots[index];
  return (
    <div
      // OPAQUE, not bg-black/50 (owner, 2026-07-26: "when the photo viewer is OPEN, remove their
      // transparent thing"). Confirmed against a real shot of the opened viewer before changing it,
      // as their note asked: at /50 the page read straight through - spec rows, their star
      // controls and the whole sourcing column were legible around the dialog, and every sampled
      // point measured at roughly half its normal luminance (rail 87 -> 43, list 63 -> 31).
      // A photograph of the part is a thing you LOOK at; competing with a readable page behind it
      // is what made it feel like a floating panel rather than a viewer.
      className="fixed inset-0 z-[110] flex items-center justify-center bg-canvas p-4"
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
        // Left/Right page the carousel. Escape is already handled by useModalDismiss, and the
        // arrows are bound on the DIALOG rather than the window so they cannot fight a text
        // caret elsewhere in the app.
        onKeyDown={(e) => {
          if (count < 2) return;
          if (e.key === "ArrowRight") {
            e.preventDefault();
            step(1);
          } else if (e.key === "ArrowLeft") {
            e.preventDefault();
            step(-1);
          }
        }}
        className="flex max-h-[80vh] w-full max-w-[560px] flex-col overflow-hidden rounded-card border border-line2 bg-popover shadow-pop outline-none"
      >
        <div className="flex h-[38px] flex-none items-center gap-3 border-b border-line bg-band px-4">
          <span className="min-w-0 flex-1 truncate text-sm font-semibold text-t1">
            {partName || <Text id="photo.title">Product Photo</Text>}
          </span>
          {/* The counter states the SET, so a person knows more exists before touching anything.
              Absent at one photo, where "1 of 1" is noise. */}
          {count > 1 ? (
            <span
              data-dev-id="preview.photo-count"
              className="flex-none tabular-nums text-2xs font-medium text-t3"
            >
              {index + 1} / {count}
            </span>
          ) : null}
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
        <div className="relative flex min-h-[280px] items-center justify-center bg-stage p-6">
          {/* vendor product shots are white-matte JPEGs: mount them on a deliberate white
              chamber so the photo reads as a mounted photograph in BOTH themes, never a
              glaring white hole punched into the dark stage */}
          <div className="flex max-h-[60vh] w-full items-center justify-center rounded-control bg-white p-4">
            <ProductPhoto
              key={shot.url}
              url={shot.url}
              alt={`Photo ${index + 1} of ${count} of ${partName || "this part"}`}
              className="max-h-[55vh] w-full object-contain"
              fallback={
                <span className="py-10 text-sm text-neutral-500">
                  <Text id="photo.unavailable">The vendor did not serve this photo.</Text>
                </span>
              }
            />
          </div>
          {count > 1 ? (
            <>
              <CarouselArrow
                side="left"
                devId="preview.photo-prev"
                onClick={() => step(-1)}
              />
              <CarouselArrow
                side="right"
                devId="preview.photo-next"
                onClick={() => step(1)}
              />
            </>
          ) : null}
        </div>
        {/* NO attribution row. The comment here used to argue that "which distributor photographed
            it is information, not a footnote" - a fair argument, and the owner decided otherwise:
            "product photos: do NOT show the source". That instruction was about the photos, not
            about one control, so it applies here too. The provenance is still on the record; it is
            simply not what this surface is for. */}
      </div>
    </div>
  );
}

/** A carousel pager. Sits over the stage edge rather than below it, so paging never moves the
 * photograph's own position - the whole point is comparing two shots of the same part. */
function CarouselArrow({
  side,
  devId,
  onClick,
}: {
  side: "left" | "right";
  // Written out in FULL by the caller, never built as `preview.photo-${side}`: the dev-id parity
  // gate scans source TEXT, so an interpolated id is invisible to it and to anyone grepping.
  devId: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      data-dev-id={devId}
      onClick={onClick}
      aria-label={side === "left" ? "Previous Photo" : "Next Photo"}
      className={
        "absolute top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-control " +
        "border border-line bg-popover/90 text-t2 shadow-pop transition-colors hover:text-t1 " +
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc " +
        (side === "left" ? "left-2" : "right-2")
      }
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
        <path d={side === "left" ? "M15 18l-6-6 6-6" : "M9 18l6-6-6-6"} />
      </svg>
    </button>
  );
}
