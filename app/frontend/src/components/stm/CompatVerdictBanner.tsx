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
import { Text, useCopyFormatter, useText } from "../../lib/copy";
import { plural } from "../../lib/plural";
import { Card, Dot } from "../primitives";

export function CompatVerdictBanner({ verdict }: { verdict: UnionDTO["verdict"] }) {
  const { interchangeable, swaps_required, blocking } = verdict;
  // "no swaps" / "1 swap" / "N swaps": three separate sentences rather than one assembled from a
  // count and a noun, because only the zero arm drops the number entirely.
  const noSwaps = useText("stm.compat.verdict.swaps-none", "no swaps");
  const oneSwap = useText("stm.compat.verdict.swaps-one", "1 swap");
  const manySwaps = useCopyFormatter("stm.compat.verdict.swaps-many", "{count} swaps");
  const interchangeableHeadline = useCopyFormatter(
    "stm.compat.verdict.interchangeable",
    "Interchangeable with {swaps}",
  );
  const incompatibleHeadline = useText("stm.compat.verdict.incompatible", "Incompatible");
  const swaps =
    swaps_required <= 0
      ? noSwaps
      : swaps_required === 1
        ? oneSwap
        : manySwaps({ count: swaps_required });
  const headline = interchangeable
    ? interchangeableHeadline({ swaps })
    : incompatibleHeadline;

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
          <Text id="stm.compat.verdict.ok-body">
            Every part in the set carries the union's signals, with the reconciling swap shown on
            each divergent position.
          </Text>
        </p>
      ) : (
        <>
          <p className="text-sm text-t2">
            <Text id="stm.compat.verdict.blocked-body">
              A required signal cannot be placed on every part in the set.
            </Text>
            {blocking.length > 0 ? (
              <>
                {" "}
                <Text
                  id="stm.compat.verdict.blocking-count"
                  values={{
                    count: blocking.length,
                    noun: plural(blocking.length, "position"),
                  }}
                >
                  {"{count} blocking {noun}."}
                </Text>
              </>
            ) : null}
          </p>
          {blocking.length > 0 ? (
            // Bounded: a big set can block on dozens of positions; the list scrolls inside the
            // banner so the verdict never pushes the union map itself out of the viewport.
            <ul
              className="flex max-h-56 flex-col gap-1.5 overflow-y-auto"
              data-testid="compat-blocking"
            >
              {blocking.map((b, i) => (
                <li
                  key={`${b.position}-${b.signal}-${i}`}
                  className="flex flex-col gap-0.5 rounded-control bg-raise2 px-3 py-2"
                >
                  <div className="flex items-baseline gap-2">
                    <span className="flex-none font-mono text-xs text-t1">
                      <Text
                        id="stm.compat.verdict.position"
                        values={{ position: b.position }}
                      >
                        {"Position {position}"}
                      </Text>
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
