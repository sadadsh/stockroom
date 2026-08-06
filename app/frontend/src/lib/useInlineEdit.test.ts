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

  // --- the draft is DERIVED, not a second copy chased by an effect -------------------------------
  //
  // Both of these are render COUNTS, and they have to be: an effect that mirrors a value into state
  // has already caught up by the time `result.current` can be read, so the wrong answer is invisible
  // from the outside and only the wasted render it cost is left to observe. That render is not free
  // either - it is a whole field re-rendering, in a list of them, every time a save lands.

  function counted(initial: string) {
    const onSave = vi.fn();
    let renders = 0;
    const view = renderHook(
      (value: string) => {
        renders += 1;
        return useInlineEdit(value, onSave);
      },
      { initialProps: initial },
    );
    return { onSave, renders: () => renders, ...view };
  }

  it("follows a value that changes underneath it without a second render", () => {
    // A different part is selected, or a save lands.
    const view = counted("Old");
    const atMount = view.renders();
    view.rerender("Fresh");
    expect(view.result.current.draft).toBe("Fresh");
    expect(view.renders()).toBe(atMount + 1);
  });

  it("ends an edit without a second render to put the draft back", () => {
    // commit() ends the edit but does not change `value` - the save is asynchronous - so the draft
    // has to go back to the underlying value. Derived, it already is.
    const view = counted("Old");
    act(() => view.result.current.begin());
    act(() => view.result.current.setDraft("New"));
    const beforeCommit = view.renders();
    act(() => view.result.current.commit());
    expect(view.result.current.editing).toBe(false);
    expect(view.result.current.draft).toBe("Old");
    expect(view.renders()).toBe(beforeCommit + 1);
  });
});
