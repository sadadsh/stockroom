/**
 * The grouped parts list (the mockup's .pk-list). Rows show the display name over
 * the part number, with an incomplete warning triangle on the right. Parts are
 * grouped by category with sticky group headers, matching library-v2.html.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import type { PartSummary } from "../api/types";
import { usePreviewGlb } from "../api/queries";
import { WarnIcon } from "./icons";
import { Badge } from "./primitives";

// Rendered GLB thumbnails, cached by part id for this session so scrolling never re-renders a
// model (each render is a real GPU pass through the shared offscreen renderer).
const thumbCache = new Map<string, string>();

// The part's 3D model, rendered flat + frozen, as the row icon. Fetches the GLB only once the
// row is in view (lazy), renders it to a PNG through the shared offscreen renderer, and caches
// the result. Returns null while loading / when the part has no renderable model, so the row
// keeps its category glyph as an honest fallback. A passive resolves its built-in library
// model through the SAME endpoint the detail hero uses.
function useModelThumbnail(id: string, inView: boolean): string | null {
  const cached = thumbCache.get(id) ?? null;
  const [url, setUrl] = useState<string | null>(cached);
  const glb = usePreviewGlb(id, inView && !cached);

  useEffect(() => {
    if (cached) {
      setUrl(cached);
      return;
    }
    if (!glb.data) return;
    let cancelled = false;
    void (async () => {
      try {
        const { renderGlbThumbnail } = await import("../lib/modelThumbnail");
        const dataUrl = await renderGlbThumbnail(glb.data as ArrayBuffer);
        if (cancelled) return;
        if (dataUrl) thumbCache.set(id, dataUrl);
        setUrl(dataUrl);
      } catch {
        /* no WebGL / render failed: keep the glyph fallback */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id, glb.data, cached]);

  return url;
}

// The row icon shell: a 30px tile that observes its own visibility (so a long list only
// renders the models the user can actually see), showing the frozen 3D render when ready and
// the category glyph until then / when the part has none.
export function RowThumbnail({ id, category }: { id: string; category: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [inView, setInView] = useState(() => typeof IntersectionObserver === "undefined");

  useEffect(() => {
    if (inView || typeof IntersectionObserver === "undefined") return;
    const el = ref.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setInView(true);
          obs.disconnect();
        }
      },
      { rootMargin: "300px" },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [inView]);

  const thumb = useModelThumbnail(id, inView);
  return (
    <span
      ref={ref}
      className="flex h-[30px] w-[30px] flex-none items-center justify-center overflow-hidden rounded-[7px] border border-line bg-field"
    >
      {thumb ? (
        <img src={thumb} alt="" className="h-full w-full object-contain" />
      ) : (
        <CategoryGlyph category={category} />
      )}
    </span>
  );
}

// A small monochrome category glyph for the row thumbnail (north-star .rthumb): the part seen
// as its kind at a glance. Neutral stroke art, so it inherits the row's text color and never
// carries a hue. Falls back to a generic chip for a category with no dedicated glyph.
function CategoryGlyph({ category }: { category: string }) {
  const c = category.toLowerCase();
  const p = { fill: "none", stroke: "currentColor", strokeWidth: 1.6, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  if (c.includes("resistor"))
    return (
      <svg viewBox="0 0 32 18" className="h-3.5 w-6 text-t2" {...p}>
        <path d="M2 9h5l1.5-4 3 8 3-8 3 8 1.5-4H32" />
      </svg>
    );
  if (c.includes("capacitor"))
    return (
      <svg viewBox="0 0 32 18" className="h-3.5 w-6 text-t2" {...p}>
        <path d="M2 9h11M19 9h11M13 3v12M19 3v12" />
      </svg>
    );
  if (c.includes("inductor") || c.includes("ferrite"))
    return (
      <svg viewBox="0 0 32 18" className="h-3.5 w-6 text-t2" {...p}>
        <path d="M2 9h4a3 3 0 0 1 6 0 3 3 0 0 1 6 0 3 3 0 0 1 6 0h4" />
      </svg>
    );
  if (c.includes("diode") || c.includes("led"))
    return (
      <svg viewBox="0 0 32 18" className="h-3.5 w-6 text-t2" {...p}>
        <path d="M2 9h10M20 9h10M12 4v10l8-5-8-5zM20 4v10" />
      </svg>
    );
  if (c.includes("connector") || c.includes("header"))
    return (
      <svg viewBox="0 0 32 18" className="h-3.5 w-6 text-t2" {...p}>
        <rect x="4" y="4" width="24" height="10" rx="2" />
        <path d="M10 14v2M16 14v2M22 14v2" />
      </svg>
    );
  if (c.includes("crystal") || c.includes("oscillator"))
    return (
      <svg viewBox="0 0 32 18" className="h-3.5 w-6 text-t2" {...p}>
        <rect x="9" y="4" width="14" height="10" rx="4" />
        <path d="M2 9h7M23 9h7" />
      </svg>
    );
  // ICs, modules, sensors, and anything else: a chip with pins
  return (
    <svg viewBox="0 0 32 18" className="h-3.5 w-6 text-t2" {...p}>
      <rect x="9" y="3" width="14" height="12" rx="1.5" />
      <path d="M6 6h3M6 9h3M6 12h3M23 6h3M23 9h3M23 12h3" />
    </svg>
  );
}

interface Props {
  parts: PartSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  // Part ids that share an MPN with another part (a real accidental duplicate);
  // each gets a Duplicate badge. Shared footprints are normal and never badged.
  duplicateIds?: Set<string>;
}

function groupByCategory(parts: PartSummary[]): Array<[string, PartSummary[]]> {
  const groups = new Map<string, PartSummary[]>();
  for (const p of parts) {
    const key = p.category || "Uncategorized";
    const bucket = groups.get(key);
    if (bucket) bucket.push(p);
    else groups.set(key, [p]);
  }
  return [...groups.entries()].sort((a, b) => a[0].localeCompare(b[0]));
}

export function PartsList({ parts, selectedId, onSelect, duplicateIds }: Props) {
  const grouped = useMemo(() => groupByCategory(parts), [parts]);

  if (parts.length === 0) {
    return (
      <div className="px-3 py-8 text-center text-sm text-t3">No Matches</div>
    );
  }

  return (
    <div className="flex flex-col gap-0.5">
      {grouped.map(([category, items]) => (
        <div key={category} className="flex flex-col gap-0.5">
          <div className="sticky top-0 z-[1] mb-0.5 flex items-baseline gap-2 bg-[var(--c-sticky)] px-2.5 pb-1.5 pt-3.5 backdrop-blur">
            <span className="text-2xs font-semibold text-t3">{category}</span>
            <span className="tnum font-mono text-2xs text-t3">{items.length}</span>
          </div>
          {items.map((p) => {
            const selected = p.id === selectedId;
            return (
              <button
                key={p.id}
                type="button"
                onClick={() => onSelect(p.id)}
                aria-current={selected ? "true" : undefined}
                className={
                  // Rows separate by whitespace + a rounded selection/hover pill, not a
                  // hairline on every row (the border-on-everything tell). The selected
                  // row is the one lift; the MPN reads in the mono index face.
                  "flex w-full items-center gap-2.5 rounded-control px-2.5 py-2 text-left transition-colors " +
                  (selected ? "bg-raise2" : "hover:bg-[var(--c-hover)]")
                }
              >
                <RowThumbnail id={p.id} category={p.category} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span
                      className={
                        "truncate text-sm " +
                        (selected ? "font-semibold text-t1" : "font-medium text-t1")
                      }
                    >
                      {p.display_name}
                    </span>
                    {duplicateIds?.has(p.id) ? (
                      <span className="flex-none" title="Another part shares this MPN">
                        <Badge tone="warn" size="sm">
                          Duplicate
                        </Badge>
                      </span>
                    ) : null}
                  </div>
                  {p.mpn ? (
                    <div className="tnum mt-0.5 truncate font-mono text-2xs text-t3">
                      {p.mpn}
                    </div>
                  ) : null}
                </div>
                {!p.is_complete ? (
                  <span
                    className="mt-0.5 flex flex-none items-center text-warn"
                    title={`Incomplete: missing ${p.missing.join(", ")}`}
                  >
                    <WarnIcon className="h-3.5 w-3.5" />
                  </span>
                ) : null}
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );
}
