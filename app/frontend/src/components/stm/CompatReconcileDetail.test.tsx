import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { CompatReconcileDetail } from "./CompatReconcileDetail";
import type { UnionPositionDTO } from "../../api/types";

function pos(over: Partial<UnionPositionDTO>): UnionPositionDTO {
  return {
    position: "23",
    position_kind: "numeric",
    lqfp_side: "left",
    bga_row: null,
    bga_col: null,
    classification: "divergent",
    present_on: 2,
    total: 2,
    per_part: [
      { ref: "STM32F407VE", canonical_pin_name: "PA0", roles: ["gpio"], functions: ["USART2_CTS"] },
      { ref: "STM32F407VG", canonical_pin_name: "PA0", roles: ["gpio"], functions: ["TIM2_CH1"] },
    ],
    reconcile: null,
    ...over,
  };
}

describe("CompatReconcileDetail", () => {
  it("lists the swaps that reconcile a divergent position (ref carries the target signal via its AF index)", () => {
    render(
      <CompatReconcileDetail
        position={pos({
          reconcile: {
            swappable: true,
            swaps: [
              { ref: "STM32F407VE", target_signal: "USART2_TX", via_af_index: 7 },
              { ref: "STM32F407VG", target_signal: "USART2_TX", via_af_index: 7 },
            ],
            reason: null,
          },
        })}
      />,
    );
    expect(screen.getByText("Reconciling Swaps")).toBeInTheDocument();
    expect(screen.getAllByText("USART2_TX").length).toBe(2);
    expect(screen.getAllByText("AF7").length).toBe(2);
    // the per-part audit trail is always present so the classification is auditable
    expect(screen.getByTestId("compat-per-part")).toBeInTheDocument();
    expect(screen.getByText(/USART2_CTS/)).toBeInTheDocument();
  });

  it("shows the un-swappable reason as sentence-case prose with the err tone", () => {
    render(
      <CompatReconcileDetail
        position={pos({
          reconcile: {
            swappable: false,
            swaps: [],
            reason: "USART2_TX has no alternate-function route to this position on STM32F407VG.",
          },
        })}
      />,
    );
    expect(screen.getByText("Un-Swappable")).toBeInTheDocument();
    expect(
      screen.getByText(/no alternate-function route to this position/),
    ).toBeInTheDocument();
    // never renders a swap list in the un-swappable branch
    expect(screen.queryByText("Reconciling Swaps")).toBeNull();
  });

  it("still renders the per-part trail for a position with no reconcile block", () => {
    render(<CompatReconcileDetail position={pos({ classification: "partial", reconcile: null })} />);
    expect(screen.getByTestId("compat-per-part")).toBeInTheDocument();
    expect(screen.queryByText("Reconciling Swaps")).toBeNull();
    expect(screen.queryByText("Un-Swappable")).toBeNull();
  });
});
