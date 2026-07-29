import type { TargetDefinitionPosition } from "../../api/types";
import {
  TARGET_LENS_GUIDANCE,
  buildTargetLegend,
  targetLegendIsExclusive,
  type TargetLegendEntry,
  type TargetMapLens,
} from "../../lib/stmTargetVisuals";
import { formatPercent } from "../../lib/stmTargetInsights";
import { LegendSwatch } from "../primitives";
import { InfoIcon } from "../icons";

export function TargetSmartLegend({
  positions,
  lens,
  activeKey,
  onSelect,
}: {
  positions: TargetDefinitionPosition[];
  lens: TargetMapLens;
  activeKey: string | null;
  onSelect: (key: string | null) => void;
}) {
  const catalog = buildTargetLegend(positions, lens, { includeEmpty: true });
  const entries = catalog.filter((entry) => entry.count > 0);
  const selected = catalog.find((entry) => entry.key === activeKey) ?? null;
  const exclusive = targetLegendIsExclusive(lens);
  const groups = [...new Set(catalog.map((entry) => entry.group))];

  return (
    <section
      data-dev-id="stm.target-legend"
      className="relative flex-none border-b border-line px-3 py-1.5"
      aria-label="Interactive Map Legend"
      data-testid="target-smart-legend"
    >
      <div className="flex items-center gap-2">
        <p
          className="min-w-0 flex-1 truncate text-2xs text-t3"
          title={selected ? `${selected.description} Measured from: ${selected.basis}` : TARGET_LENS_GUIDANCE[lens]}
        >
          <span className="font-medium text-t2">
            {selected ? selected.label : exclusive ? "Exclusive Map" : "Coverage Map"}
          </span>
          {" · "}
          {selected ? selected.description : TARGET_LENS_GUIDANCE[lens]}
        </p>
        <details
          className="group relative flex-none"
          data-dev-id="stm.target-legend-guide"
          data-testid="target-legend-guide"
        >
          <summary className="flex h-6 cursor-pointer list-none items-center gap-1 rounded-control px-1.5 text-2xs text-t3 hover:bg-hover hover:text-t1">
            <InfoIcon className="h-3.5 w-3.5" />
            Guide
            <span className="font-mono">
              {entries.length}/{catalog.length}
            </span>
          </summary>
          <div className="absolute right-0 top-full z-20 mt-1 grid max-h-[420px] w-[min(680px,calc(100vw-340px))] grid-cols-2 gap-x-5 gap-y-3 overflow-y-auto rounded-card border border-line2 bg-canvas px-3 py-3 shadow-pop">
            {groups.map((group) => (
              <section key={group}>
                <h3 className="mb-1 text-2xs font-medium text-t2">{group}</h3>
                <div className="space-y-1">
                  {catalog
                    .filter((entry) => entry.group === group)
                    .map((entry) => (
                      <button
                        key={entry.key}
                        type="button"
                        aria-pressed={activeKey === entry.key}
                        aria-label={`Inspect ${entry.label} Definition`}
                        onClick={() =>
                          onSelect(activeKey === entry.key ? null : entry.key)
                        }
                        className={`grid w-full grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-x-2 rounded-control border px-2 py-1.5 text-left ${
                          activeKey === entry.key
                            ? "border-acc bg-acc/[0.10]"
                            : "border-transparent hover:border-line hover:bg-hover"
                        } ${entry.count ? "" : "opacity-55"}`}
                      >
                        <LegendSwatch token={entry.token} />
                        <span>
                          <span className="block text-xs text-t2">{entry.label}</span>
                          <span className="mt-0.5 block text-2xs leading-relaxed text-t3">
                            {entry.description}
                          </span>
                          <span className="mt-1 block text-2xs leading-relaxed text-t3">
                            <span className="text-t2">Measured From: </span>
                            {entry.basis}
                          </span>
                        </span>
                        <span className="font-mono text-2xs text-t3">
                          {entry.count} ·{" "}
                          {formatPercent(entry.count, positions.length)}
                        </span>
                      </button>
                    ))}
                </div>
              </section>
            ))}
          </div>
        </details>
      </div>

      {exclusive ? (
        <div
          className="mt-1 flex h-1 overflow-hidden rounded-control bg-raise2"
          aria-label="Package Position Distribution"
          role="img"
        >
          {entries.map((entry) => (
            <button
              key={entry.key}
              type="button"
              title={`${entry.label}: ${entry.count} of ${positions.length} positions`}
              aria-label={`Filter ${entry.label}`}
              onClick={() => onSelect(activeKey === entry.key ? null : entry.key)}
              className={`h-full min-w-px transition-[filter,opacity] ${
                activeKey && activeKey !== entry.key
                  ? "opacity-20"
                  : "hover:brightness-125"
              }`}
              style={{
                width: `${entry.percentage}%`,
                backgroundColor: entry.token,
              }}
            />
          ))}
        </div>
      ) : null}

      <div className="mt-1 flex gap-1 overflow-x-auto pb-0.5">
        {entries.map((entry) => (
          <LegendEntryButton
            key={entry.key}
            entry={entry}
            total={positions.length}
            active={activeKey === entry.key}
            exclusive={exclusive}
            onSelect={onSelect}
          />
        ))}
      </div>
    </section>
  );
}

function LegendEntryButton({
  entry,
  total,
  active,
  exclusive,
  onSelect,
}: {
  entry: TargetLegendEntry;
  total: number;
  active: boolean;
  exclusive: boolean;
  onSelect: (key: string | null) => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      aria-label={`Show ${entry.label}`}
      onClick={() => onSelect(active ? null : entry.key)}
      className={`relative h-7 flex-none overflow-hidden rounded-control border px-2 text-left transition-colors ${
        active
          ? "border-acc bg-acc/[0.10]"
          : "border-line hover:border-line2 hover:bg-hover"
      }`}
    >
      {!exclusive ? (
        <span
          className="absolute inset-y-0 left-0 opacity-10"
          style={{
            width: `${entry.percentage}%`,
            backgroundColor: entry.token,
          }}
        />
      ) : null}
      <span className="relative flex h-full items-center gap-1.5">
        <LegendSwatch token={entry.token} />
        <span className="whitespace-nowrap text-2xs text-t2">
          {entry.shortLabel}
        </span>
        <span className="font-mono text-2xs text-t3">
          {entry.count} · {formatPercent(entry.count, total)}
        </span>
      </span>
    </button>
  );
}
