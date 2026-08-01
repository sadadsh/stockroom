/**
 * What ONE library-wide run could not finish by itself, as a short list of single actions.
 *
 * The owner's ask is *"a simple download button in our app that can do everything for you"*, and
 * most of that distance is reachable: the run above completes every part it is authorized to
 * complete with nobody watching. The rest cannot be automated at all - DigiKey serves CAD models
 * only through a page whose automation their terms forbid - so the honest remainder is presented
 * as WORK, not as an error log.
 *
 * The design rules this surface follows, because a "what is left" list is exactly the kind of
 * thing that turns into noise:
 *  - ONE row is ONE trip, and the row STARTS it. Its control runs the same person-driven capture
 *    the Complete Part window runs: the backend opens that provider on that exact component in the
 *    person's own browser and watches their Downloads, so what they download is imported. A row
 *    that merely opened a link routed the person and then dropped the result on the floor.
 *  - Nothing here clicks anything on a provider page, ever. The person does that.
 *  - The reason is the ROUTE'S OWN words ("no Ultra Librarian sign-in is saved..."), never a
 *    category this component invented from a status code.
 *  - The frontend never builds a provider URL. The backend owns opening the page; the plain link
 *    kept beside the control is the backend's own resolved URL, for someone who only wants a look.
 *  - Parts nothing can currently help are counted apart from parts a person can advance. Merging
 *    them would send someone to a provider that already said it has nothing.
 *  - ONE capture runs at a time (one slot in `lib/capture.tsx`, one process-wide exclusive window
 *    in the backend), so while one is in flight every other row says so instead of offering a
 *    start that would displace it.
 *  - ONE CLICK WORKS THE WHOLE LIST. Work Through All starts the first row and then starts the
 *    next one each time a capture reaches a terminal state, so the person clicks here once and
 *    then just works the provider pages as they appear. The advance is driven by capture
 *    completion and never by a timer, which is the only version of this that cannot open a page
 *    before the person has dealt with the last one.
 */
import { useEffect, useRef, useState } from "react";
import { useCadSourceQuery, useCaptureWorklist } from "../api/queries";
import type { CaptureWorklistRow, Requirement } from "../api/types";
import { captureAwaitsPerson, captureInFlight, REQ_LABELS, useCapture } from "../lib/capture";
import { CaptureRouteControls } from "./CaptureRouteControls";
import { Badge, Button } from "./primitives";

// A worklist is a sitting, not an inbox: the rows a person can realistically work through before
// the run is worth re-reading. The remainder is counted in full underneath, never hidden.
const VISIBLE_ROWS = 25;

export function CompletionWorklist({ batchId, live }: { batchId: string; live: boolean }) {
  const worklist = useCaptureWorklist(batchId, live);
  const capture = useCapture();
  const data = worklist.data;
  // Bounded here rather than after the early return below, because `useAutoAdvance` is a hook and
  // cannot sit behind one. An absent projection simply gives it nothing to work through.
  const rows = (data?.worklist ?? []).slice(0, VISIBLE_ROWS);
  const auto = useAutoAdvance(rows);
  // No projection yet, or a batch this route does not own: say nothing rather than claim a
  // library is finished. The run's own status block above is still authoritative.
  if (!data) return null;

  const hidden = data.worklist_total - rows.length;
  // ONE capture slot, so a start on any row is a start for all of them. Read once here and handed
  // down, rather than each row asking and the answers drifting apart mid-render. A pass that is
  // between rows holds the slot just as firmly as one mid-capture, so it counts as busy too.
  const capturing = captureInFlight(capture.active);
  const busy = capturing || auto.running;
  const runningPartId = capturing ? capture.active.partId : null;
  // A capture started from here is always person-driven, but the same slot can be holding an
  // automatic pass started from the Complete Part window, and that opens no page to finish.
  const awaitsPerson = captureAwaitsPerson(capture.active);
  // One slot, so a capture started anywhere can displace one started here. Rows are disabled while
  // a capture is in flight, so this list can never cause a supersession - but it can be on the
  // receiving end of one, and a row whose run stopped being followed must not go quiet about it.
  const displaced = capture.active.superseded;
  const superseded =
    displaced && rows.some((row) => row.part_id === displaced.partId) ? displaced : null;

  return (
    <div
      data-dev-id="settings.completion-worklist"
      data-testid="completion-worklist"
      className="mt-4 flex flex-col gap-2 border-t border-line pt-3"
    >
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={data.worklist_total ? "warn" : "ok"}>
          {data.worklist_total} Needs You
        </Badge>
        {data.unattended_total > 0 ? (
          <Badge tone="ok">{data.unattended_total} Done For You</Badge>
        ) : null}
        {data.pending_items > 0 ? (
          <Badge tone="neutral">{data.pending_items} Still Working</Badge>
        ) : null}
        {data.stalled_total > 0 ? (
          <Badge tone="neutral">{data.stalled_total} No Route</Badge>
        ) : null}
      </div>

      {data.worklist_total === 0 ? (
        <p className="text-sm text-t2">
          {data.pending_items > 0
            ? "Nothing needs you yet. This fills in as each component settles."
            : "Nothing on this run needs a person."}
        </p>
      ) : (
        <>
          {/* The promise this control can now keep: starting a row starts the real capture, so the
              file the person downloads is snapshotted, adopted, and put through the unchanged
              identity gates. Only the clicking is theirs. */}
          <p className="text-sm text-t2">
            These routes cannot be finished for you. Starting one opens that provider on this exact
            component in your own browser and watches your Downloads, so what you collect is filed
            against that component. Stockroom runs one capture at a time: Work Through All starts
            the first component and starts the next one as each capture finishes, so the only
            clicking left is on the provider pages themselves.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              small
              variant={auto.running ? "ghost-danger" : "accent"}
              data-dev-id="settings.completion-worklist-run"
              disabled={!auto.running && (busy || rows.length === 0)}
              title={
                auto.running
                  ? "Stop starting the next component. Whatever is open now stays open."
                  : busy
                    ? "Stockroom runs one capture at a time. Finish or skip the one in progress first."
                    : `Start ${rows.length === 1 ? "this component" : `all ${rows.length} components`} in order, one at a time`
              }
              aria-label={
                auto.running
                  ? "Stop working through the completion worklist"
                  : "Work through every listed component, one capture at a time"
              }
              onClick={() => (auto.running ? auto.stop() : auto.begin())}
            >
              {auto.running ? "Stop Advancing" : "Work Through All"}
            </Button>
            {auto.running ? (
              <span data-testid="completion-worklist-auto" className="text-2xs text-t2">
                {auto.openName
                  ? `Working through ${auto.done + 1} of ${auto.total}. ${auto.openName} is open in your browser; the next component starts when this capture finishes.`
                  : `Working through ${auto.done} of ${auto.total}. Starting the next component.`}
              </span>
            ) : null}
          </div>
          {auto.ended ? (
            <p data-testid="completion-worklist-auto-ended" className="text-sm text-t2">
              {auto.ended}
            </p>
          ) : null}
          {superseded ? (
            <p
              data-testid="completion-worklist-superseded"
              className="text-sm text-[var(--c-warn-text)]"
            >
              Completion for {superseded.partName || "an earlier component"} was superseded when
              the running capture started, so that run is no longer being followed. Start it again
              when this one finishes.
            </p>
          ) : null}
          <ul className="flex max-h-80 flex-col divide-y divide-line overflow-y-auto">
            {rows.map((row) => (
              <WorklistRow
                key={`${row.part_id}-${row.route_id}`}
                row={row}
                busy={busy}
                runningPartId={runningPartId}
                awaitsPerson={awaitsPerson}
                incomplete={auto.incomplete.includes(row.part_id)}
              />
            ))}
          </ul>
          {hidden > 0 ? (
            <p className="text-sm text-t3">
              {hidden} more {hidden === 1 ? "component needs" : "components need"} a person. Work
              through these first, then run it again: the next run re-reads what is genuinely left.
            </p>
          ) : null}
        </>
      )}

      {data.stalled_total > 0 ? (
        <p className="border-l-2 border-line pl-3 text-sm text-t2">
          <span className="tnum text-t2">{data.stalled_total}</span>{" "}
          {data.stalled_total === 1 ? "component" : "components"} finished with files still
          missing and no provider route a person could advance.
        </p>
      ) : null}
      {data.unreadable.length > 0 ? (
        <p className="text-sm text-t3">
          {data.unreadable.length}{" "}
          {data.unreadable.length === 1 ? "component report" : "component reports"} could not be
          read, so {data.unreadable.length === 1 ? "it is" : "they are"} not counted above.
        </p>
      ) : null}
    </div>
  );
}

function WorklistRow({
  row,
  busy,
  runningPartId,
  awaitsPerson,
  incomplete,
}: {
  row: CaptureWorklistRow;
  busy: boolean;
  runningPartId: string | null;
  awaitsPerson: boolean;
  // This row was started by the one-click pass and reached a terminal state without completing.
  // The row stays exactly where it is and says so: a row that quietly disappeared once its capture
  // failed would be a row nobody ever goes back to.
  incomplete: boolean;
}) {
  const name = row.display_name || row.mpn || row.part_id;
  const running = runningPartId === row.part_id;
  return (
    <li
      data-dev-id="settings.completion-worklist-row"
      data-part-id={row.part_id}
      data-route-id={row.route_id}
      data-capturing={running ? "true" : undefined}
      className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-x-3 gap-y-1 py-2"
    >
      <div className="min-w-0">
        <span className="block truncate text-xs font-medium text-t1">{name}</span>
        <span className="block truncate text-2xs text-t3">
          <span className="font-mono">{row.mpn || row.part_id}</span>
          <span aria-hidden="true"> · </span>
          {row.label}
        </span>
      </div>
      <div className="flex flex-none flex-col items-end gap-1">
        <StartCapture row={row} busy={busy} running={running} />
        <OpenProvider row={row} />
      </div>
      <p className="col-span-2 text-2xs leading-snug text-[var(--c-warn-text)]">{row.reason}</p>
      {incomplete ? (
        <p className="col-span-2 text-2xs leading-snug text-[var(--c-warn-text)]">
          This capture ended without completing, so this component still needs a trip. Start it
          again when you are ready.
        </p>
      ) : null}
      {row.remaining.length > 0 ? (
        <div className="col-span-2 flex flex-wrap items-center gap-1.5">
          <span className="text-2xs text-t3">Still needs</span>
          {row.remaining.map((requirement) => (
            <Badge key={requirement} tone="neutral" size="sm">
              {REQ_LABELS[requirement as Requirement] ?? requirement}
            </Badge>
          ))}
        </div>
      ) : null}
      {running && awaitsPerson ? (
        <div className="col-span-2 mt-1 rounded-control border border-line bg-field px-2.5 py-2">
          <CaptureRouteControls partId={row.part_id} />
        </div>
      ) : null}
    </li>
  );
}

// One component's trip, snapshotted at the click. The pass never re-reads the worklist while it is
// running: the projection refetches every five seconds underneath it, and a queue that reshuffled
// mid-pass would open a page the person was not expecting.
interface QueuedRow {
  partId: string;
  name: string;
  providerKey: string;
  remaining: Requirement[];
}

// ONE trip through the list, as data.
interface AutoAdvance {
  // Still to start, in the order the list showed them.
  queue: QueuedRow[];
  // The row whose capture is running right now, or null between rows.
  open: QueuedRow | null;
  total: number;
  // Part ids this pass took to a terminal state that was not a verified completion.
  incomplete: string[];
  // Why the pass is no longer advancing, in the person's words. Null while it is still running.
  ended: string | null;
}

/**
 * Work the whole list from ONE click.
 *
 * The advance is driven by the single capture slot reaching a TERMINAL state and by nothing else -
 * no timer, no interval, no optimistic guess about how long a provider page takes. That is the only
 * version of this that cannot open the next page before the person has dealt with the last one, and
 * it is also what keeps the "one capture at a time" rule intact: the next row is started from the
 * same effect that observed the previous one stop.
 *
 * It stops, and says why, in every case where continuing would be wrong:
 *  - the person presses Stop Advancing;
 *  - the person presses Skip This Part, which is them taking the list back by hand;
 *  - another surface takes the capture slot, which is the existing `superseded` concept rather
 *    than a second notion of "the run that stopped being followed";
 *  - a capture that never opened a page, or a runtime that reports capture unavailable, because
 *    that fault repeats identically for every remaining row and would walk the whole list.
 * A capture that DID open and then ended incomplete is a real trip: the pass moves on and names
 * that row as incomplete rather than dropping it.
 */
function useAutoAdvance(rows: CaptureWorklistRow[]) {
  const capture = useCapture();
  const start = capture.start;
  const active = capture.active;
  const [pass, setPass] = useState<AutoAdvance | null>(null);
  // Has the capture slot actually held the open row yet? `start` repoints the slot synchronously,
  // but the render carrying it can arrive a tick later, and a part id that does not match ours is
  // only a displacement once we have seen it match.
  const heldRef = useRef(false);
  // Did that capture get past `resolving` - did a provider page genuinely open? Not observing the
  // in-flight render errs towards stopping the pass, which is the safe direction.
  const openedRef = useRef(false);

  useEffect(() => {
    if (pass === null || pass.ended !== null) return;
    const open = pass.open;

    if (open !== null) {
      if (active.partId === open.partId) {
        heldRef.current = true;
        if (captureInFlight(active)) {
          if (active.status !== "resolving") openedRef.current = true;
          return;
        }
      } else {
        if (!heldRef.current) return;
        setPass({
          ...pass,
          ended: `Working through the list stopped: the capture for ${open.name} was superseded when another one started.`,
        });
        return;
      }
      const incomplete =
        active.status === "done" ? pass.incomplete : [...pass.incomplete, open.partId];
      const stopped =
        active.intentSent === "skip-part"
          ? `You skipped ${open.name}, so working through the list stopped there.`
          : active.status === "unavailable" || !openedRef.current
            ? `${open.name} could not be started, so working through the list stopped rather than opening every remaining page on the same fault.`
            : null;
      setPass({ ...pass, open: null, incomplete, ended: stopped });
      return;
    }

    const next = pass.queue[0];
    if (next === undefined) {
      const missed = pass.incomplete.length;
      setPass({
        ...pass,
        ended:
          missed > 0
            ? `Worked through all ${pass.total} ${pass.total === 1 ? "component" : "components"}. ${missed} did not complete and ${missed === 1 ? "is" : "are"} still listed above.`
            : `Worked through all ${pass.total} ${pass.total === 1 ? "component" : "components"}.`,
      });
      return;
    }
    heldRef.current = false;
    openedRef.current = false;
    setPass({ ...pass, queue: pass.queue.slice(1), open: next });
    void start(next.partId, next.name, next.remaining, next.providerKey, "assisted");
  }, [pass, active, start]);

  return {
    running: pass !== null && pass.ended === null,
    openName: pass?.open?.name ?? null,
    // How many rows this pass has already taken to a terminal state.
    done: pass ? pass.total - pass.queue.length - (pass.open ? 1 : 0) : 0,
    total: pass?.total ?? 0,
    incomplete: pass?.incomplete ?? [],
    ended: pass?.ended ?? null,
    begin() {
      if (rows.length === 0) return;
      heldRef.current = false;
      openedRef.current = false;
      setPass({
        queue: rows.map((row) => ({
          partId: row.part_id,
          name: row.display_name || row.mpn || row.part_id,
          providerKey: row.provider_key,
          remaining: row.remaining,
        })),
        open: null,
        total: rows.length,
        incomplete: [],
        ended: null,
      });
    },
    stop() {
      setPass((current) =>
        current === null || current.ended !== null
          ? current
          : {
              ...current,
              ended: current.open
                ? `Stopped working through the list. ${current.open.name} is still open in your browser; finish or skip it there.`
                : "Stopped working through the list.",
            },
      );
    },
  };
}

/**
 * The row's PRIMARY control: start the real capture for this component on this provider.
 *
 * It runs the same path the Complete Part window runs - one assisted capture naming this part and
 * this provider - so the backend opens the page in the person's own browser AND snapshots their
 * Downloads. That second half is the whole point: a control that only opened a link routed the
 * person and then had no way to receive what they collected.
 *
 * The frontend never constructs the provider URL; it sends the provider KEY the route reported and
 * lets the backend resolve and open it, which is the only version of this that cannot silently land
 * on the wrong page.
 */
function StartCapture({
  row,
  busy,
  running,
}: {
  row: CaptureWorklistRow;
  busy: boolean;
  running: boolean;
}) {
  const capture = useCapture();
  const name = row.display_name || row.mpn || row.part_id;
  // One slot: a start here while another capture is in flight would displace it. Say so rather
  // than offering the click and reporting the loss afterwards.
  const blocked = busy && !running;

  return (
    <Button
      small
      variant={running ? "default" : "accent"}
      data-dev-id="settings.completion-worklist-start"
      disabled={busy}
      title={
        running
          ? `Capturing ${row.label} for ${row.mpn || row.part_id} now`
          : blocked
            ? "Stockroom runs one capture at a time. Finish or skip the one in progress first."
            : `Capture ${row.label} for ${row.mpn || row.part_id}`
      }
      // Twenty-five rows of "Start Capture" are twenty-five identical button names to anyone
      // reading by voice, so the component and provider travel in the accessible name.
      aria-label={`Start the ${row.label} capture for ${name}`}
      onClick={() =>
        void capture.start(row.part_id, name, row.remaining, row.provider_key, "assisted")
      }
    >
      {running ? "Capturing" : "Start Capture"}
    </Button>
  );
}

/**
 * The secondary affordance: just look at the page, without starting anything.
 *
 * The href is whatever the backend resolved for THIS part on THIS provider - for DigiKey that is
 * already the exact models tab when a previous capture learned it. When the backend resolved no
 * page, this says so instead of offering a link that lands on a search for nothing. Downloading
 * from here imports nothing: no capture is running, so nothing is watching Downloads.
 */
function OpenProvider({ row }: { row: CaptureWorklistRow }) {
  const source = useCadSourceQuery(row.part_id, true);
  const target = source.data?.sources.find((candidate) => candidate.key === row.provider_key);

  if (!target?.url) {
    return (
      <span className="flex-none text-2xs text-t3">
        {source.isLoading ? "Finding the page..." : "No page resolved"}
      </span>
    );
  }
  return (
    <a
      href={target.url}
      target="_blank"
      rel="noreferrer"
      data-dev-id="settings.completion-worklist-open"
      // The provider's own instruction is deliberately NOT the tooltip here: for an
      // implemented provider it describes the capture Stockroom drives, and this control only
      // opens a page. Name the destination instead.
      title={`Open ${target.label} for ${row.mpn || row.part_id} without capturing`}
      // Twenty-five rows of "Open Ultra Librarian" are twenty-five identical link names to
      // anyone reading by voice. The part travels in the accessible name so each row is
      // distinguishable out of its visual context.
      aria-label={`Open ${target.label} for ${row.mpn || row.part_id} without capturing`}
      className={
        "inline-flex flex-none items-center gap-1 whitespace-nowrap rounded-control px-1 " +
        "text-2xs font-medium text-t3 transition-colors hover:text-t1 " +
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 " +
        "focus-visible:outline-acc"
      }
    >
      Open {target.label}
      <svg
        width="10"
        height="10"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        aria-hidden="true"
      >
        <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
        <path d="M15 3h6v6M10 14 21 3" />
      </svg>
    </a>
  );
}
