import { act, fireEvent, render, screen } from "@testing-library/react";
import { ToastProvider, useToast } from "./toast";

function Trigger() {
  const { toast } = useToast();
  return (
    <button type="button" onClick={() => toast("Saved", "ok")}>
      fire
    </button>
  );
}

function ActionTrigger({ action }: { action: () => void }) {
  const { toast } = useToast();
  return (
    <button
      type="button"
      onClick={() => toast("Part deleted", "ok", { label: "Undo Delete", onClick: action })}
    >
      delete
    </button>
  );
}

describe("toasts", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("shows a toast and auto-dismisses it after the timeout", () => {
    render(
      <ToastProvider>
        <Trigger />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByText("fire"));
    expect(screen.getByText("Saved")).toBeInTheDocument();

    act(() => vi.advanceTimersByTime(4000));
    expect(screen.queryByText("Saved")).not.toBeInTheDocument();
  });

  it("dismisses when clicked", () => {
    render(
      <ToastProvider>
        <Trigger />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByText("fire"));
    fireEvent.click(screen.getByRole("button", { name: "Dismiss Saved" }));
    expect(screen.queryByText("Saved")).not.toBeInTheDocument();
  });

  it("runs an explicit recovery action once and dismisses the toast", () => {
    const action = vi.fn();
    render(
      <ToastProvider>
        <ActionTrigger action={action} />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByText("delete"));

    fireEvent.click(screen.getByRole("button", { name: "Undo Delete" }));

    expect(action).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Part deleted")).not.toBeInTheDocument();
  });

  it("throws when used outside a provider", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<Trigger />)).toThrow(/ToastProvider/);
    spy.mockRestore();
  });
});
