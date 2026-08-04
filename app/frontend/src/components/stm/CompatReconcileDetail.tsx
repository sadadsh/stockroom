/**
 * CompatReconcileDetail (COMPAT-03): the click detail for one union position. It shows the per-part
 * audit trail (so no classification is ever a silent majority collapse, CONTEXT decision 3) and, for
 * a divergent position, the alternate-function swaps that reconcile it across the set, or an
 * un-swappable reason.
 *
 * This is strictly READ-ONLY and non-mutating (CONTEXT decision 4): it describes a swap, it never
 * applies one and issues no request of any kind. It holds no mutation hook and no write call by
 * design - a swap is shown, never performed (no CubeMX-style silent auto-remap).
 */
import type { UnionPositionDTO } from "../../api/types";
import { Badge, Card } from "../primitives";
import { Text, useText } from "../../lib/copy";
import { CLASSIFICATION_LABEL, classificationTone } from "./compatEncoding";

export function CompatReconcileDetail({ position }: { position: UnionPositionDTO }) {
  const { classification, per_part, reconcile } = position;
  const unreconcilable = useText(
    "stm.compat.reconcile.unreconcilable",
    "This position cannot be reconciled across the set.",
  );

  return (
    <Card className="flex flex-col gap-4 px-4 py-3" data-testid="compat-reconcile-detail">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-sm font-semibold text-t1">
          <Text id="stm.compat.reconcile.position" values={{ position: position.position }}>
            {"Position {position}"}
          </Text>
        </span>
        <Badge tone={classificationTone(classification)} size="sm">
          {CLASSIFICATION_LABEL[classification]}
        </Badge>
        <span className="font-mono text-2xs text-t3">
          <Text
            id="stm.compat.reconcile.part-count"
            values={{ present: position.present_on, total: position.total }}
          >
            {"{present}/{total} parts"}
          </Text>
        </span>
      </div>

      {reconcile ? (
        reconcile.swappable ? (
          <section>
            <div className="mb-1.5 text-2xs font-semibold text-t3">
              <Text id="stm.compat.reconcile.swaps-title">Reconciling Swaps</Text>
            </div>
            {reconcile.swaps.length > 0 ? (
              <ul className="flex flex-col gap-1">
                {reconcile.swaps.map((s, i) => (
                  <li
                    key={`${s.ref}-${s.via_af_index}-${i}`}
                    className="flex items-baseline justify-between gap-3"
                  >
                    <span className="flex-none font-mono text-xs text-t1">{s.ref}</span>
                    <span className="min-w-0 truncate font-mono text-xs text-t2">
                      <span className="text-t3">AF{s.via_af_index}</span> {s.target_signal}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-t3">
                <Text id="stm.compat.reconcile.no-swap">
                  No swap is needed to reconcile this position.
                </Text>
              </p>
            )}
          </section>
        ) : (
          <section className="flex flex-col gap-1.5">
            <Badge tone="err" size="sm" className="self-start">
              <Text id="stm.compat.reconcile.un-swappable">Un-Swappable</Text>
            </Badge>
            <p className="text-xs text-t2">{reconcile.reason ?? unreconcilable}</p>
          </section>
        )
      ) : null}

      <section>
        <div className="mb-1.5 text-2xs font-semibold text-t3">
          <Text id="stm.compat.reconcile.per-part-title">Per Part</Text>
        </div>
        {/* Bounded: the audit trail across a whole-family set runs to dozens of parts; it
            scrolls inside the card rather than stretching the page. */}
        <ul className="flex max-h-64 flex-col gap-2 overflow-y-auto" data-testid="compat-per-part">
          {per_part.map((pp, i) => (
            <li key={`${pp.ref}-${i}`} className="flex flex-col gap-0.5">
              <div className="flex items-baseline justify-between gap-3">
                <span className="flex-none font-mono text-xs text-t1">{pp.ref}</span>
                <span className="font-mono text-2xs text-t3">{pp.canonical_pin_name}</span>
              </div>
              {pp.roles.length > 0 ? (
                <div className="text-2xs text-t3">
                  <Text
                    id="stm.compat.reconcile.roles"
                    values={{ roles: pp.roles.join(", ") }}
                  >
                    {"Roles: {roles}"}
                  </Text>
                </div>
              ) : null}
              {pp.functions.length > 0 ? (
                <div className="truncate font-mono text-2xs text-t3">
                  <Text
                    id="stm.compat.reconcile.functions"
                    values={{ functions: pp.functions.join(", ") }}
                  >
                    {"Functions: {functions}"}
                  </Text>
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      </section>
    </Card>
  );
}
