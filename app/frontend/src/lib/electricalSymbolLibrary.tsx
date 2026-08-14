import batteryRaw from "@tabler/icons/outline/circuit-battery.svg?raw";
import bulbRaw from "@tabler/icons/outline/circuit-bulb.svg?raw";
import cellRaw from "@tabler/icons/outline/circuit-cell.svg?raw";
import motorRaw from "@tabler/icons/outline/circuit-motor.svg?raw";
import pushbuttonRaw from "@tabler/icons/outline/circuit-pushbutton.svg?raw";
import switchRaw from "@tabler/icons/outline/circuit-switch-open.svg?raw";
import cpuRaw from "@tabler/icons/outline/cpu.svg?raw";
import connectorRaw from "@tabler/icons/outline/plug-connected.svg?raw";
import waveformRaw from "@tabler/icons/outline/wave-sine.svg?raw";

import capacitorRaw from "../assets/electrical-symbols/iec/capacitor.svg?raw";
import polarizedCapacitorRaw from "../assets/electrical-symbols/iec/capacitor-polarized.svg?raw";
import diodeRaw from "../assets/electrical-symbols/iec/diode.svg?raw";
import ledRaw from "../assets/electrical-symbols/iec/diode-led.svg?raw";
import inductorRaw from "../assets/electrical-symbols/iec/inductor.svg?raw";
import opampRaw from "../assets/electrical-symbols/iec/opamp-single-output.svg?raw";
import piezoRaw from "../assets/electrical-symbols/iec/piezo.svg?raw";
import resistorRaw from "../assets/electrical-symbols/iec/resistor.svg?raw";
import transformerRaw from "../assets/electrical-symbols/iec/transformer.svg?raw";

/** The component identities Stockroom can distinguish visually. */
export type ElectricalSymbolKind =
  | "battery"
  | "capacitor"
  | "capacitor-polarized"
  | "connector"
  | "crystal"
  | "diode"
  | "fuse"
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

const IEC_ARTWORK: Partial<Record<ElectricalSymbolKind, string>> = {
  resistor: resistorRaw,
  capacitor: capacitorRaw,
  "capacitor-polarized": polarizedCapacitorRaw,
  inductor: inductorRaw,
  diode: diodeRaw,
  led: ledRaw,
  opamp: opampRaw,
  crystal: piezoRaw,
  transformer: transformerRaw,
};

const TABLER_ARTWORK: Partial<Record<ElectricalSymbolKind, string>> = {
  battery: batteryRaw,
  connector: connectorRaw,
  fuse: cellRaw,
  ic: cpuRaw,
  lamp: bulbRaw,
  motor: motorRaw,
  pushbutton: pushbuttonRaw,
  switch: switchRaw,
  transistor: cpuRaw,
  waveform: waveformRaw,
};

function injectableSvg(raw: string): string {
  const start = raw.indexOf("<svg");
  return start >= 0 ? raw.slice(start) : raw;
}

/**
 * The category resolver is intentionally separate from presentation. Categories remain library
 * data; this registry owns only the stable visual language used to identify them.
 */
export function electricalSymbolForCategory(category: string): ElectricalSymbolKind {
  const value = category.toLocaleLowerCase();
  if (value.includes("polar") && value.includes("capacitor")) return "capacitor-polarized";
  if (value.includes("resistor") || value.includes("thermistor") || value.includes("varistor")) {
    return "resistor";
  }
  if (value.includes("capacitor")) return "capacitor";
  if (value.includes("inductor") || value.includes("ferrite") || value.includes("choke")) {
    return "inductor";
  }
  if (value.includes("led") || value.includes("light emitting")) return "led";
  if (value.includes("diode") || value.includes("rectifier")) return "diode";
  if (
    value.includes("transistor") ||
    value.includes("mosfet") ||
    value.includes("igbt") ||
    value.includes("fet")
  ) {
    return "transistor";
  }
  if (value.includes("op amp") || value.includes("opamp") || value.includes("amplifier")) {
    return "opamp";
  }
  if (value.includes("relay") || value.includes("switch")) return "switch";
  if (value.includes("button")) return "pushbutton";
  if (value.includes("connector") || value.includes("header") || value.includes("socket")) {
    return "connector";
  }
  if (value.includes("crystal") || value.includes("oscillator") || value.includes("resonator")) {
    return "crystal";
  }
  if (value.includes("transformer")) return "transformer";
  if (value.includes("battery") || value.includes("cell")) return "battery";
  if (value.includes("fuse")) return "fuse";
  if (value.includes("motor")) return "motor";
  if (value.includes("lamp") || value.includes("bulb")) return "lamp";
  return "ic";
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
  const raw = IEC_ARTWORK[kind] ?? TABLER_ARTWORK[kind] ?? cpuRaw;
  return (
    <span
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
      data-electrical-symbol={kind}
      className={`electrical-symbol inline-flex items-center justify-center ${className}`}
      dangerouslySetInnerHTML={{ __html: injectableSvg(raw) }}
    />
  );
}

export const ELECTRICAL_SYMBOL_KINDS = Object.freeze(
  [...Object.keys(IEC_ARTWORK), ...Object.keys(TABLER_ARTWORK)] as ElectricalSymbolKind[],
);
