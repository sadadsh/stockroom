import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { EditableText } from "./EditableText";

describe("EditableText", () => {
  it("saves a changed value on Enter", async () => {
    const onSave = vi.fn();
    render(<EditableText value="Old" onSave={onSave} label="Manufacturer" />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Edit Manufacturer" }));
    const input = screen.getByLabelText("Manufacturer");
    await user.clear(input);
    await user.type(input, "New");
    await user.keyboard("{Enter}");

    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave).toHaveBeenCalledWith("New");
  });

  it("cancels on Escape without saving and restores the value", async () => {
    const onSave = vi.fn();
    render(<EditableText value="Old" onSave={onSave} label="Manufacturer" />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Edit Manufacturer" }));
    const input = screen.getByLabelText("Manufacturer");
    await user.clear(input);
    await user.type(input, "New");
    await user.keyboard("{Escape}");

    expect(onSave).not.toHaveBeenCalled();
    expect(screen.getByText("Old")).toBeInTheDocument();
  });

  it("does not fire onSave for a no-op edit", async () => {
    const onSave = vi.fn();
    render(<EditableText value="Same" onSave={onSave} label="Field" />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Edit Field" }));
    await user.keyboard("{Enter}");

    expect(onSave).not.toHaveBeenCalled();
  });

  it("shows a fillable placeholder when empty", () => {
    render(
      <EditableText value="" onSave={vi.fn()} label="Tags" placeholder="Add Tags" />,
    );
    expect(screen.getByText("Add Tags")).toBeInTheDocument();
  });
});
