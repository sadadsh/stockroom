import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { cloneCoreBringUpPolicy, TargetPolicyEditor } from "./TargetPolicyEditor";

describe("TargetPolicyEditor", () => {
  it("applies a generic edited policy without hidden hardware defaults", () => {
    const onChange = vi.fn();
    render(
      <TargetPolicyEditor policy={cloneCoreBringUpPolicy()} onPolicyChange={onChange} />,
    );
    fireEvent.click(screen.getByText("Definition Policy"));
    const textarea = screen.getByLabelText("Target Definition Policy JSON");
    const edited = cloneCoreBringUpPolicy();
    edited.id = "fixture-policy";
    fireEvent.change(textarea, { target: { value: JSON.stringify(edited) } });
    fireEvent.click(screen.getByRole("button", { name: "Apply Policy" }));
    expect(onChange).toHaveBeenCalledWith(edited);
    const value = (textarea as HTMLTextAreaElement).value;
    expect(value).not.toContain("part_mpn");
    expect(value).not.toContain("channel_fabric");
    expect(value).toContain("routing_constraints");
  });

  it("keeps an invalid policy local and explains the parse failure", () => {
    const onChange = vi.fn();
    render(
      <TargetPolicyEditor policy={cloneCoreBringUpPolicy()} onPolicyChange={onChange} />,
    );
    fireEvent.click(screen.getByText("Definition Policy"));
    fireEvent.change(screen.getByLabelText("Target Definition Policy JSON"), {
      target: { value: "{" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply Policy" }));
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByText(/Expected property name|invalid/i)).toBeInTheDocument();
  });
});
