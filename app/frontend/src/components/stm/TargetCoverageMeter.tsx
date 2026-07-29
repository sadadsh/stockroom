import { formatPercent } from "../../lib/stmTargetInsights";

export function TargetCoverageMeter({
  value,
  total,
  token = "var(--stm-classify-shared)",
  label,
  compact = false,
}: {
  value: number;
  total: number;
  token?: string;
  label: string;
  compact?: boolean;
}) {
  const safeTotal = Math.max(0, total);
  const safeValue = Math.max(0, Math.min(value, safeTotal));
  const width = safeTotal ? (safeValue / safeTotal) * 100 : 0;

  return (
    <div aria-label={`${label}: ${safeValue} of ${safeTotal}`}>
      <div className="flex items-baseline justify-between gap-2">
        <span className={`${compact ? "text-2xs" : "text-xs"} text-t2`}>
          {label}
        </span>
        <span className="font-mono text-2xs text-t3">
          {safeValue} Of {safeTotal} · {formatPercent(safeValue, safeTotal)}
        </span>
      </div>
      <div
        className={`${compact ? "mt-1 h-1" : "mt-1.5 h-1.5"} overflow-hidden rounded-control bg-raise2`}
      >
        <div
          className="h-full rounded-control"
          style={{ width: `${width}%`, backgroundColor: token }}
        />
      </div>
    </div>
  );
}
