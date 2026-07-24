/**
 * SwitchPlanTable: the Bench's socket switch plan (owner redesign 2026-07-23). For a ZIF-socket
 * board hosting every part in the set (the NETDECK build-card architecture), this is the readout
 * that matters: every position that is NOT identical across the set, what the baseline identity
 * is, who diverges, and what it takes to reconcile - an AF swap (software), or a blocker that
 * needs real switching/isolation hardware on the socket board.
 *
 * Derived entirely from the union already in hand (no fetch). A row expands into the full
 * per-part audit trail + reconcile detail (the same CompatReconcileDetail the map click uses).
 */
import { Fragment, useMemo, useState } from "react";
import type { UnionDTO, UnionPositionDTO } from "../../api/types";
import { Badge, Eyebrow } from "../primitives";
import { CLASSIFICATION_LABEL, classificationTone } from "./compatEncoding";
import { CompatReconcileDetail } from "./CompatReconcileDetail";

// The dominant identity at a position: the most common (name, functions) story among the parts
// present, i.e. what the socket pin "usually is". Divergers are the parts telling another story.
export function baselineIdentity(position: UnionPositionDTO): {
  name: string;
  functions: string[];
  divergers: { ref: string; canonical_pin_name: string }[];
} {
  const tally = new Map<string, { count: number; name: string; functions: string[] }>();
  for (const pp of position.per_part) {
    const key = `${pp.canonical_pin_name}|${[...pp.functions].sort().join(",")}`;
    const cur = tally.get(key);
    if (cur) cur.count += 1;
    else tally.set(key, { count: 1, name: pp.canonical_pin_name, functions: pp.functions });
  }
  let best: { count: number; name: string; functions: string[] } | null = null;
  let bestKey = "";
  for (const [key, entry] of tally) {
    if (!best || entry.count > best.count) {
      best = entry;
      bestKey = key;
    }
  }
  const divergers = position.per_part
    .filter(
      (pp) => `${pp.canonical_pin_name}|${[...pp.functions].sort().join(",")}` !== bestKey,
    )
    .map((pp) => ({ ref: pp.ref, canonical_pin_name: pp.canonical_pin_name }));
  return { name: best?.name ?? "", functions: best?.functions ?? [], divergers };
}

// One switch-plan row's resolution story, in socket-board terms.
function resolution(position: UnionPositionDTO): { label: string; tone: "ok" | "warn" | "err" | "neutral" } {
  if (position.classification === "partial") {
    return {
      label: `Absent on ${position.total - position.present_on} of ${position.total}`,
      tone: "neutral",
    };
  }
  const rec = position.reconcile;
  if (rec?.swappable) {
    const n = rec.swaps.length;
    return { label: n > 0 ? `AF swap on ${n} ${n === 1 ? "part" : "parts"}` : "No swap needed", tone: "warn" };
  }
  if (rec && !rec.swappable) {
    return { label: "Needs switching hardware", tone: "err" };
  }
  return { label: "", tone: "neutral" };
}

export function SwitchPlanTable({ union }: { union: UnionDTO }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const rows = useMemo(
    () => union.positions.filter((p) => p.classification !== "shared"),
    [union.positions],
  );
  const sharedCount = union.positions.length - rows.length;

  return (
    <section className="flex flex-col gap-2" data-testid="switch-plan">
      <div className="flex items-baseline justify-between gap-3">
        <Eyebrow>Switch Plan</Eyebrow>
        <span className="tnum font-mono text-2xs text-t3">
          {sharedCount} shared · {rows.length} need attention
        </span>
      </div>
      {rows.length === 0 ? (
        <p className="rounded-card bg-stage px-4 py-6 text-center text-sm text-t3 shadow-[inset_0_1px_0_var(--edge-hi)]">
          Every position is identical across the set. A plain socket carries all parts.
        </p>
      ) : (
        <div className="max-h-80 overflow-auto rounded-card bg-stage shadow-[inset_0_1px_0_var(--edge-hi)]">
          <table className="w-full border-collapse text-left">
            <thead className="sticky top-0 z-[1] bg-[var(--c-sticky)] backdrop-blur">
              <tr className="border-b border-line text-2xs font-semibold text-t3">
                <th className="px-2.5 py-1.5">Position</th>
                <th className="px-2.5 py-1.5">State</th>
                <th className="px-2.5 py-1.5">Baseline</th>
                <th className="px-2.5 py-1.5">Divergence</th>
                <th className="px-2.5 py-1.5">Resolution</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => {
                const base = baselineIdentity(p);
                const res = resolution(p);
                const open = expanded === p.position;
                return (
                  <Fragment key={p.position}>
                    <tr
                      onClick={() => setExpanded(open ? null : p.position)}
                      aria-expanded={open}
                      className={
                        "cursor-pointer border-b border-line/60 align-top " +
                        (open ? "bg-acc-soft" : "hover:bg-hover")
                      }
                    >
                      <td className="tnum px-2.5 py-1.5 font-mono text-xs text-t1">
                        {p.position}
                      </td>
                      <td className="px-2.5 py-1.5">
                        <Badge tone={classificationTone(p.classification)} size="sm">
                          {CLASSIFICATION_LABEL[p.classification]}
                        </Badge>
                      </td>
                      <td className="px-2.5 py-1.5">
                        <span className="font-mono text-xs text-t1">{base.name}</span>
                        {base.functions.length > 0 ? (
                          <span className="ml-1.5 font-mono text-2xs text-t3">
                            {base.functions.slice(0, 3).join(" · ")}
                            {base.functions.length > 3 ? " …" : ""}
                          </span>
                        ) : null}
                      </td>
                      <td className="px-2.5 py-1.5 font-mono text-2xs text-t2">
                        {base.divergers.length > 0
                          ? `${base.divergers.length} ${base.divergers.length === 1 ? "part" : "parts"}`
                          : ""}
                      </td>
                      <td className="px-2.5 py-1.5">
                        {res.label ? (
                          <Badge tone={res.tone} size="sm">
                            {res.label}
                          </Badge>
                        ) : null}
                      </td>
                    </tr>
                    {open ? (
                      <tr className="border-b border-line/60">
                        <td colSpan={5} className="px-2.5 py-2">
                          <CompatReconcileDetail position={p} />
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
