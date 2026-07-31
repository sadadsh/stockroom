/**
 * The update standing every surface reads, with the two clocks the pure derivation cannot keep.
 *
 * `deriveUpdateStanding` stays pure: each bound it applies (how long a dead backend still reads as
 * a restart, how long an adoption may sit in flight) is a duration derived from instants passed in.
 * Something has to remember when those started, and the query cannot - React Query rewrites
 * `dataUpdatedAt` on every successful poll and `errorUpdatedAt` on every failed one, so neither
 * measures a STREAK.
 *
 * The clocks are module state rather than per-component refs because the rail, the status bar and
 * Settings all read this hook at once: three independent clocks would let a section mounted
 * mid-adoption disagree with the one that watched that adoption start.
 */
import { useUpdateCheck } from "../api/queries";
import {
  deriveUpdateStanding,
  isAdoptionInFlight,
  updateTargetRevision,
  type UpdateStandingView,
} from "./updateStanding";

const clocks: {
  adoption: { key: string; at: number } | null;
  failedSince: number | null;
} = { adoption: null, failedSince: null };

/** One module instance is shared by every test in a file, so a leftover clock would leak. */
export function resetUpdateClocksForTests() {
  clocks.adoption = null;
  clocks.failedSince = null;
}

export function useUpdateStanding(buildVersion: string = __APP_VERSION__): {
  query: ReturnType<typeof useUpdateCheck>;
  view: UpdateStandingView;
} {
  const query = useUpdateCheck();
  const now = Date.now();
  // ONE adoption, identified by what it is adopting: a phase that advances (applying ->
  // handing_off -> restarting) is progress on the same adoption and must not restart its clock.
  const adoptionKey = isAdoptionInFlight(query.data)
    ? updateTargetRevision(query.data) || "in-flight"
    : "";
  // Assigned during render on purpose, and idempotently: the standing derived below has to see the
  // clock that this render's data starts, not one an effect writes a paint later.
  if (!adoptionKey) clocks.adoption = null;
  else if (clocks.adoption?.key !== adoptionKey) clocks.adoption = { key: adoptionKey, at: now };
  if (query.isError) clocks.failedSince ??= now;
  else clocks.failedSince = null;
  return {
    query,
    view: deriveUpdateStanding({
      data: query.data,
      // `isFetching` is true on EVERY background refetch - every 5s while an update runs, plus
      // every window focus - so passing it here flickered a settled pill to "Checking..." on each
      // poll. `isPending` is the genuinely unknown-yet case: no answer has ever landed.
      checking: query.isPending,
      failed: query.isError,
      now,
      failedSince: clocks.failedSince ?? undefined,
      phaseStartedAt: clocks.adoption?.at,
      buildVersion,
    }),
  };
}
