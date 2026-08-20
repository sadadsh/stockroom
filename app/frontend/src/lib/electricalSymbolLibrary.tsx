import { Icon } from "../components/Icon";

/** The component identities Stockroom can distinguish visually. */
export type ElectricalSymbolKind =
  | "battery"
  | "capacitor"
  | "capacitor-polarized"
  | "connector"
  | "crystal"
  | "diode"
  | "fuse"
  | "generic"
  | "ic"
  | "inductor"
  | "lamp"
  | "led"
  | "motor"
  | "opamp"
  | "pushbutton"
  | "resistor"
  | "switch"
  | "transformer"
  | "transistor"
  | "waveform";

/**
 * The category resolver is intentionally separate from presentation. Categories remain library
 * data; this registry owns only the stable visual language used to identify them.
 */
export function electricalSymbolForCategory(category: string): ElectricalSymbolKind {
  const normalized = category
    .normalize("NFKD")
    .toLocaleLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
  const tokens = new Set(normalized.split(" ").filter(Boolean));
  const has = (...terms: string[]) => terms.some((term) => tokens.has(term));

  // A driver or switching regulator describes the IC's job, not the driven load or a switch.
  if (has("driver", "drivers") || normalized === "switching voltage regulators") return "generic";
  if (has("capacitor", "capacitors") && has("polar", "polarized", "polarised")) {
    return "capacitor-polarized";
  }
  if (has("resistor", "resistors", "thermistor", "thermistors", "varistor", "varistors")) return "resistor";
  if (has("capacitor", "capacitors")) return "capacitor";
  if (has("inductor", "inductors", "ferrite", "ferrites", "choke", "chokes")) return "inductor";
  if (normalized === "light emitting diodes" || normalized === "light emitting diode" || has("led", "leds")) return "led";
  if (has("diode", "diodes", "rectifier", "rectifiers")) return "diode";
  if (has("transistor", "transistors", "mosfet", "mosfets", "igbt", "igbts", "fet", "fets")) return "transistor";
  if (normalized === "op amp" || normalized === "op amps" || has("opamp", "opamps") ||
      (has("operational") && has("amplifier", "amplifiers"))) return "opamp";
  if (has("relay", "relays", "switch", "switches")) return "switch";
  if (has("pushbutton", "pushbuttons") || (has("push") && has("button", "buttons"))) return "pushbutton";
  if (has("connector", "connectors", "header", "headers", "socket", "sockets")) return "connector";
  if (has("crystal", "crystals", "oscillator", "oscillators", "resonator", "resonators")) return "crystal";
  if (has("transformer", "transformers")) return "transformer";
  if (has("battery", "batteries") || normalized === "cell" || normalized === "cells") return "battery";
  if (has("fuse", "fuses")) return "fuse";
  if (normalized === "motor" || normalized === "motors") return "motor";
  if (has("lamp", "lamps", "bulb", "bulbs")) return "lamp";
  if (["ic", "ics", "integrated circuit", "integrated circuits", "logic gate", "logic gates"].includes(normalized)) return "ic";
  return "generic";
}

export function ElectricalSymbol({
  kind,
  className = "",
  title,
}: {
  kind: ElectricalSymbolKind;
  className?: string;
  title?: string;
}) {
  return (
    <span
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
      data-electrical-symbol={kind}
      className={`electrical-symbol inline-flex items-center justify-center ${className}`}
    >
      <Icon id={`category.${kind}`} className="h-full w-full" />
    </span>
  );
}

export const ELECTRICAL_SYMBOL_KINDS = Object.freeze(
  [
    "battery",
    "capacitor",
    "capacitor-polarized",
    "connector",
    "crystal",
    "diode",
    "fuse",
    "generic",
    "ic",
    "inductor",
    "lamp",
    "led",
    "motor",
    "opamp",
    "pushbutton",
    "resistor",
    "switch",
    "transformer",
    "transistor",
    "waveform",
  ] as ElectricalSymbolKind[],
);
