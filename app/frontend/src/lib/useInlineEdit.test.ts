import { act, renderHook } from "@testing-library/react";
import { useInlineEdit } from "./useInlineEdit";

// These lock the one hard invariant: a field saves at most once per edit and
// never on cancel. Both real-browser races fire a second commit in the SAME tick
// (Enter-then-blur, Escape-then-blur). We reproduce that by calling commit twice
// inside one act() with no render between: the ref-based guard flips
// synchronously, so a second commit is a no-op. Remove the guard and the
// double-commit test sees two saves and the cancel test sees one -> both go red.

function setup(initial = "Old") {
  const onSave = vi.fn();
  const view = renderHook((value: string) => useInlineEdit(value, onSave), {
    initialProps: initial,
  });
  return { onSave, ...view };
}

describe("useInlineEdit", () => {
  it("saves exactly once when a second commit fires in the same tick", () => {
    const { result, onSave } = setup("Old");
    act(() => result.current.begin());
    act(() => result.current.setDraft("New"));
    act(() => {
      result.current.commit();
      result.current.commit(); // the unmount-blur second commit
    });
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave).toHaveBeenCalledWith("New");
  });

  it("never saves when a commit follows a cancel in the same tick", () => {
    const { result, onSave } = setup("Old");
    act(() => result.current.begin());
    act(() => result.current.setDraft("New"));
    act(() => {
      result.current.cancel();
      result.current.commit(); // the Escape-then-blur second commit
    });
    expect(onSave).not.toHaveBeenCalled();
  });

  it("does not save a no-op edit (unchanged value)", () => {
    const { result, onSave } = setup("Same");
    act(() => result.current.begin());
    act(() => result.current.commit());
    expect(onSave).not.toHaveBeenCalled();
  });

  it("trims whitespace before comparing and saving", () => {
    const { result, onSave } = setup("Old");
    act(() => result.current.begin());
    act(() => result.current.setDraft("  New  "));
    act(() => result.current.commit());
    expect(onSave).toHaveBeenCalledWith("New");
  });

  it("resets a stale draft to the current value when a new edit begins", () => {
    const { result } = setup("Old");
    act(() => result.current.begin());
    act(() => result.current.setDraft("Typed But Abandoned"));
    act(() => result.current.cancel());
    act(() => result.current.begin());
    expect(result.current.draft).toBe("Old");
  });
});
