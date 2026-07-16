import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { SegmentedControl } from "./primitives";

const OPTIONS = [
  { id: "a", label: "Doctor" },
  { id: "b", label: "Duplicates" },
] as const;

// A tiny controlled host so keyboard navigation actually moves the selection
// (a radiogroup follows focus, so tabIndex only shifts once value updates).
function Host({ onChange }: { onChange?: (id: "a" | "b") => void }) {
  const [value, setValue] = useState<"a" | "b">("a");
  return (
    <SegmentedControl
      options={OPTIONS}
      value={value}
      onChange={(id) => {
        setValue(id);
        onChange?.(id);
      }}
      aria-label="View"
    />
  );
}

describe("SegmentedControl", () => {
  it("is a radiogroup with one checked option, not a tablist", () => {
    render(<Host />);
    const group = screen.getByRole("radiogroup", { name: "View" });
    expect(group).toBeInTheDocument();
    // It must not masquerade as the tablist primitive.
    expect(screen.queryByRole("tablist")).toBeNull();
    expect(screen.getByRole("radio", { name: "Doctor" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getByRole("radio", { name: "Duplicates" })).toHaveAttribute(
      "aria-checked",
      "false",
    );
  });

  it("selects an option on click", async () => {
    const onChange = vi.fn();
    render(<Host onChange={onChange} />);
    await userEvent.click(screen.getByRole("radio", { name: "Duplicates" }));
    expect(onChange).toHaveBeenCalledWith("b");
    expect(screen.getByRole("radio", { name: "Duplicates" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("moves the selection with the arrow keys (roving tabindex)", async () => {
    const onChange = vi.fn();
    render(<Host onChange={onChange} />);
    const user = userEvent.setup();
    const first = screen.getByRole("radio", { name: "Doctor" });
    // Only the checked option is in the tab order.
    expect(first).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("radio", { name: "Duplicates" })).toHaveAttribute(
      "tabindex",
      "-1",
    );
    first.focus();
    await user.keyboard("{ArrowRight}");
    expect(onChange).toHaveBeenLastCalledWith("b");
    // Wraps around from the last option.
    await user.keyboard("{ArrowRight}");
    expect(onChange).toHaveBeenLastCalledWith("a");
  });

  it("jumps to the first and last option with Home and End", async () => {
    const onChange = vi.fn();
    render(<Host onChange={onChange} />);
    const user = userEvent.setup();
    screen.getByRole("radio", { name: "Doctor" }).focus();
    await user.keyboard("{End}");
    expect(onChange).toHaveBeenLastCalledWith("b");
    await user.keyboard("{Home}");
    expect(onChange).toHaveBeenLastCalledWith("a");
  });
});
