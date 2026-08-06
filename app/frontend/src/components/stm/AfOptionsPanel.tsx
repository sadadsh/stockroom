/**
 * AfOptionsPanel (SWAP-01/02): the alternate-function vocabulary that makes remapping possible,
 * reachable from BOTH directions and always visible (CONTEXT decision 7 - the fix for CubeMX's
 * hidden Ctrl-click discoverability failure):
 * - From a selected pin: its complete AF0-15 set (GET /api/stm/pin/af), ordered by AF index.
 * - From a chosen peripheral signal: every candidate pin it can route to across the part
 *   (GET /api/stm/signal/candidates), ordered numeric-aware so A1, A2, A10 sort correctly.
 *
 * The signal direction is driven by clicking an AF row (a first-class control, never a modifier
 * key). Both queries are enabled-gated on their inputs, so nothing fetches until it is needed. A 409
 * routes to the same reused "index not built" message (decision 9). Read-only: it lists options,
 * it never applies one.
 */
import { useMemo, useState } from "react";
import { useStmPinAf, useStmSignalCandidates } from "../../api/stmQueries";
import { ApiError } from "../../api/client";
import { Eyebrow } from "../primitives";
import { Text } from "../../lib/copy";
import { withStableKeys } from "./listKeys";

// The single numeric-aware collation (mirrors PinoutViewer.tsx): it orders "1","2","10" correctly
// AND handles alphanumeric BGA labels "A1".."A10","AB12" - drop { numeric: true } and it goes red.
function comparePositions(a: string, b: string): number {
  return a.localeCompare(b, undefined, { numeric: true });
}

function is409(err: unknown): boolean {
  return err instanceof ApiError && err.status === 409;
}

// A new pin must clear the chosen signal (the previous signal may not exist on the new pin). That
// is a full state reset, so the caller keys this component on (part, position) and React remounts
// it - no adjustment effect, and no render where the old signal is still showing.
export function AfOptionsPanel({ part, position }: { part: string; position: string }) {
  const [signal, setSignal] = useState<string | null>(null);

  const pinAf = useStmPinAf(part, position);
  const candidates = useStmSignalCandidates(part, signal);

  const afs = useMemo(
    () => [...(pinAf.data?.alternate_functions ?? [])].sort((a, b) => a.af_index - b.af_index),
    [pinAf.data],
  );
  const cands = useMemo(
    () => [...(candidates.data?.candidates ?? [])].sort((a, b) => comparePositions(a.position, b.position)),
    [candidates.data],
  );
  // mcu_package_pin is UNIQUE(mcu_id, physical_pin_number, raw_pin_name) and raw_pin_name is not in
  // the candidate DTO, so two PINREMAP identities at one position can match on every field the row
  // carries. Key on that content and let withStableKeys disambiguate an exact repeat.
  const candRows = useMemo(
    () =>
      withStableKeys(cands, (c) => `${c.position}|${c.af_index}|${c.canonical_pin_name}`),
    [cands],
  );

  const notBuilt = is409(pinAf.error) || is409(candidates.error);

  return (
    <div className="flex flex-col gap-4" data-testid="af-options-panel">
      <section>
        <Eyebrow className="mb-1.5">
          <Text id="stm.af.options.title">Alternate Functions</Text>
        </Eyebrow>
        {notBuilt ? (
          <p className="text-xs text-t3">
            <Text id="stm.af.options.not-built">Build the index to see alternate functions.</Text>
          </p>
        ) : pinAf.isLoading ? (
          <p className="text-xs text-t3">
            <Text id="stm.af.options.loading">Loading alternate functions...</Text>
          </p>
        ) : pinAf.isError ? (
          <p className="text-xs text-err-text">
            <Text id="stm.af.options.failed">Could not load alternate functions.</Text>
          </p>
        ) : afs.length === 0 ? (
          <p className="text-xs text-t3">
            <Text id="stm.af.options.none">This pin has no alternate-function mux.</Text>
          </p>
        ) : (
          <ul className="flex flex-col gap-1">
            {/* pin_alternate_function is UNIQUE(mcu_package_pin_id, af_index, signal), so the
                (af_index, signal) pair is this pin's row id. */}
            {afs.map((af) => {
              const active = af.signal === signal;
              return (
                <li key={`${af.af_index}-${af.signal}`}>
                  <button
                    type="button"
                    aria-pressed={active}
                    onClick={() => setSignal((cur) => (cur === af.signal ? null : af.signal))}
                    className={
                      "flex w-full items-baseline justify-between gap-3 rounded-control px-2 py-1 text-left " +
                      (active ? "bg-acc-soft" : "hover:bg-[var(--c-hover)]")
                    }
                  >
                    <span className="min-w-0 truncate font-mono text-xs text-t1">
                      <span className="text-t3">AF{af.af_index}</span> {af.signal}
                    </span>
                    {af.peripheral ? (
                      <span className="flex-none font-mono text-2xs text-t3">{af.peripheral}</span>
                    ) : null}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section>
        <Eyebrow className="mb-1.5">
          <Text id="stm.af.options.candidates-title">Signal Candidates</Text>
        </Eyebrow>
        {!signal ? (
          <p className="text-xs text-t3">
            <Text id="stm.af.options.candidates-prompt">
              Select a signal above to see each candidate pin for it.
            </Text>
          </p>
        ) : candidates.isLoading ? (
          <p className="text-xs text-t3">
            <Text id="stm.af.options.candidates-loading">Loading candidate pins...</Text>
          </p>
        ) : candidates.isError ? (
          is409(candidates.error) ? (
            <p className="text-xs text-t3">
              <Text id="stm.af.options.candidates-not-built">
                Build the index to see candidate pins.
              </Text>
            </p>
          ) : (
            <p className="text-xs text-err-text">
              <Text id="stm.af.options.candidates-failed">Could not load candidate pins.</Text>
            </p>
          )
        ) : cands.length === 0 ? (
          <p className="text-xs text-t3">
            <Text id="stm.af.options.candidates-empty" values={{ signal }}>
              {"No candidate pins for {signal} on this part."}
            </Text>
          </p>
        ) : (
          <ul className="flex flex-col gap-1" data-testid="af-signal-candidates">
            <li className="px-2 pb-0.5 font-mono text-2xs text-t3">{signal}</li>
            {candRows.map(({ key, item: c }) => (
              <li
                key={key}
                className="flex items-baseline justify-between gap-3 px-2 py-0.5"
              >
                <span className="flex items-baseline gap-2">
                  <span className="w-10 flex-none font-mono text-xs text-t3">{c.position}</span>
                  <span className="font-mono text-xs text-t1">{c.canonical_pin_name}</span>
                </span>
                <span className="flex-none font-mono text-2xs text-t3">AF{c.af_index}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
