/**
 * PinoutLegend (VIZ-02): teaches the four encoding channels the pinout map paints, so the map is
 * readable without guessing. One quiet row per axis, each named with an Eyebrow (CONTEXT decision 5).
 * Color appears only where color is the data (the category fill row); the role, 5V, and selection
 * channels are neutral, matching the map. Every swatch is the shared LegendSwatch primitive.
 */
import { Eyebrow, LegendSwatch } from "../primitives";
import { PIN_CATEGORIES } from "./pinEncoding";

export function PinoutLegend() {
  return (
    <div className="flex flex-col gap-3" data-testid="pinout-legend">
      {/* Fill = category (the one saturated channel) */}
      <section>
        <Eyebrow className="mb-1.5">Category</Eyebrow>
        <div className="grid grid-cols-2 gap-x-3 gap-y-1">
          {PIN_CATEGORIES.map((cat) => (
            <div key={cat.key} className="flex items-center gap-1.5">
              <LegendSwatch token={cat.stroke} />
              <span className="truncate text-xs text-t2">{cat.label}</span>
            </div>
          ))}
        </div>
      </section>

      {/* Border = role weight (neutral) */}
      <section>
        <Eyebrow className="mb-1.5">Role</Eyebrow>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <RoleKey width={1} color="var(--c-line2)" label="Standard" />
          <RoleKey width={1.25} color="var(--c-t2)" label="Function" />
          <RoleKey width={1.75} color="var(--c-t1)" label="Special" />
        </div>
        <p className="mt-1 text-2xs text-t3">Border weight marks a pin&rsquo;s role.</p>
      </section>

      {/* Mark = 5V tolerant (neutral dot) */}
      <section>
        <Eyebrow className="mb-1.5">5V Tolerance</Eyebrow>
        <div className="flex items-center gap-1.5">
          <LegendSwatch token="var(--stm-gpio)" variant="dot" />
          <span className="text-xs text-t2">5V Tolerant</span>
        </div>
      </section>

      {/* Ring = selection (neutral accent) */}
      <section>
        <Eyebrow className="mb-1.5">Selection</Eyebrow>
        <div className="flex items-center gap-1.5">
          <LegendSwatch token="var(--stm-gpio)" variant="ring" />
          <span className="text-xs text-t2">Selected</span>
        </div>
      </section>
    </div>
  );
}

function RoleKey({ width, color, label }: { width: number; color: string; label: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <span
        className="h-3 w-3 flex-none rounded-control bg-raise2"
        style={{ border: `${width}px solid ${color}` }}
      />
      <span className="text-xs text-t2">{label}</span>
    </div>
  );
}
