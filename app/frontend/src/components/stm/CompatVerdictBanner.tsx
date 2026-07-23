/**
 * CompatVerdictBanner (COMPAT-05): the set-level verdict, rendered as the workbench's one dominant
 * focal element (CONTEXT decision 5) above the union map, never buried in the position grid. It
 * states either "interchangeable with N swaps" (ok tone) or "incompatible" (err tone) with the
 * blocking positions / signals / reasons listed beneath it.
 *
 * Status color runs only through the Badge / Dot tone system and the ok / err token classes, never a
 * scattered color literal. The verdict message and each blocking reason are sentence-case prose; no
 * em dashes.
 */
import type { UnionDTO } from "../../api/types";
import { Card, Dot } from "../primitives";

// "no swaps" / "1 swap" / "N swaps", so the headline reads as natural sentence-case prose.
function swapPhrase(n: number): string {
  if (n <= 0) return "no swaps";
  return n === 1 ? "1 swap" : `${n} swaps`;
}

export function CompatVerdictBanner({ verdict }: { verdict: UnionDTO["verdict"] }) {
  const { interchangeable, swaps_required, blocking } = verdict;
  const headline = interchangeable
    ? `Interchangeable with ${swapPhrase(swaps_required)}`
    : "Incompatible";

  return (
    <Card className="flex flex-none flex-col gap-3 px-5 py-4" data-testid="compat-verdict-banner">
      <div className="flex items-center gap-2.5">
        <Dot tone={interchangeable ? "ok" : "err"} />
        <h3
          className={
            "text-lg font-semibold " + (interchangeable ? "text-ok" : "text-err")
          }
        >
          {headline}
        </h3>
      </div>

      {interchangeable ? (
        <p className="text-sm text-t2">
          Every part in the set carries the union's signals, with the reconciling swap shown on each
          divergent position.
        </p>
      ) : (
        <>
          <p className="text-sm text-t2">
            A required signal cannot be placed on every part in the set.
          </p>
          {blocking.length > 0 ? (
            <ul className="flex flex-col gap-1.5" data-testid="compat-blocking">
              {blocking.map((b, i) => (
                <li
                  key={`${b.position}-${b.signal}-${i}`}
                  className="flex flex-col gap-0.5 rounded-control bg-raise2 px-3 py-2"
                >
                  <div className="flex items-baseline gap-2">
                    <span className="flex-none font-mono text-xs text-t1">
                      Position {b.position}
                    </span>
                    <span className="min-w-0 truncate font-mono text-xs text-err">{b.signal}</span>
                  </div>
                  <p className="text-2xs text-t3">{b.reason}</p>
                </li>
              ))}
            </ul>
          ) : null}
        </>
      )}
    </Card>
  );
}
