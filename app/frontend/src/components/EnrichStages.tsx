/**
 * The honest loading affordance for a distributor lookup (spec section 8). The pipeline
 * streams its REAL phases over SSE (fetching -> rendering -> extracting -> validating), so
 * this shows a four-segment rail that fills as the scrape actually advances rather than a
 * bare spinner or a faked percentage. Completed phases are solid, the in-flight phase runs a
 * shimmer (indeterminate WITHIN a phase, since there is no sub-phase percentage to fake), and
 * the line beneath names the current phase and its live message. The rail deliberately dwells
 * on Rendering: that is the multi-second browser settle past the bot wall, and that is true.
 */
import { motion } from "motion/react";
import type { JobProgress } from "../lib/useJob";

const STAGES = [
  { key: "fetching", label: "Fetching", pct: 15 },
  { key: "rendering", label: "Rendering", pct: 45 },
  { key: "extracting", label: "Reading", pct: 80 },
  { key: "validating", label: "Checking", pct: 92 },
] as const;

// A plain-language fallback line per phase, shown until the pipeline's own message arrives.
const STAGE_HINT: Record<string, string> = {
  queued: "Starting the lookup",
  fetching: "Loading the distributor page",
  rendering: "Getting past the bot wall and settling the page",
  extracting: "Reading identity, specs, pricing and stock",
  validating: "Checking the pulled values",
};

export function EnrichStages({
  progress,
  className = "",
}: {
  progress: JobProgress | null;
  className?: string;
}) {
  // Track the reached phase off the MONOTONIC pct, not the raw stage: the multi-source MPN walk
  // re-emits earlier stages (LCSC 'extracting' then the scrape source 'fetching'), and the
  // pipeline already clamps pct so it never rewinds. Keying the rail off pct means a completed
  // segment never un-fills. The furthest phase whose threshold pct has been reached is active.
  const pct = progress?.pct ?? 0;
  let activeIndex = 0;
  for (let i = 0; i < STAGES.length; i++) {
    if (pct >= STAGES[i].pct) activeIndex = i;
  }
  const activeLabel = STAGES[activeIndex]?.label ?? "Working";
  // The live message reflects the current activity (the pipeline's own message when present).
  // Before any phase is reached (pct 0, the job just queued) show the starting hint; otherwise
  // fall back to a plain-language hint for the reached phase.
  const hint = pct < STAGES[0].pct ? STAGE_HINT.queued : STAGE_HINT[STAGES[activeIndex].key];
  const message = progress?.message || hint || "Working";

  return (
    <div className={`flex flex-col gap-2 ${className}`}>
      <div
        className="flex items-center gap-1.5"
        role="progressbar"
        aria-label="Enriching from the distributor"
        aria-valuetext={activeLabel}
      >
        {STAGES.map((s, i) => {
          const done = i < activeIndex;
          const isActive = i === activeIndex;
          return (
            <div key={s.key} className="h-1 flex-1 overflow-hidden bg-raise2">
              {done ? (
                <div className="h-full w-full bg-acc" />
              ) : isActive ? (
                <motion.div
                  className="h-full w-1/2 bg-acc"
                  animate={{ x: ["-60%", "220%"] }}
                  transition={{ duration: 1.15, repeat: Infinity, ease: "easeInOut" }}
                />
              ) : null}
            </div>
          );
        })}
      </div>
      <span className="text-xs text-t2">
        <span className="font-medium text-t1">{activeLabel}</span>
        <span className="text-t3"> · </span>
        {message}
      </span>
    </div>
  );
}
