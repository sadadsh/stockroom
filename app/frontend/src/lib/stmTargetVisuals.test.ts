import { describe, expect, it } from "vitest";
import type { TargetDefinitionPosition } from "../api/types";
import {
  buildTargetLegend,
  targetLegendKey,
  targetMatchesLegend,
  targetPositionColor,
} from "./stmTargetVisuals";

function position(
  overrides: Partial<TargetDefinitionPosition>,
): TargetDefinitionPosition {
  return {
    position: "1",
    position_kind: "numeric",
    lqfp_side: "left",
    bga_row: null,
    bga_col: null,
    silicon_class: "stable_io",
    board_action: "direct",
    identities: ["PA0"],
    access_tags: [],
    access_tags_union: [],
    present_on: 3,
    total_targets: 3,
    route_ids: [],
    hazard: "",
    per_target: [
      {
        ref: "STM32A",
        family: "STM32TEST",
        canonical_pin_name: "PA0",
        electrical_class: "io",
        critical_identity: null,
        roles: [],
        functions: [],
        alternate_functions: [],
        access_tags: [],
      },
    ],
    ...overrides,
  };
}

describe("STM target visual model", () => {
  it("builds one complete compatibility distribution with exact percentages", () => {
    const positions = [
      position({ position: "1" }),
      position({ position: "2", silicon_class: "variant_io" }),
      position({
        position: "3",
        silicon_class: "safety_collision",
        board_action: "isolate",
      }),
      position({
        position: "4",
        silicon_class: "partial",
        board_action: "unsupported",
      }),
    ];

    const legend = buildTargetLegend(positions, "compatibility");
    expect(legend.map((entry) => [entry.key, entry.count, entry.percentage])).toEqual([
      ["identical", 1, 25],
      ["variant", 1, 25],
      ["partial", 1, 25],
      ["conflict", 1, 25],
    ]);
    expect(legend.reduce((sum, entry) => sum + entry.count, 0)).toBe(
      positions.length,
    );
  });

  it("uses the same registry for lens classification, color, and filtering", () => {
    const debug = position({
      access_tags_union: ["swdio", "usart"],
      route_ids: ["service_uart"],
    });
    const requiredRoute = position({
      position: "2",
      access_tags_union: ["usart"],
      route_ids: ["service_uart"],
    });
    const conflict = position({
      position: "3",
      silicon_class: "safety_collision",
      board_action: "isolate",
      universal_primitive: "conditioned-signal-with-selected-critical-role",
      per_target: [
        {
          ref: "STM32A",
          family: "STM32TEST",
          canonical_pin_name: "VSS",
          electrical_class: "ground",
          critical_identity: "ground",
          roles: [],
          functions: [],
          alternate_functions: [],
          access_tags: [],
        },
        {
          ref: "STM32B",
          family: "STM32TEST",
          canonical_pin_name: "VCAP_1",
          electrical_class: "vcap",
          critical_identity: "vcap",
          roles: [],
          functions: [],
          alternate_functions: [],
          access_tags: [],
        },
      ],
    });

    expect(targetLegendKey(debug, "access")).toBe("swdio");
    expect(targetLegendKey(requiredRoute, "access")).toBe("service");
    expect(targetLegendKey(conflict, "electrical")).toBe("mixed");
    expect(targetMatchesLegend(conflict, "electrical", "conflict")).toBe(true);
    expect(targetMatchesLegend(conflict, "electrical", "ground")).toBe(true);
    expect(targetMatchesLegend(conflict, "electrical", "vcap")).toBe(true);
    expect(targetLegendKey(conflict, "board")).toBe("compact-hybrid");
    expect(targetPositionColor(conflict, "electrical")).toBe(
      "var(--stm-classify-divergent)",
    );
    expect(targetPositionColor(conflict, "electrical", "ground")).toBe(
      "var(--stm-ground)",
    );
    expect(targetPositionColor(requiredRoute, "access")).toBe(
      "var(--stm-classify-shared)",
    );
  });

  it("keeps every supported category discoverable while filtering run-critical and access facts", () => {
    const digitalSupply = position({
      per_target: [
        {
          ref: "STM32A",
          family: "STM32TEST",
          canonical_pin_name: "VDD",
          electrical_class: "power",
          critical_identity: "power:vdd",
          roles: ["power_vdd"],
          functions: [],
          alternate_functions: [],
          access_tags: [],
        },
      ],
    });
    const resetAndDebug = position({
      position: "2",
      access_tags_union: ["reset", "swdio"],
      per_target: [
        {
          ref: "STM32A",
          family: "STM32TEST",
          canonical_pin_name: "NRST",
          electrical_class: "reset",
          critical_identity: "reset",
          roles: ["reset"],
          functions: [],
          alternate_functions: [],
          access_tags: ["reset", "swdio"],
        },
      ],
    });

    expect(targetMatchesLegend(digitalSupply, "foundation", "digital-supply")).toBe(
      true,
    );
    expect(targetMatchesLegend(digitalSupply, "electrical", "digital-power")).toBe(
      true,
    );
    expect(targetMatchesLegend(resetAndDebug, "foundation", "reset-control")).toBe(
      true,
    );
    expect(targetMatchesLegend(resetAndDebug, "access", "swdio")).toBe(true);
    expect(targetMatchesLegend(resetAndDebug, "access", "reset")).toBe(true);

    const accessCatalog = buildTargetLegend(
      [digitalSupply, resetAndDebug],
      "access",
      { includeEmpty: true },
    );
    expect(accessCatalog).toHaveLength(18);
    expect(accessCatalog.find((entry) => entry.key === "boot1")).toMatchObject({
      count: 0,
      percentage: 0,
    });
    expect(accessCatalog.find((entry) => entry.key === "swdio")).toMatchObject({
      count: 1,
      percentage: 50,
    });
  });
});
