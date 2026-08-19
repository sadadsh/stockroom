/**
 * The pulled product photograph (specs["Image"], a vendor CDN URL). HIDDEN by default
 * (owner 2026-07-24): surfaces render a small PhotoTrigger ("Photo" chip), and clicking
 * it opens the PhotoCard - a scrim dialog with the image large. The image itself loads
 * with a two-lane fallback: the direct <img> first (zero backend load), then the backend
 * image proxy (/api/enrich/image, disk-cached) via an authenticated blob when the CDN
 * refuses the hotlink (Mouser sits behind Akamai). When both lanes fail the `fallback`
 * renders instead - never a broken-image glyph.
 */
import { useState, type ReactNode, type Ref } from "react";
import { useProductImage } from "../api/queries";
import { useModalDismiss } from "../lib/useModalDismiss";
import { useObjectUrl } from "../lib/useObjectUrl";
import { Text, useCopyFormatter, useText } from "../lib/copy";
import { Icon } from "./Icon";
import type { PartPhoto } from "./partPhotos";

interface ProductPhotoProps {
  url: string;
  alt: string;
  className?: string;
  fallback?: ReactNode;
}

/**
 * A different part's photo must never inherit the previous url's lanes, so the url IS the identity
 * of the lane state: React unmounts the old lanes and mounts fresh ones.
 *
 * Clearing them from an effect instead (`useEffect(() => { setDirect(true); setDead(false) }, [url])`)
 * left one committed render in between that still carried the OLD url's verdict: a part whose direct
 * hotlink had already failed switched to a new url and, for that frame, asked the backend proxy for
 * it - a request the direct lane exists to avoid - or, once both lanes had failed, drew the fallback
 * over a photo that was in fact fine.
 */
export function ProductPhoto(props: ProductPhotoProps) {
  return <PhotoLanes key={props.url} {...props} />;
}

function PhotoLanes({ url, alt, className, fallback }: ProductPhotoProps) {
  const [direct, setDirect] = useState(true); // lane 1: the plain <img src>
  const [dead, setDead] = useState(false); // both lanes failed: the fallback
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
  // The accessible names, resolved above the early return below. A photo button is a glyph plus two
  // words, so the name is where the complete action lives, and the part it names is data.
  const thisPart = useText("photo.this-part", "this part");
  const viewManyName = useCopyFormatter("photo.view-many-aria", "View {count} Photos of {part}");
  const viewOneName = useCopyFormatter("photo.view-one-aria", "View Photo of {part}");
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
              ? viewManyName({ count, part: partName || thisPart })
              : viewOneName({ part: partName || thisPart })
          }
          className="group flex h-8 w-full items-center gap-2 rounded-control border border-line bg-field px-3 text-xs font-medium text-t1 transition-colors hover:border-line2 hover:bg-raise2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
        >
          {/* Anatomy DELIBERATELY matched to the CAD row directly beneath it: glyph and label on the
              left, affordance on the right. Measured on the first cut, which centred its content and
              set the label in `text-t2`: it was the only centred control between two label-left /
              value-right neighbours, and in light theme its label measured rgb(90,90,90) against the
              rgb(18,18,36) of the STATUS word beside it - so the one ACTION in the stack was the
              quietest text in it. */}
          <Icon id="media.photo" className="h-3.5 w-3.5 flex-none text-t3 transition-colors group-hover:text-t1" />
          {count > 1 ? (
            <Text id="photo.view-many" values={{ count }}>{"View {count} Photos"}</Text>
          ) : (
            <Text id="photo.view-one">View Photo</Text>
          )}
          <Icon id="detail.chevron-right" className="ml-auto h-3.5 w-3.5 flex-none text-t3 transition-colors group-hover:text-t1" />
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
        aria-label={viewOneName({ part: partName || thisPart })}
        className="inline-flex flex-none items-center gap-1.5 rounded-control border border-line bg-raise px-2 py-1 text-2xs font-medium text-t2 transition-colors hover:border-line2 hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
      >
        <Icon id="media.photo" className="h-3 w-3 flex-none" />
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
  const { ref: dialogRef, zIndex: modalZ } = useModalDismiss(open, onClose);
  const shots: PartPhoto[] =
    photos && photos.length ? photos : url ? [{ url, vendor: "" }] : [];
  // A different part (or a refreshed set) must never open on a stale index: paging to photo 3 and
  // reopening on a part with one photo would otherwise render an empty stage. The SET is the page
  // index's identity, and closing removes the stage outright, so neither case can survive - where
  // an effect that reset the index ran only AFTER a render had already drawn the wrong slide.
  const setKey = shots.map((s) => s.url).join("|");

  if (!open || shots.length === 0) return null;
  return (
    <PhotoStage
      key={setKey}
      shots={shots}
      partName={partName}
      onClose={onClose}
      dialogRef={dialogRef}
      modalZ={modalZ}
    />
  );
}

/** The open viewer. Mounted only while it is open and remounted per photo SET, so the page index
 * is born at zero rather than corrected after the fact. */
function PhotoStage({
  shots,
  partName,
  onClose,
  dialogRef,
  modalZ,
}: {
  shots: PartPhoto[];
  partName: string;
  onClose: () => void;
  dialogRef: Ref<HTMLDivElement>;
  modalZ: number;
}) {
  const closeLabel = useText("photo.close", "Close");
  const thisPart = useText("photo.this-part", "this part");
  const dialogName = useCopyFormatter("photo.dialog-aria", "Photo of {part}");
  const [at, setAt] = useState(0);

  const count = shots.length;
  const index = Math.min(at, count - 1);
  const step = (delta: number) => setAt((i) => (i + delta + count) % count);

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
      style={{ zIndex: modalZ }}
      className="fixed inset-0 flex items-center justify-center bg-canvas p-4"
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
        aria-label={dialogName({ part: partName || thisPart })}
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
            aria-label={closeLabel}
            className="flex h-7 w-7 flex-none items-center justify-center rounded-control text-t3 transition-colors hover:bg-raise2 hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus"
          >
            <Icon id="action.close" className="h-3.5 w-3.5" />
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
  const previousName = useText("photo.previous", "Previous Photo");
  const nextName = useText("photo.next", "Next Photo");
  return (
    <button
      type="button"
      data-dev-id={devId}
      onClick={onClick}
      aria-label={side === "left" ? previousName : nextName}
      className={
        "absolute top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-control " +
        "border border-line bg-popover text-t2 shadow-pop transition-colors hover:text-t1 " +
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus " +
        (side === "left" ? "left-2" : "right-2")
      }
    >
      <Icon
        id="detail.chevron-right"
        className={`h-3.5 w-3.5 ${side === "left" ? "rotate-180" : ""}`}
      />
    </button>
  );
}
