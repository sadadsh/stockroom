/**
 * PinoutLegend (VIZ-02): the modular key to everything the map encodes, rebuilt around the loaded
 * part (owner ask 2026-07-23) instead of a static swatch chart:
 *
 * - Category: the ten color-is-data buckets WITH live pin counts for the loaded part; each row is
 *   a real toggle that highlights its pins on the map (dimming the rest) - the legend is a lens,
 *   not just a caption. Empty buckets stay listed but quiet (an honest zero).
 * - Role / 5V / Selection: the three neutral channels, with live counts where they apply.
 * - Bring-Up Pins: boot straps, reset, debug access, oscillator pins, and the power domains
 *   present, each with its count computed from the same pinout the map draws (no fetch).
 *
 * Without a pinout (nothing selected) it falls back to the plain static key.
 */
import { useMemo } from "react";
import type { PinDTO, PinoutDTO } from "../../api/types";
import { Eyebrow, LegendSwatch } from "../primitives";
import { Text, useCopyFormatter, useText } from "../../lib/copy";
import { PIN_CATEGORIES, isFiveVoltTolerant, roleStroke } from "./pinEncoding";

export interface LegendProps {
  pinout?: PinoutDTO | null;
  /** category keys currently highlighted on the map; empty set = no highlight lens active */
  highlight?: ReadonlySet<string>;
  onToggleHighlight?: (categoryKey: string) => void;
}

// The category a pin counts under: the API's category bucket, with the legacy raw io class
// reading as gpio (mirrors pinEncoding's alias).
function bucketOf(pin: PinDTO): string {
  return pin.category === "io" ? "gpio" : pin.category;
}

const DEBUG_ROLE = /swd|jtag|swo|trace/i;
const OSC_ROLE = /^oscillator/i;

export function PinoutLegend({ pinout, highlight, onToggleHighlight }: LegendProps) {
  const pins = pinout?.pins;

  const standardLabel = useText("stm.pinout.legend.role-standard", "Standard");
  const functionLabel = useText("stm.pinout.legend.role-function", "Function");
  const specialLabel = useText("stm.pinout.legend.role-special", "Special");
  const bootLabel = useText("stm.pinout.legend.boot-straps", "Boot straps");
  const resetLabel = useText("stm.pinout.legend.reset", "Reset");
  const debugLabel = useText("stm.pinout.legend.debug-access", "Debug access");
  const oscillatorLabel = useText("stm.pinout.legend.oscillator", "Oscillator");
  const supplyLabel = useCopyFormatter("stm.pinout.legend.supply", "{domain} supply");

  const counts = useMemo(() => {
    const by: Record<string, number> = {};
    for (const p of pins ?? []) by[bucketOf(p)] = (by[bucketOf(p)] ?? 0) + 1;
    return by;
  }, [pins]);

  const facts = useMemo(() => {
    if (!pins) return null;
    const roleNames = (p: PinDTO) => (p.roles ?? []).map((r) => `${r.role_name} ${r.role_class}`);
    const boot = pins.filter((p) => p.category === "boot").length;
    const reset = pins.filter((p) => p.category === "reset").length;
    const debug = pins.filter((p) => roleNames(p).some((n) => DEBUG_ROLE.test(n))).length;
    const osc = pins.filter((p) =>
      (p.roles ?? []).some((r) => OSC_ROLE.test(r.role_name)),
    ).length;
    const fiveV = pins.filter((p) => isFiveVoltTolerant(p)).length;
    const roleTiers = { standard: 0, function: 0, special: 0 };
    for (const p of pins) {
      const tier = roleStroke(p).tier;
      if (tier === 2) roleTiers.special += 1;
      else if (tier === 1) roleTiers.function += 1;
      else roleTiers.standard += 1;
    }
    const domains = new Map<string, number>();
    for (const p of pins) {
      if (p.supply) domains.set(p.supply, (domains.get(p.supply) ?? 0) + 1);
    }
    return { boot, reset, debug, osc, fiveV, roleTiers, domains };
  }, [pins]);

  return (
    <div className="flex flex-col gap-3" data-testid="pinout-legend">
      {/* Fill = category (the one saturated channel), a live filtering lens when a part is loaded */}
      <section>
        <Eyebrow className="mb-1.5">
          <Text id="stm.pinout.legend.category">Category</Text>
        </Eyebrow>
        <div className="grid grid-cols-2 gap-x-3 gap-y-0.5">
          {PIN_CATEGORIES.map((cat) => {
            const count = counts[cat.key] ?? 0;
            const active = highlight?.has(cat.key) ?? false;
            const interactive = !!pins && !!onToggleHighlight;
            const row = (
              <>
                <LegendSwatch token={cat.stroke} />
                <span className={"truncate text-xs " + (count || !pins ? "text-t2" : "text-t3")}>
                  {cat.label}
                </span>
                {pins ? (
                  <span className="tnum ml-auto font-mono text-2xs text-t3">{count}</span>
                ) : null}
              </>
            );
            return interactive ? (
              <button
                key={cat.key}
                type="button"
                aria-pressed={active}
                onClick={() => onToggleHighlight(cat.key)}
                className={
                  "flex w-full items-center gap-1.5 rounded-control px-1 py-0.5 text-left " +
                  (active ? "bg-acc-soft" : "hover:bg-hover")
                }
              >
                {row}
              </button>
            ) : (
              <div key={cat.key} className="flex items-center gap-1.5 px-1 py-0.5">
                {row}
              </div>
            );
          })}
        </div>
        {pins && onToggleHighlight ? (
          <p className="mt-1 text-2xs text-t3">
            <Text id="stm.pinout.legend.category-hint">Click a category to spotlight its pins.</Text>
          </p>
        ) : null}
      </section>

      {/* Border = role weight (neutral) */}
      <section>
        <Eyebrow className="mb-1.5">
          <Text id="stm.pinout.legend.role">Role</Text>
        </Eyebrow>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <RoleKey
            width={1}
            color="var(--c-line2)"
            label={standardLabel}
            count={facts?.roleTiers.standard}
          />
          <RoleKey
            width={1.25}
            color="var(--c-t2)"
            label={functionLabel}
            count={facts?.roleTiers.function}
          />
          <RoleKey
            width={1.75}
            color="var(--c-t1)"
            label={specialLabel}
            count={facts?.roleTiers.special}
          />
        </div>
        <p className="mt-1 text-2xs text-t3">
          <Text id="stm.pinout.legend.role-hint">Border weight marks a pin’s role.</Text>
        </p>
      </section>

      {/* Mark = 5V tolerant; Ring = selection (both neutral) */}
      <section className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <span className="flex items-center gap-1.5">
          <LegendSwatch token="var(--stm-gpio)" variant="dot" />
          <span className="text-xs text-t2">
            <Text id="stm.pinout.legend.five-v-tolerant">5V Tolerant</Text>
          </span>
          {facts ? <span className="tnum font-mono text-2xs text-t3">{facts.fiveV}</span> : null}
        </span>
        <span className="flex items-center gap-1.5">
          <LegendSwatch token="var(--stm-gpio)" variant="ring" />
          <span className="text-xs text-t2">
            <Text id="stm.pinout.legend.selected">Selected</Text>
          </span>
        </span>
      </section>

      {/* Bring-up facts for the loaded part */}
      {facts ? (
        <section data-testid="legend-key-pins">
          <Eyebrow className="mb-1.5">
            <Text id="stm.pinout.legend.bring-up">Bring-Up Pins</Text>
          </Eyebrow>
          <div className="flex flex-col gap-0.5">
            <KeyFact label={bootLabel} count={facts.boot} />
            <KeyFact label={resetLabel} count={facts.reset} />
            <KeyFact label={debugLabel} count={facts.debug} />
            <KeyFact label={oscillatorLabel} count={facts.osc} />
            {[...facts.domains.entries()].map(([domain, n]) => (
              <KeyFact key={domain} label={supplyLabel({ domain })} count={n} mono />
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}

function KeyFact({ label, count, mono }: { label: string; count: number; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3 px-1">
      <span className={(mono ? "font-mono " : "") + "text-xs " + (count ? "text-t2" : "text-t3")}>
        {label}
      </span>
      <span className="tnum font-mono text-2xs text-t3">{count}</span>
    </div>
  );
}

function RoleKey({
  width,
  color,
  label,
  count,
}: {
  width: number;
  color: string;
  label: string;
  count?: number;
}) {
  return (
    <div className="flex items-center gap-1.5">
      <span
        className="h-3 w-3 flex-none rounded-control bg-raise2"
        style={{ border: `${width}px solid ${color}` }}
      />
      <span className="text-xs text-t2">{label}</span>
      {count != null ? <span className="tnum font-mono text-2xs text-t3">{count}</span> : null}
    </div>
  );
}
