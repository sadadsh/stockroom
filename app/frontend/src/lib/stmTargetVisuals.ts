import type { TargetDefinitionPosition } from "../api/types";
import {
  TARGET_COMPATIBILITY_INSIGHTS,
  compatibilityKind,
  formatElectricalIdentity,
  formatToken,
} from "./stmTargetInsights";

export type TargetMapLens =
  | "compatibility"
  | "foundation"
  | "electrical"
  | "access"
  | "board";

export interface TargetLegendSpec {
  key: string;
  label: string;
  shortLabel: string;
  token: string;
  description: string;
  group: string;
  basis: string;
}

export interface TargetLegendEntry extends TargetLegendSpec {
  count: number;
  percentage: number;
}

export const TARGET_LENSES: ReadonlyArray<{
  id: TargetMapLens;
  label: string;
}> = [
  { id: "compatibility", label: "Compatibility" },
  { id: "foundation", label: "Run Critical" },
  { id: "electrical", label: "Electrical Role" },
  { id: "access", label: "Service Access" },
  { id: "board", label: "Routing Plan" },
];

export const TARGET_LENS_GUIDANCE: Record<TargetMapLens, string> = {
  compatibility:
    "Shows whether one physical connection can work across every selected MCU.",
  foundation:
    "Shows every position involved in power-up, reset, clocking, or safe reserved-pin handling.",
  electrical:
    "Shows the electrical role occupying each physical package position.",
  access:
    "Shows positions involved in programming, debug, recovery, clocks, and service interfaces.",
  board:
    "Shows where routing is direct, passively compacted, fully exclusive, policy-defined, or unavailable.",
};

export function targetLegendIsExclusive(lens: TargetMapLens): boolean {
  return lens === "compatibility" || lens === "board";
}

const COMPATIBILITY_SPECS: TargetLegendSpec[] = [
  "identical",
  "variant",
  "partial",
  "conflict",
].map((kind) => {
  const insight =
    TARGET_COMPATIBILITY_INSIGHTS[
      kind as keyof typeof TARGET_COMPATIBILITY_INSIGHTS
    ];
  return {
    key: kind,
    label: insight.label,
    shortLabel: insight.shortLabel,
    token: insight.token,
    description: insight.consequence,
    group: "Package Compatibility",
    basis:
      "One physical package position compared across every selected MCU.",
  };
});

const FOUNDATION_SPECS: TargetLegendSpec[] = [
  {
    key: "digital-supply",
    label: "Digital Supply",
    shortLabel: "VDD",
    token: "var(--stm-power)",
    description:
      "Every VDD position must be biased within the selected MCU limits and locally decoupled.",
    group: "Power",
    basis: "Normalized critical identity power:vdd.",
  },
  {
    key: "analog-supply",
    label: "Analog Supply",
    shortLabel: "VDDA",
    token: "var(--stm-analog)",
    description:
      "VDDA positions need the documented bias, filtering, and relationship to the digital supply.",
    group: "Power",
    basis: "Normalized critical identity power:vdda.",
  },
  {
    key: "backup-supply",
    label: "Backup Supply",
    shortLabel: "VBAT",
    token: "var(--stm-boot)",
    description:
      "VBAT needs a valid bias or the documented tie when no independent backup source is used.",
    group: "Power",
    basis: "Normalized critical identity power:vbat.",
  },
  {
    key: "analog-reference",
    label: "Analog Reference",
    shortLabel: "VREF",
    token: "var(--stm-vcap)",
    description:
      "Reference positions need the exact documented bias and decoupling for every selected MCU that exposes them.",
    group: "Power",
    basis: "Normalized power identity beginning with power:vref.",
  },
  {
    key: "special-supply",
    label: "Special Supply Or Power Control",
    shortLabel: "Special Power",
    token: "var(--stm-classify-divergent)",
    description:
      "USB, I/O-domain, DSI, regulator-bypass, supervisor, and other special power pins require target-specific implementation evidence.",
    group: "Power",
    basis:
      "All remaining normalized power, power-control, and regulator-control identities.",
  },
  {
    key: "ground-return",
    label: "Ground Returns",
    shortLabel: "Ground",
    token: "var(--stm-ground)",
    description:
      "Every digital and analog ground return must reach the intended low-impedance domain.",
    group: "Returns",
    basis: "Normalized critical identity ground.",
  },
  {
    key: "core-regulator",
    label: "Core Regulator",
    shortLabel: "VCAP",
    token: "var(--stm-vcap)",
    description:
      "VCAP and internal-regulator positions require the exact capacitor network and must not be externally loaded.",
    group: "Regulation",
    basis: "Normalized critical identity vcap.",
  },
  {
    key: "reset-control",
    label: "Reset Control",
    shortLabel: "NRST",
    token: "var(--stm-reset)",
    description:
      "Reset must have a valid default state and remain reachable for power-up, programming, and recovery.",
    group: "Start And Recover",
    basis: "Normalized critical identity reset or the reset access classifier.",
  },
  {
    key: "boot-control",
    label: "Boot Configuration",
    shortLabel: "Boot",
    token: "var(--stm-boot)",
    description:
      "Every exposed boot strap needs a deterministic target-correct default and an intentional access path.",
    group: "Start And Recover",
    basis: "Normalized critical identity boot or BOOT0/BOOT1 access tags.",
  },
  {
    key: "high-speed-clock",
    label: "High-Speed External Clock",
    shortLabel: "HSE",
    token: "var(--stm-oscillator)",
    description:
      "HSE oscillator positions must remain electrically suitable when the design policy uses an external high-speed clock.",
    group: "Clocking",
    basis: "OSC access tag derived from pin names, functions, and alternate functions.",
  },
  {
    key: "low-speed-clock",
    label: "Low-Speed External Clock",
    shortLabel: "LSE",
    token: "var(--stm-debug)",
    description:
      "LSE oscillator positions must remain electrically suitable when the design policy uses a 32 kHz clock.",
    group: "Clocking",
    basis: "OSC32 access tag derived from pin names, functions, and alternate functions.",
  },
  {
    key: "reserved-no-connect",
    label: "Reserved Or No Connect",
    shortLabel: "NC / RFU",
    token: "var(--stm-nc)",
    description:
      "Reserved, RFU, and no-connect positions stay isolated unless exact target documentation explicitly permits a connection.",
    group: "Safety",
    basis: "Normalized no-connect identity, including NC, RFU, and Reserved names.",
  },
  {
    key: "not-foundation",
    label: "No Run-Critical Obligation",
    shortLabel: "Other",
    token: "var(--c-line2)",
    description:
      "No power-up, reset, clock, regulator, or reserved-pin obligation is classified at this position.",
    group: "Other",
    basis: "Position does not match another run-critical category.",
  },
];

const ELECTRICAL_SPECS: TargetLegendSpec[] = [
  {
    key: "io",
    label: "GPIO / I/O",
    shortLabel: "GPIO",
    token: "var(--stm-gpio)",
    description:
      "General-purpose digital positions. Use the compatibility view before assigning a universal signal.",
    group: "Signals",
    basis: "CubeMX electrical class I/O.",
  },
  {
    key: "digital-power",
    label: "Digital Power",
    shortLabel: "VDD",
    token: "var(--stm-power)",
    description:
      "Primary digital supply positions required by at least one selected MCU.",
    group: "Supplies",
    basis: "Normalized critical identity power:vdd.",
  },
  {
    key: "analog-power",
    label: "Analog Power",
    shortLabel: "VDDA",
    token: "var(--stm-analog)",
    description:
      "Analog supply positions that must follow the selected MCU power-domain rules.",
    group: "Supplies",
    basis: "Normalized critical identity power:vdda.",
  },
  {
    key: "backup-power",
    label: "Backup Power",
    shortLabel: "VBAT",
    token: "var(--stm-boot)",
    description:
      "Backup-domain supply positions used by RTC and retained-domain functions.",
    group: "Supplies",
    basis: "Normalized critical identity power:vbat.",
  },
  {
    key: "reference-power",
    label: "Analog Reference",
    shortLabel: "VREF",
    token: "var(--stm-vcap)",
    description:
      "Analog reference supply or return positions.",
    group: "Supplies",
    basis: "Normalized power identity beginning with power:vref.",
  },
  {
    key: "special-power",
    label: "Special Power Domain",
    shortLabel: "Special",
    token: "var(--stm-classify-divergent)",
    description:
      "A supply or power-control role outside the primary VDD, VDDA, VBAT, and VREF domains.",
    group: "Supplies",
    basis:
      "Remaining power, power-control, or regulator-control critical identities.",
  },
  {
    key: "ground",
    label: "Ground",
    shortLabel: "Ground",
    token: "var(--stm-ground)",
    description:
      "Ground-return positions that must be bonded to the correct electrical domain.",
    group: "Returns",
    basis: "CubeMX ground class or normalized ground identity.",
  },
  {
    key: "reset",
    label: "Reset",
    shortLabel: "Reset",
    token: "var(--stm-reset)",
    description:
      "Reset and reset-adjacent control positions needed for reliable startup and recovery.",
    group: "Controls",
    basis: "CubeMX reset class or normalized reset identity.",
  },
  {
    key: "boot",
    label: "Boot Control",
    shortLabel: "Boot",
    token: "var(--stm-boot)",
    description:
      "Boot-mode control positions whose default state and service access must be deliberate.",
    group: "Controls",
    basis: "CubeMX boot class or normalized boot identity.",
  },
  {
    key: "vcap",
    label: "Regulator",
    shortLabel: "Regulator",
    token: "var(--stm-vcap)",
    description:
      "Internal-regulator capacitor or regulator-control positions with device-specific obligations.",
    group: "Regulation",
    basis: "CubeMX VCAP class or normalized vcap identity.",
  },
  {
    key: "nc",
    label: "No Connect",
    shortLabel: "No Connect",
    token: "var(--stm-nc)",
    description:
      "Reserved or no-connect positions. Keep them electrically isolated.",
    group: "Reserved",
    basis: "CubeMX NC class or normalized no-connect identity.",
  },
  {
    key: "mixed",
    label: "Mixed Electrical Roles",
    shortLabel: "Mixed Roles",
    token: "var(--stm-classify-divergent)",
    description:
      "Selected MCUs expose different non-critical electrical classes at this position.",
    group: "Cross-MCU",
    basis: "More than one normalized electrical category occupies the position.",
  },
  {
    key: "conflict",
    label: "Electrical Conflict",
    shortLabel: "Conflict",
    token: "var(--c-err)",
    description:
      "Fixed electrical identities disagree. A direct universal connection is unsafe.",
    group: "Cross-MCU",
    basis: "Compiler silicon class safety_collision.",
  },
  {
    key: "unknown",
    label: "Unknown Role",
    shortLabel: "Unknown",
    token: "var(--c-line2)",
    description:
      "The silicon source did not provide a recognized electrical classification.",
    group: "Unknown",
    basis: "Unrecognized or missing source electrical class.",
  },
];

const ACCESS_SPECS: TargetLegendSpec[] = [
  {
    key: "swdio",
    label: "SWD Data",
    shortLabel: "SWDIO",
    token: "var(--stm-debug)",
    description:
      "Serial Wire Debug data access for programming, identification, and interactive debug.",
    group: "Core Debug",
    basis: "SWDIO or JTMS capability found in pin names and functions.",
  },
  {
    key: "swclk",
    label: "SWD Clock",
    shortLabel: "SWCLK",
    token: "var(--stm-debug)",
    description:
      "Serial Wire Debug clock access required alongside SWDIO.",
    group: "Core Debug",
    basis: "SWCLK or JTCK capability found in pin names and functions.",
  },
  {
    key: "swo",
    label: "Serial Wire Output",
    shortLabel: "SWO",
    token: "var(--stm-classify-shared)",
    description:
      "Optional single-wire trace and instrumentation output.",
    group: "Core Debug",
    basis: "SWO or JTDO capability found in pin names and functions.",
  },
  {
    key: "jtag",
    label: "JTAG",
    shortLabel: "JTAG",
    token: "var(--stm-boot)",
    description:
      "JTAG programming, debug, and boundary-scan capability, including shared SWD pins.",
    group: "Extended Debug",
    basis: "JTAG, JTDI, JTDO, JTMS, JTCK, or NJTRST capability.",
  },
  {
    key: "trace",
    label: "Parallel Trace",
    shortLabel: "Trace",
    token: "var(--stm-vcap)",
    description:
      "Parallel trace clock and data capability for high-bandwidth instruction or data tracing.",
    group: "Extended Debug",
    basis: "TRACE capability found in pin names and functions.",
  },
  {
    key: "reset",
    label: "Reset Access",
    shortLabel: "Reset",
    token: "var(--stm-reset)",
    description:
      "Reset control can be exposed here for programming or recovery.",
    group: "Recover",
    basis: "NRST or reset capability.",
  },
  {
    key: "boot0",
    label: "Boot 0 Control",
    shortLabel: "BOOT0",
    token: "var(--stm-boot)",
    description:
      "Primary boot-source selection strap used for recovery and alternate boot modes.",
    group: "Recover",
    basis: "BOOT0 capability.",
  },
  {
    key: "boot1",
    label: "Boot 1 Control",
    shortLabel: "BOOT1",
    token: "var(--stm-boot)",
    description:
      "Secondary boot-mode control where the selected MCU exposes it.",
    group: "Recover",
    basis: "BOOT1 capability.",
  },
  {
    key: "osc",
    label: "High-Speed Clock Access",
    shortLabel: "HSE",
    token: "var(--stm-oscillator)",
    description:
      "External high-speed oscillator or clock input/output capability.",
    group: "Clocking",
    basis: "OSC capability excluding OSC32.",
  },
  {
    key: "osc32",
    label: "Low-Speed Clock Access",
    shortLabel: "LSE",
    token: "var(--stm-oscillator)",
    description:
      "External 32 kHz oscillator or low-speed clock input/output capability.",
    group: "Clocking",
    basis: "OSC32 capability.",
  },
  {
    key: "usb",
    label: "USB",
    shortLabel: "USB",
    token: "var(--stm-gpio)",
    description:
      "USB device, host, or OTG signal capability that can support communication or recovery.",
    group: "Communication And Extraction",
    basis: "USB capability found in pin functions.",
  },
  {
    key: "usart",
    label: "UART / USART",
    shortLabel: "UART",
    token: "var(--stm-gpio)",
    description:
      "Asynchronous serial capability commonly used for consoles, recovery, and data extraction.",
    group: "Communication And Extraction",
    basis: "USART or UART capability found in pin functions.",
  },
  {
    key: "can",
    label: "CAN / FDCAN",
    shortLabel: "CAN",
    token: "var(--stm-gpio)",
    description:
      "CAN or FDCAN capability for robust external communication and diagnostics.",
    group: "Communication And Extraction",
    basis: "CAN or FDCAN capability found in pin functions.",
  },
  {
    key: "i2c",
    label: "I2C",
    shortLabel: "I2C",
    token: "var(--stm-gpio)",
    description:
      "Two-wire serial capability for peripherals, identification devices, and service access.",
    group: "Communication And Extraction",
    basis: "I2C capability found in pin functions.",
  },
  {
    key: "spi",
    label: "SPI / I2S",
    shortLabel: "SPI",
    token: "var(--stm-gpio)",
    description:
      "Synchronous serial capability for high-rate peripherals, programming, or extraction paths.",
    group: "Communication And Extraction",
    basis: "SPI capability found in pin functions.",
  },
  {
    key: "analog",
    label: "Analog Access",
    shortLabel: "Analog",
    token: "var(--stm-analog)",
    description:
      "Analog measurement or injection capability is present.",
    group: "Observe And Stimulate",
    basis: "ADC, DAC, comparator, or op-amp capability.",
  },
  {
    key: "service",
    label: "Required Service Route",
    shortLabel: "Required Route",
    token: "var(--stm-classify-shared)",
    description:
      "The active policy assigns at least one required debug, recovery, or service route here.",
    group: "Selected Plan",
    basis: "One or more compiled policy route IDs use this package position.",
  },
  {
    key: "none",
    label: "No Declared Access",
    shortLabel: "No Access",
    token: "var(--c-line2)",
    description:
      "No programming, recovery, extraction, or service role is declared at this position.",
    group: "Other",
    basis: "No recognized access tag and no compiled policy route.",
  },
];

const BOARD_SPECS: TargetLegendSpec[] = [
  {
    key: "direct-or-fixed",
    label: "Direct Or Fixed",
    shortLabel: "Direct / Fixed",
    token: "var(--stm-classify-shared)",
    description:
      "No active routing adaptation is suggested. The position is fixed, directly usable, passively broken out, or deliberately left open.",
    group: "Universal Routing Topology",
    basis: "Compiler universal primitive has no active target-selected path.",
  },
  {
    key: "compact-hybrid",
    label: "Compact Hybrid",
    shortLabel: "Compact Hybrid",
    token: "var(--stm-classify-divergent)",
    description:
      "One common signal path uses validated passive conditioning while only the conflicting critical role is actively selected.",
    group: "Universal Routing Topology",
    basis:
      "Compiler primitive conditioned-signal-with-selected-critical-role.",
  },
  {
    key: "fully-exclusive",
    label: "Fully Exclusive",
    shortLabel: "Fully Exclusive",
    token: "var(--c-err)",
    description:
      "Every conductive role needs its own target-selected path because a generally safe passive compaction was not found.",
    group: "Universal Routing Topology",
    basis: "Compiler primitive exclusive-identity-branches.",
  },
  {
    key: "policy-defined",
    label: "Policy Defined",
    shortLabel: "Policy Defined",
    token: "var(--c-acc)",
    description:
      "The caller supplied an evidenced mix of selectable, passive, direct, or isolated branches.",
    group: "Universal Routing Topology",
    basis: "Compiler primitive declared-identity-branches.",
  },
  {
    key: "excluded",
    label: "Excluded From Common Interface",
    shortLabel: "Excluded",
    token: "var(--stm-classify-partial)",
    description:
      "The universal interface cannot depend on this position because it is absent from part of the target set.",
    group: "Universal Routing Topology",
    basis: "Compiler primitive exclude-from-common-interface.",
  },
];

const SPECS: Record<TargetMapLens, TargetLegendSpec[]> = {
  compatibility: COMPATIBILITY_SPECS,
  foundation: FOUNDATION_SPECS,
  electrical: ELECTRICAL_SPECS,
  access: ACCESS_SPECS,
  board: BOARD_SPECS,
};

function normalizedElectricalKeys(
  position: TargetDefinitionPosition,
): Set<string> {
  const keys = new Set<string>();
  for (const target of position.per_target) {
    const identity = (target.critical_identity ?? "").toLowerCase();
    const electrical = target.electrical_class.toLowerCase();
    if (electrical === "io" && !identity) keys.add("io");
    else if (identity === "power:vdd") keys.add("digital-power");
    else if (identity === "power:vdda") keys.add("analog-power");
    else if (identity === "power:vbat") keys.add("backup-power");
    else if (identity.startsWith("power:vref")) keys.add("reference-power");
    else if (
      identity.startsWith("power:") ||
      identity.startsWith("power-control:") ||
      identity.startsWith("regulator-control:")
    ) {
      keys.add("special-power");
    } else if (identity === "ground" || electrical === "ground") {
      keys.add("ground");
    } else if (identity === "reset" || electrical === "reset") {
      keys.add("reset");
    } else if (identity === "boot" || electrical === "boot") {
      keys.add("boot");
    } else if (identity === "vcap" || electrical === "vcap") {
      keys.add("vcap");
    } else if (identity === "no-connect" || electrical === "nc") {
      keys.add("nc");
    } else {
      keys.add("unknown");
    }
  }
  return keys;
}

function foundationKeys(position: TargetDefinitionPosition): Set<string> {
  const identities = new Set(
    position.per_target
      .map((target) => (target.critical_identity ?? "").toLowerCase())
      .filter(Boolean),
  );
  const tags = new Set(
    position.access_tags_union.map((tag) => tag.toLowerCase()),
  );
  const keys = new Set<string>();

  if (identities.has("power:vdd")) keys.add("digital-supply");
  if (identities.has("power:vdda")) keys.add("analog-supply");
  if (identities.has("power:vbat")) keys.add("backup-supply");
  if ([...identities].some((identity) => identity.startsWith("power:vref"))) {
    keys.add("analog-reference");
  }
  if (
    [...identities].some(
      (identity) =>
        (identity.startsWith("power:") &&
          !["power:vdd", "power:vdda", "power:vbat"].includes(identity) &&
          !identity.startsWith("power:vref")) ||
        identity.startsWith("power-control:") ||
        identity.startsWith("regulator-control:"),
    )
  ) {
    keys.add("special-supply");
  }
  if (identities.has("ground")) keys.add("ground-return");
  if (identities.has("vcap")) keys.add("core-regulator");
  if (identities.has("reset") || tags.has("reset")) keys.add("reset-control");
  if (
    identities.has("boot") ||
    tags.has("boot0") ||
    tags.has("boot1")
  ) {
    keys.add("boot-control");
  }
  if (tags.has("osc")) keys.add("high-speed-clock");
  if (tags.has("osc32")) keys.add("low-speed-clock");
  if (identities.has("no-connect")) keys.add("reserved-no-connect");
  if (!keys.size) keys.add("not-foundation");
  return keys;
}

export function targetLegendKey(
  position: TargetDefinitionPosition,
  lens: TargetMapLens,
): string {
  if (lens === "compatibility") return compatibilityKind(position);
  if (lens === "board") {
    switch (position.universal_primitive) {
      case "conditioned-signal-with-selected-critical-role":
        return "compact-hybrid";
      case "exclusive-identity-branches":
        return "fully-exclusive";
      case "declared-identity-branches":
        return "policy-defined";
      case "exclude-from-common-interface":
        return "excluded";
      case "fixed-network":
      case "leave-open":
      case "universal-breakout":
      case "firmware-mapped-breakout":
        return "direct-or-fixed";
      default:
        if (position.board_action === "unsupported") return "excluded";
        if (
          position.board_action === "selectable" ||
          position.board_action === "switched"
        ) {
          return "fully-exclusive";
        }
        return "direct-or-fixed";
    }
  }
  if (lens === "foundation") {
    return [...foundationKeys(position)][0] ?? "not-foundation";
  }
  if (lens === "access") {
    const tags = new Set(
      position.access_tags_union.map((tag) => tag.toLowerCase()),
    );
    if (tags.has("swdio")) return "swdio";
    if (tags.has("swclk")) return "swclk";
    if (tags.has("swo")) return "swo";
    if (tags.has("jtag")) return "jtag";
    if (tags.has("trace")) return "trace";
    if (tags.has("reset")) return "reset";
    if (tags.has("boot0")) return "boot0";
    if (tags.has("boot1")) return "boot1";
    if (tags.has("osc")) return "osc";
    if (tags.has("osc32")) return "osc32";
    if (position.route_ids.length) return "service";
    if (tags.has("analog")) return "analog";
    for (const tag of ["usb", "usart", "can", "i2c", "spi"]) {
      if (tags.has(tag)) return tag;
    }
    return "none";
  }

  const keys = normalizedElectricalKeys(position);
  if (keys.size > 1) return "mixed";
  return [...keys][0] ?? "unknown";
}

export function targetMatchesLegend(
  position: TargetDefinitionPosition,
  lens: TargetMapLens,
  key: string,
): boolean {
  if (targetLegendIsExclusive(lens)) {
    return targetLegendKey(position, lens) === key;
  }

  if (lens === "foundation") {
    return foundationKeys(position).has(key);
  }

  if (lens === "electrical") {
    const keys = normalizedElectricalKeys(position);
    if (key === "conflict") {
      return position.silicon_class === "safety_collision";
    }
    if (key === "mixed") return keys.size > 1;
    return keys.has(key);
  }

  const tags = new Set(
    position.access_tags_union.map((tag) => tag.toLowerCase()),
  );
  if (key === "service") return position.route_ids.length > 0;
  if (
    [
      "swdio",
      "swclk",
      "swo",
      "jtag",
      "trace",
      "reset",
      "boot0",
      "boot1",
      "osc",
      "osc32",
      "usb",
      "usart",
      "can",
      "i2c",
      "spi",
      "analog",
    ].includes(key)
  ) {
    return tags.has(key);
  }
  if (key === "none") {
    return tags.size === 0 && position.route_ids.length === 0;
  }
  return false;
}

export function buildTargetLegend(
  positions: TargetDefinitionPosition[],
  lens: TargetMapLens,
  options: { includeEmpty?: boolean } = {},
): TargetLegendEntry[] {
  const total = positions.length;
  const entries = SPECS[lens]
    .map((spec) => {
      const count = positions.filter((position) =>
        targetMatchesLegend(position, lens, spec.key),
      ).length;
      return {
        ...spec,
        count,
        percentage: total ? (count / total) * 100 : 0,
      };
    });
  return options.includeEmpty
    ? entries
    : entries.filter((item) => item.count > 0);
}

export function targetLegendSpec(
  lens: TargetMapLens,
  key: string,
): TargetLegendSpec | null {
  return SPECS[lens].find((item) => item.key === key) ?? null;
}

export function targetPositionColor(
  position: TargetDefinitionPosition,
  lens: TargetMapLens,
  activeKey?: string | null,
): string {
  if (
    activeKey &&
    targetMatchesLegend(position, lens, activeKey)
  ) {
    return targetLegendSpec(lens, activeKey)?.token ?? "var(--c-line2)";
  }
  const key = targetLegendKey(position, lens);
  return targetLegendSpec(lens, key)?.token ?? "var(--c-line2)";
}

export function targetPositionDescription(
  position: TargetDefinitionPosition,
  lens: TargetMapLens,
): string {
  if (lens === "electrical") {
    return (
      position.identities.map(formatElectricalIdentity).join(", ") ||
      targetLegendSpec(lens, targetLegendKey(position, lens))?.label ||
      "Unknown Electrical Role"
    );
  }
  if (lens === "access" && position.access_tags_union.length) {
    return position.access_tags_union.map(formatToken).join(", ");
  }
  return (
    targetLegendSpec(lens, targetLegendKey(position, lens))?.label ??
    "Unknown Position"
  );
}
