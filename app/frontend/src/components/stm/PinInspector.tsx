/**
 * PinInspector (VIZ-03): every derived fact for the clicked pin, looked up client-side from the
 * already-fetched PinoutDTO (CONTEXT decision 4), so it makes NO network call of its own. Read-only
 * facts only, including the full alternate-function set (the assignment/swap UI is Phase 5).
 *
 * Layout follows the design-rules "pin header" + "detail" recipes: a mono hero name, a quiet
 * sentence-case metadata line with the category dot, then a plain definition list. Mono for machine
 * values so signals/AF columns align; Title Case section labels; no em dashes.
 */
import type { PinDTO } from "../../api/types";
import { Eyebrow } from "../primitives";
import { categoryFill, categoryLabel, isFiveVoltTolerant } from "./pinEncoding";
import { AfOptionsPanel } from "./AfOptionsPanel";

const SIDE_LABEL: Record<string, string> = {
  left: "Left",
  right: "Right",
  top: "Top",
  bottom: "Bottom",
};

// `part` is the active ref_name / MPN the pin belongs to. When present, AfOptionsPanel (SWAP-01/02)
// composes in as a section of the inspector, reachable from both the pin and the signal directions.
export function PinInspector({ pin, part }: { pin: PinDTO; part?: string | null }) {
  const fiveV = isFiveVoltTolerant(pin);
  return (
    <div className="flex flex-col gap-4" data-testid="pin-inspector">
      {/* hero: the pin name is the one focal element */}
      <div>
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-lg font-semibold text-t1">{pin.canonical_pin_name}</span>
          <span className="font-mono text-xs text-t3">Pin {pin.position}</span>
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-t2">
          <span className="flex items-center gap-1.5">
            <span
              className="h-[7px] w-[7px] flex-none rounded-full"
              style={{ backgroundColor: categoryFill(pin.category) }}
            />
            {categoryLabel(pin.category)}
          </span>
          {pin.pin_type ? (
            <>
              <Sep />
              <span>{pin.pin_type}</span>
            </>
          ) : null}
          {pin.lqfp_side ? (
            <>
              <Sep />
              <span>{SIDE_LABEL[pin.lqfp_side]} side</span>
            </>
          ) : null}
          {fiveV ? (
            <>
              <Sep />
              <span>5V tolerant</span>
            </>
          ) : null}
        </div>
        {pin.raw_pin_name && pin.raw_pin_name !== pin.canonical_pin_name ? (
          <div className="mt-1 font-mono text-2xs text-t3">Raw {pin.raw_pin_name}</div>
        ) : null}
      </div>

      {pin.supply ? (
        <Row label="Supply">
          <span className="font-mono text-sm text-t1">{pin.supply}</span>
        </Row>
      ) : null}

      {/* When the active part is known, AfOptionsPanel owns the interactive alternate-function
          surface (both directions), so the static AF list is suppressed to avoid a duplicate. */}
      <FunctionSections pin={pin} showAf={!part} />

      {part ? <AfOptionsPanel part={part} position={pin.position} /> : null}

      {pin.roles.length > 0 ? (
        <Section label="Roles">
          <ul className="flex flex-col gap-1">
            {pin.roles.map((r, i) => (
              <li key={`${r.role_name}-${i}`} className="flex items-baseline justify-between gap-3">
                <span className="text-xs text-t1">{r.role_name}</span>
                <span className="flex-none font-mono text-2xs text-t3">{r.role_class}</span>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      <Section label="5V Tolerance">
        {pin.five_v ? (
          <div className="flex flex-col gap-1 text-xs text-t2">
            <span className="text-t1">{pin.five_v.tolerant ? "Tolerant" : "Not tolerant"}</span>
            {pin.five_v.caveat ? <span className="text-t3">{pin.five_v.caveat}</span> : null}
          </div>
        ) : (
          <span className="text-xs text-t3">Not applicable</span>
        )}
      </Section>
    </div>
  );
}

/**
 * The pin's function lists, split the way the mux actually works (the defect this replaces
 * showed one undifferentiated signal list with no AF indices):
 * - "Alternate Functions": the AF0-15 muxed signals, each with its AF index - the fact the
 *   whole compatibility feature runs on.
 * - "Analog & System": signals that are NOT AF-muxed (ADC/DAC inputs, wakeup, RTC refs),
 *   separated so an analog input never reads as a muxable function.
 * A pin with functions but NO AF set (the F1 legacy-AFIO families) keeps a single plain
 * "Functions" list: on those parts the split would be a fiction, not a fact.
 */
function FunctionSections({ pin, showAf }: { pin: PinDTO; showAf: boolean }) {
  const afs = pin.alternate_functions;
  const afSignals = new Set(afs.map((af) => af.signal));
  const plain = pin.functions.filter((fn) => !afSignals.has(fn.signal));

  if (afs.length === 0) {
    if (pin.functions.length === 0) return null;
    return (
      <Section label="Functions">
        <PlainFunctionList functions={pin.functions} />
      </Section>
    );
  }

  return (
    <>
      {showAf ? (
        <Section label="Alternate Functions">
          <ul className="flex flex-col gap-1">
            {afs.map((af, i) => (
              <li
                key={`${af.af_index}-${af.signal}-${i}`}
                className="flex items-baseline justify-between gap-3"
              >
                <span className="min-w-0 truncate font-mono text-xs text-t1">
                  <span className="text-t3">AF{af.af_index}</span> {af.signal}
                </span>
                {af.peripheral ? (
                  <span className="flex-none font-mono text-2xs text-t3">{af.peripheral}</span>
                ) : null}
              </li>
            ))}
          </ul>
        </Section>
      ) : null}
      {plain.length > 0 ? (
        <Section label="Analog & System">
          <PlainFunctionList functions={plain} />
        </Section>
      ) : null}
    </>
  );
}

function PlainFunctionList({ functions }: { functions: PinDTO["functions"] }) {
  return (
    <ul className="flex flex-col gap-1">
      {functions.map((fn, i) => (
        <li key={`${fn.signal}-${i}`} className="flex items-baseline justify-between gap-3">
          <span className="font-mono text-xs text-t1">{fn.signal}</span>
          {fn.io_modes ? <span className="truncate text-2xs text-t3">{fn.io_modes}</span> : null}
        </li>
      ))}
    </ul>
  );
}

function Sep() {
  return <span className="text-t3">·</span>;
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <section>
      <Eyebrow className="mb-1.5">{label}</Eyebrow>
      {children}
    </section>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <Eyebrow>{label}</Eyebrow>
      {children}
    </div>
  );
}
