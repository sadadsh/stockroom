import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FamilyPicker } from "./FamilyPicker";
import type { StmScope } from "../../pages/StmViewerPage";

vi.mock("../../api/stmQueries", () => ({ useStmFamilies: vi.fn() }));
import { useStmFamilies } from "../../api/stmQueries";
const mockFamilies = vi.mocked(useStmFamilies);

const EMPTY: StmScope = { families: [], mcus: [] };

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function fam(over: Record<string, unknown>): any {
  return { data: undefined, isLoading: false, isError: false, ...over };
}

beforeEach(() => vi.clearAllMocks());

describe("FamilyPicker", () => {
  it("renders the families with their counts", () => {
    mockFamilies.mockReturnValue(
      fam({
        data: {
          families: [
            { family: "STM32F4", lines: ["STM32F407"], mcu_count: 168, packages: [] },
            { family: "STM32H7", lines: [], mcu_count: 40, packages: [] },
          ],
        },
      }),
    );
    render(<FamilyPicker scope={EMPTY} onScopeChange={vi.fn()} />);

    expect(screen.getByText("STM32F4")).toBeInTheDocument();
    expect(screen.getByText("168")).toBeInTheDocument();
    expect(screen.getByText("STM32H7")).toBeInTheDocument();
    expect(screen.getByText("40")).toBeInTheDocument();
  });

  it("toggling a family emits the updated scope with no network request", async () => {
    mockFamilies.mockReturnValue(
      fam({
        data: {
          families: [{ family: "STM32F4", lines: [], mcu_count: 168, packages: [] }],
        },
      }),
    );
    const onScopeChange = vi.fn();
    render(<FamilyPicker scope={EMPTY} onScopeChange={onScopeChange} />);

    await userEvent.click(screen.getByText("STM32F4"));

    expect(onScopeChange).toHaveBeenCalledWith({ families: ["STM32F4"], mcus: [] });
    // useStmFamilies is the only data hook; no matrix fetch is issued here (decision 3)
  });

  it("expanding a family reveals its lines and selecting one scopes into scope.mcus", async () => {
    mockFamilies.mockReturnValue(
      fam({
        data: {
          families: [
            { family: "STM32F4", lines: ["STM32F407", "STM32F429"], mcu_count: 168, packages: [] },
          ],
        },
      }),
    );
    const onScopeChange = vi.fn();
    render(<FamilyPicker scope={EMPTY} onScopeChange={onScopeChange} />);

    await userEvent.click(screen.getByRole("button", { name: "Expand STM32F4" }));
    await userEvent.click(screen.getByText("STM32F429"));

    expect(onScopeChange).toHaveBeenCalledWith({ families: [], mcus: ["STM32F429"] });
  });

  it("renders the loading and error branches without throwing", () => {
    mockFamilies.mockReturnValue(fam({ isLoading: true }));
    const { rerender } = render(<FamilyPicker scope={EMPTY} onScopeChange={vi.fn()} />);
    expect(screen.getByText("Loading families...")).toBeInTheDocument();

    mockFamilies.mockReturnValue(fam({ isError: true }));
    rerender(<FamilyPicker scope={EMPTY} onScopeChange={vi.fn()} />);
    expect(screen.getByText("Could not load families.")).toBeInTheDocument();
  });
});
