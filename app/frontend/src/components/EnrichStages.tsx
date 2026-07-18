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
  { key: "fetching", label: "Fetching" },
  { key: "rendering", label: "Rendering" },
  { key: "extracting", label: "Reading" },
  { key: "validating", label: "Checking" },
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
  const stage = progress?.stage ?? "queued";
  const found = STAGES.findIndex((s) => s.key === stage);
  // queued / unknown -> the first phase is the one in flight, nothing completed yet.
  const activeIndex = found === -1 ? 0 : found;
  const activeLabel = STAGES[activeIndex]?.label ?? "Working";
  const message = progress?.message || STAGE_HINT[stage] || "Working";

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
            <div key={s.key} className="h-1 flex-1 overflow-hidden rounded-full bg-raise2">
              {done ? (
                <div className="h-full w-full rounded-full bg-acc" />
              ) : isActive ? (
                <motion.div
                  className="h-full w-1/2 rounded-full bg-acc"
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
