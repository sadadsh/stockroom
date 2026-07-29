import type {
  TargetBoardAction,
  TargetDefinitionPosition,
  TargetSiliconClass,
} from "../api/types";

export type TargetCompatibilityKind =
  | "identical"
  | "variant"
  | "partial"
  | "conflict";

export interface TargetCompatibilityInsight {
  kind: TargetCompatibilityKind;
  label: string;
  shortLabel: string;
  consequence: string;
  token: string;
}

export const TARGET_COMPATIBILITY_INSIGHTS: Record<
  TargetCompatibilityKind,
  TargetCompatibilityInsight
> = {
  identical: {
    kind: "identical",
    label: "Same Across All MCUs",
    shortLabel: "Same",
    consequence:
      "One universal connection can serve this position because its pin or fixed electrical role is identical across every selected MCU.",
    token: "var(--stm-classify-shared)",
  },
  variant: {
    kind: "variant",
    label: "GPIO Varies By MCU",
    shortLabel: "GPIO Changes",
    consequence:
      "The position exists on every selected MCU, but its GPIO identity changes. Keep signal assignments flexible.",
    token: "var(--stm-classify-divergent)",
  },
  partial: {
    kind: "partial",
    label: "Not On Every MCU",
    shortLabel: "Missing",
    consequence:
      "A universal design cannot depend on this position because some selected MCUs do not expose it.",
    token: "var(--stm-classify-partial)",
  },
  conflict: {
    kind: "conflict",
    label: "Electrical Conflict",
    shortLabel: "Conflict",
    consequence:
      "Electrical roles disagree. The universal design needs a proven routing adaptation: compact passive conditioning where safe, otherwise fully exclusive target-specific branches.",
    token: "var(--c-err)",
  },
};

export const TARGET_COMPATIBILITY_ORDER: TargetCompatibilityKind[] = [
  "identical",
  "variant",
  "partial",
  "conflict",
];

export const BOARD_ACTION_LABEL: Record<TargetBoardAction, string> = {
  hardwire: "Connect Permanently",
  breakout: "Expose For Use",
  direct: "Connect Directly",
  switched: "Use Controlled Switching",
  selectable: "Use Configurable Selection",
  isolate: "Keep Isolated",
  unsupported: "Do Not Use",
};

export const BOARD_ACTION_EXPLANATION: Record<TargetBoardAction, string> = {
  hardwire:
    "This fixed electrical role must be connected according to the MCU hardware requirements.",
  breakout:
    "Bring this position to an assignable board net or accessible test point.",
  direct:
    "The compiled policy permits one direct connection across all selected MCUs.",
  switched:
    "Route this position through controlled switching and preserve the declared safe default.",
  selectable:
    "Use a jumper, selector, or equivalent configuration so only the intended path is active.",
  isolate:
    "Do not join the conflicting MCU identities directly. Leave the position open unless a declared safety branch is selected.",
  unsupported:
    "Do not rely on this position in a universal design because it is unavailable on some selected MCUs.",
};

const TOKEN_LABELS: Record<string, string> = {
  analog: "Analog",
  blocked: "Blocked",
  boot: "Boot Control",
  boot0: "Boot 0",
  boot1: "Boot 1",
  breakout: "Breakout",
  complete: "Complete",
  direct: "Direct Connection",
  "documented-service": "Documented Service Path",
  ground: "Ground",
  gpio: "GPIO",
  "high-z": "High Impedance",
  io: "I/O",
  isolate: "Isolate",
  jtag: "JTAG",
  "no-connect": "No Connect",
  off: "Off",
  open: "Open",
  osc: "High-Speed Clock",
  osc32: "Low-Speed Clock",
  oscillator: "Oscillator",
  partial: "Partial Coverage",
  "pin-capability": "Pin Capability Only",
  "pin-obligation": "Pin Obligation",
  power: "Power",
  "power-control": "Power Control",
  recovery: "Recovery",
  reset: "Reset",
  "regulator-control": "Regulator Control",
  spi: "SPI",
  swclk: "SWD Clock",
  swdio: "SWD Data",
  swo: "SWO",
  switched: "Switched Connection",
  trace: "Trace",
  unavailable: "Unavailable",
  unsupported: "Unsupported",
  usart: "UART",
  "validated-procedure": "Validated Procedure",
  vcap: "Regulator Capacitor",
};

export function compatibilityKind(
  position: Pick<TargetDefinitionPosition, "silicon_class">,
): TargetCompatibilityKind {
  const mapping: Record<TargetSiliconClass, TargetCompatibilityKind> = {
    fixed_critical: "identical",
    stable_io: "identical",
    variant_io: "variant",
    partial: "partial",
    safety_collision: "conflict",
  };
  return mapping[position.silicon_class];
}

export function formatPercent(count: number, total: number): string {
  if (!total) return "0%";
  return `${Math.round((count / total) * 100)}%`;
}

export function formatToken(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return "Not Declared";
  const direct = TOKEN_LABELS[trimmed.toLowerCase()];
  if (direct) return direct;
  if (/^[A-Z][A-Z0-9_./+-]*$/.test(trimmed)) return trimmed;

  return trimmed
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .split(/\s+/)
    .map((word) => {
      const known = TOKEN_LABELS[word.toLowerCase()];
      if (known) return known;
      return word ? `${word[0].toUpperCase()}${word.slice(1)}` : word;
    })
    .join(" ");
}

export function formatElectricalIdentity(value: string): string {
  if (!value.includes(":")) return formatToken(value);
  return value
    .split(":")
    .map((part) => formatToken(part))
    .join(" · ");
}

export function sentenceCase(value: string): string {
  const normalized = value.trim();
  if (!normalized) return normalized;
  return `${normalized[0].toUpperCase()}${normalized.slice(1)}`;
}
