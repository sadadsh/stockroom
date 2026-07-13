/**
 * The circular completeness passport indicator from the mockup (renderDetail's
 * ring). Draws score/total as an arc; green when complete, warn while parts are
 * missing. total is the passport size (REQUIRED_FIELDS in stockroom.model.part).
 */

interface Props {
  score: number;
  total: number;
  complete: boolean;
}

export function CompletenessRing({ score, total, complete }: Props) {
  const size = 56;
  const r = 24;
  const c = 2 * Math.PI * r;
  const frac = total > 0 ? Math.max(0, Math.min(1, score / total)) : 0;
  const offset = c * (1 - frac);
  const color = complete ? "var(--c-ok)" : "var(--c-warn)";
  return (
    <div className="relative h-14 w-14 flex-none">
      <svg width={size} height={size} viewBox="0 0 56 56">
        <circle
          cx="28"
          cy="28"
          r={r}
          fill="none"
          style={{ stroke: "var(--c-ring-track)" }}
          strokeWidth="4"
        />
        <circle
          cx="28"
          cy="28"
          r={r}
          fill="none"
          style={{ stroke: color }}
          strokeWidth="4"
          strokeLinecap="round"
          strokeDasharray={c.toFixed(1)}
          strokeDashoffset={offset.toFixed(1)}
          transform="rotate(-90 28 28)"
        />
      </svg>
      <span className="tnum absolute inset-0 flex items-center justify-center text-[12px] font-semibold text-t1">
        {score}/{total}
      </span>
    </div>
  );
}
