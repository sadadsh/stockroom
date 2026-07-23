/**
 * The reload-survives proof (Phase F / LAYOUT-01, CONTEXT verify gate): a committed ELEMENT_OVERRIDES
 * entry carrying layout values (`order` + `grid-column`) must apply as inline styles on boot with dev
 * mode OFF - so a saved reorder / re-slot ships for EVERYONE, not just the owner in an active session.
 *
 * This exercises the Phase E generic apply-by-id (lib/devMode.tsx's element effect, which runs
 * regardless of `enabled`, feeding applyElementOverrides). It is deliberately test-ONLY: it asserts the
 * existing pipeline already carries `order` / `grid-column` generically, so a reordered / re-slotted
 * layout persists across reload with no production change. It mirrors the vi.mock pattern in
 * lib/devMode.test.tsx (a mutable stand-in for the committed, on-disk-empty element.overrides.ts).
 */
import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { ThemeProvider } from "./theme";
import { DevModeProvider, useDevMode } from "./devMode";

// A mutable stand-in for the committed lib/element.overrides.ts (empty on disk). A test seeds it to
// stand in for what a prior Save committed, then afterEach empties it so nothing leaks between tests.
const MOCK_ELEMENT_OVERRIDES: Record<string, Record<string, string>> = vi.hoisted(() => ({}));
vi.mock("./element.overrides", () => ({ ELEMENT_OVERRIDES: MOCK_ELEMENT_OVERRIDES }));

afterEach(() => {
  document.documentElement.removeAttribute("style");
  document.documentElement.removeAttribute("data-theme");
  for (const key of Object.keys(MOCK_ELEMENT_OVERRIDES)) delete MOCK_ELEMENT_OVERRIDES[key];
});

// A provider whose subtree carries a real grid child [data-dev-id] node, so the boot apply has a live
// target - the matching element a committed layout override lands on for everyone.
function wrapper({ children }: { children: ReactNode }) {
  return (
    <ThemeProvider>
      <DevModeProvider>
        <div data-dev-id="detail.actions" className="grid grid-cols-2 gap-2">
          <button type="button" data-dev-id="detail.action-a" className="text-t1">
            Action A
          </button>
          <button type="button" data-dev-id="detail.action-b" className="text-t1">
            Action B
          </button>
        </div>
        {children}
      </DevModeProvider>
    </ThemeProvider>
  );
}

function actionNode(): HTMLElement {
  const el = document.querySelector<HTMLElement>('[data-dev-id="detail.action-a"]');
  if (!el) throw new Error("action-a node not rendered");
  return el;
}

describe("element overrides boot apply (reload-survives proof)", () => {
  it("applies a committed order + grid-column override as inline styles on boot with dev mode OFF", () => {
    // Seed the committed map BEFORE mount, as if a prior Save had reordered + re-slotted this element.
    MOCK_ELEMENT_OVERRIDES["detail.action-a"] = { order: "2", "grid-column": "1 / 3" };

    const { result } = renderHook(() => useDevMode(), { wrapper });

    // Dev mode is OFF: this is the everyone-on-boot path, not an active editing session.
    expect(result.current.enabled).toBe(false);

    // BOTH committed layout values landed as inline styles on the matching data-dev-id element, so the
    // reordered / re-slotted layout survives reload for every user.
    const el = actionNode();
    expect(el.style.getPropertyValue("order")).toBe("2");
    expect(el.style.getPropertyValue("grid-column")).toBe("1 / 3");
  });

  it("clears the inline layout styles when the committed override is removed (a reset ships too)", () => {
    // With no committed entry, the element boots with no inline order / grid-column - proving the apply
    // is driven purely by the committed map (a committed reset reverts for everyone, not just locally).
    const { result } = renderHook(() => useDevMode(), { wrapper });
    expect(result.current.enabled).toBe(false);
    const el = actionNode();
    expect(el.style.getPropertyValue("order")).toBe("");
    expect(el.style.getPropertyValue("grid-column")).toBe("");
  });
});
