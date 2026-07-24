import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { CompatVerdictBanner } from "./CompatVerdictBanner";
import type { UnionDTO } from "../../api/types";

type Verdict = UnionDTO["verdict"];

describe("CompatVerdictBanner", () => {
  it("reads Interchangeable with the swaps_required count in the ok tone", () => {
    render(<CompatVerdictBanner verdict={{ interchangeable: true, swaps_required: 3, blocking: [] }} />);
    const headline = screen.getByText("Interchangeable with 3 swaps");
    expect(headline).toBeInTheDocument();
    expect(headline.className).toContain("text-ok");
    // no blocking list when the set is interchangeable
    expect(screen.queryByTestId("compat-blocking")).toBeNull();
  });

  it("singularizes a one-swap verdict", () => {
    render(<CompatVerdictBanner verdict={{ interchangeable: true, swaps_required: 1, blocking: [] }} />);
    expect(screen.getByText("Interchangeable with 1 swap")).toBeInTheDocument();
  });

  it("reads Incompatible in the err tone and lists each blocking entry's signal and reason", () => {
    const verdict: Verdict = {
      interchangeable: false,
      swaps_required: 0,
      blocking: [
        {
          position: "23",
          signal: "USART2_TX",
          reason: "No alternate-function route places this signal on every part.",
        },
      ],
    };
    render(<CompatVerdictBanner verdict={verdict} />);
    const headline = screen.getByText("Incompatible");
    expect(headline.className).toContain("text-err");
    // the blocking entry's signal + reason both render beneath the verdict
    expect(screen.getByTestId("compat-blocking")).toBeInTheDocument();
    expect(screen.getByText("USART2_TX")).toBeInTheDocument();
    expect(
      screen.getByText(/No alternate-function route places this signal/),
    ).toBeInTheDocument();
  });
});
