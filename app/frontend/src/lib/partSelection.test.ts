import { beforeEach, describe, expect, it, vi } from "vitest";
import { onRequestedPart, requestPart } from "./partSelection";

// The module holds one slot of state; reset the subscriber between tests.
beforeEach(() => {
  const off = onRequestedPart(() => {});
  off();
});

describe("partSelection", () => {
  it("delivers a request to a live subscriber", () => {
    const seen = vi.fn();
    const off = onRequestedPart(seen);
    requestPart("lm358");
    expect(seen).toHaveBeenCalledWith("lm358");
    off();
  });

  it("buffers a request fired before anyone subscribes, then drains it on subscribe", () => {
    // The palette can fire on a route where Components is not yet mounted.
    requestPart("buffered");
    const seen = vi.fn();
    const off = onRequestedPart(seen);
    expect(seen).toHaveBeenCalledWith("buffered");
    off();
  });

  it("drains the buffer only once", () => {
    requestPart("once");
    const first = vi.fn();
    const offFirst = onRequestedPart(first);
    offFirst();
    const second = vi.fn();
    const offSecond = onRequestedPart(second);
    expect(first).toHaveBeenCalledWith("once");
    expect(second).not.toHaveBeenCalled(); // the buffer was already consumed
    offSecond();
  });

  it("unsubscribing stops delivery", () => {
    const seen = vi.fn();
    const off = onRequestedPart(seen);
    off();
    requestPart("after-off");
    expect(seen).not.toHaveBeenCalled();
  });

  it("a later subscriber replaces the earlier one", () => {
    const first = vi.fn();
    const offFirst = onRequestedPart(first);
    const second = vi.fn();
    const offSecond = onRequestedPart(second);
    requestPart("routed");
    expect(second).toHaveBeenCalledWith("routed");
    expect(first).not.toHaveBeenCalled();
    offFirst();
    offSecond();
  });
});
