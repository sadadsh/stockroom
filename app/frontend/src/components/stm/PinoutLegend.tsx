/**
 * PinoutLegend (VIZ-02): teaches the four encoding channels the pinout map paints, so the map is
 * readable without guessing. Color appears only where color is the data (the category fill row);
 * the role, 5V, and selection channels are neutral, matching the map (CONTEXT decision 5).
 */
import { PIN_CATEGORIES } from "./pinEncoding";

function Swatch({ token }: { token: string }) {
  return (
    <span
      className="h-3 w-3 flex-none rounded-[3px]"
      style={{ backgroundColor: `var(${token})` }}
    />
  );
}

export function PinoutLegend() {
  return (
    <div className="flex flex-col gap-2.5" data-testid="pinout-legend">
      {/* Fill = category (the one saturated channel) */}
      <section>
        <div className="mb-1.5 text-2xs font-semibold text-t3">Category</div>
        <div className="grid grid-cols-2 gap-x-3 gap-y-1">
          {PIN_CATEGORIES.map((cat) => (
            <div key={cat.key} className="flex items-center gap-1.5">
              <Swatch token={cat.token} />
              <span className="truncate text-xs text-t2">{cat.label}</span>
            </div>
          ))}
        </div>
      </section>

      {/* Border = role weight (neutral) */}
      <section>
        <div className="mb-1.5 text-2xs font-semibold text-t3">Role</div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <RoleKey width={1} color="var(--c-line2)" label="Standard" />
          <RoleKey width={1.25} color="var(--c-t2)" label="Function" />
          <RoleKey width={1.75} color="var(--c-t1)" label="Special" />
        </div>
        <p className="mt-1 text-2xs text-t3">Border weight marks a pin&rsquo;s role.</p>
      </section>

      {/* Mark = 5V tolerant, Ring = selection (both neutral) */}
      <section className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="relative h-3 w-3 flex-none rounded-control bg-stm-gpio">
            <span className="absolute left-1/2 top-1/2 h-1 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-t1" />
          </span>
          <span className="text-xs text-t2">5V Tolerant</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="h-3 w-3 flex-none rounded-control bg-stm-gpio outline outline-2 outline-offset-1 outline-acc-strong" />
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
        className="h-3 w-3 flex-none rounded-[3px] bg-raise2"
        style={{ border: `${width}px solid ${color}` }}
      />
      <span className="text-xs text-t2">{label}</span>
    </div>
  );
}
