/**
 * The one that matters: editing ONE repeated instance must not edit every instance, and a
 * a semantic role or repeated catalogue id must never become an implicit multi-selection.
 *
 * Before this, `applyElementOverrides` resolved every id with one `querySelectorAll`, so an override
 * keyed on a repeated element's id landed on all of its siblings - which is correct for a class-level
 * id and destructive for anything else. The two contracts are separate now, and these are the proofs.
 */
import { render } from "@testing-library/react";
import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { ThemeProvider } from "./theme";
import { DevModeProvider, useDevMode } from "./devMode";
import { applicableOverrides, applyElementOverrides } from "./applyElementOverrides";
import {
  CANDIDATE_ROLE,
  candidateDevId,
  componentProviderDevId,
  componentTabDevId,
  devIdScope,
  devIdSegment,
  instanceDevId,
  isAllowedDevId,
  nodeForDevId,
  nodesForDevId,
  renderedDevIds,
} from "./componentDevIds";

const MOCK_ELEMENT_OVERRIDES: Record<string, Record<string, string>> = vi.hoisted(() => ({}));
vi.mock("./element.overrides", () => ({ ELEMENT_OVERRIDES: MOCK_ELEMENT_OVERRIDES }));

afterEach(() => {
  document.body.innerHTML = "";
  document.documentElement.removeAttribute("style");
  document.documentElement.removeAttribute("data-theme");
  for (const key of Object.keys(MOCK_ELEMENT_OVERRIDES)) delete MOCK_ELEMENT_OVERRIDES[key];
});

/** Three staged candidate cards, exactly as `CandidateCard` marks itself up. */
function Candidates({ ids }: { ids: string[] }) {
  return (
    <div className="flex flex-col">
      {ids.map((id) => (
        <div key={id} data-dev-id={candidateDevId(id)} data-dev-role={CANDIDATE_ROLE}>
          {id}
        </div>
      ))}
    </div>
  );
}

function nodeFor(id: string): HTMLElement {
  const el = nodeForDevId(id);
  if (!el) throw new Error(`no element for ${id}`);
  return el;
}

describe("instance vs shared addressing", () => {
  it("classifies a bracketed id as an instance and a catalogue id as shared", () => {
    expect(devIdScope(candidateDevId("abc"))).toBe("instance");
    expect(devIdScope(componentTabDevId("stm32h743vit6"))).toBe("instance");
    expect(devIdScope(CANDIDATE_ROLE)).toBe("shared");
    expect(devIdScope("components.row")).toBe("shared");
  });

  it("an override on ONE instance leaves its siblings untouched", () => {
    render(<Candidates ids={["a", "b", "c"]} />);
    applyElementOverrides({ [candidateDevId("b")]: { width: "240px" } });

    expect(nodeFor(candidateDevId("b")).style.getPropertyValue("width")).toBe("240px");
    expect(nodeFor(candidateDevId("a")).style.getPropertyValue("width")).toBe("");
    expect(nodeFor(candidateDevId("c")).style.getPropertyValue("width")).toBe("");
  });

  it("does not implicitly expand a semantic target through data-dev-role", () => {
    render(<Candidates ids={["a", "b", "c"]} />);
    applyElementOverrides({ [CANDIDATE_ROLE]: { padding: "8px" } });

    for (const id of ["a", "b", "c"]) {
      expect(nodeFor(candidateDevId(id)).style.getPropertyValue("padding")).toBe("");
    }
  });

  it("does not implicitly broadcast a repeated data-dev-id override", () => {
    // Explicit multi-select resolves concrete occurrence ids before writing; a raw repeated id is
    // ambiguous and therefore applies nowhere.
    document.body.innerHTML =
      '<div data-dev-id="components.row"></div><div data-dev-id="components.row"></div>';
    applyElementOverrides({ "components.row": { gap: "4px" } });
    const rows = nodesForDevId("components.row");
    expect(rows).toHaveLength(2);
    for (const row of rows) expect(row.style.getPropertyValue("gap")).toBe("");
  });

  it("clears an instance override without disturbing the shared one", () => {
    render(<Candidates ids={["a", "b"]} />);
    const first: Record<string, Record<string, string>> = {
      [CANDIDATE_ROLE]: { padding: "8px" },
      [candidateDevId("b")]: { width: "1px" },
    };
    applyElementOverrides(first);
    applyElementOverrides({ [CANDIDATE_ROLE]: { padding: "8px" } }, first);

    expect(nodeFor(candidateDevId("b")).style.getPropertyValue("width")).toBe("");
    expect(nodeFor(candidateDevId("b")).style.getPropertyValue("padding")).toBe("");
    expect(nodeFor(candidateDevId("a")).style.getPropertyValue("padding")).toBe("");
  });

  it("survives a reorder: the id follows the record, not the position", () => {
    const first = render(<Candidates ids={["a", "b", "c"]} />);
    applyElementOverrides({ [candidateDevId("b")]: { width: "240px" } });
    expect(nodeFor(candidateDevId("b")).style.getPropertyValue("width")).toBe("240px");

    // Re-render in a different order. `b` moves; the override is still on `b` and only on `b`.
    first.rerender(<Candidates ids={["c", "b", "a"]} />);
    applyElementOverrides({ [candidateDevId("b")]: { width: "240px" } });
    expect(nodeFor(candidateDevId("b")).style.getPropertyValue("width")).toBe("240px");
    expect(nodeFor(candidateDevId("a")).style.getPropertyValue("width")).toBe("");
    expect(nodeFor(candidateDevId("c")).style.getPropertyValue("width")).toBe("");
  });
});

describe("an unsafe dynamic value cannot break selection", () => {
  // Every one of these would either close the bracket grammar early or make the selector a parse
  // error if the value reached the attribute or the selector raw.
  const HOSTILE = [
    'a"b',
    "a'b",
    "a[b]c",
    "a\\b",
    "a b",
    "a]b[c",
    "`tick`",
    "a\nb",
    "a\tb",
  ];

  it("strips the dangerous characters out of the id itself", () => {
    for (const value of HOSTILE) {
      const segment = devIdSegment(value);
      expect(segment).not.toMatch(/["'`\\[\]\s]/);
    }
  });

  it("still selects exactly the element the id names", () => {
    render(<Candidates ids={HOSTILE} />);
    for (const value of HOSTILE) {
      const id = candidateDevId(value);
      const matches = nodesForDevId(id);
      // Some hostile values collapse to the SAME segment (`a b` and `a\tb` both become `a_b`), which
      // is honest: they are one id, and it addresses every element carrying it. What must never
      // happen is a throw, or a selector that reaches the whole list.
      expect(matches.length).toBeGreaterThan(0);
      expect(matches.length).toBeLessThan(HOSTILE.length);
      for (const el of matches) expect(el.getAttribute("data-dev-id")).toBe(id);
    }
  });

  it("never throws, even for an id no escape could turn into a selector", () => {
    render(<Candidates ids={["a"]} />);
    expect(() => nodesForDevId('ingest.candidate["]')).not.toThrow();
    expect(() => applyElementOverrides({ 'ingest.candidate["]': { width: "1px" } })).not.toThrow();
  });
});

describe("what counts as an addressable id", () => {
  it("accepts a catalogue id and every approved dynamic shape", () => {
    expect(isAllowedDevId("components.row")).toBe(true);
    expect(isAllowedDevId(candidateDevId("abc"))).toBe(true);
    expect(isAllowedDevId(componentTabDevId("stm32h743vit6"))).toBe(true);
    expect(isAllowedDevId(componentProviderDevId("stm32h743vit6", "digikey"))).toBe(true);
    expect(isAllowedDevId(instanceDevId("stm.package", "LQFP100"))).toBe(true);
    expect(isAllowedDevId(instanceDevId("detail.handoff-field", "manufacturer"))).toBe(true);
  });

  it("refuses an unregistered id, bracketed or not", () => {
    expect(isAllowedDevId("made.up-id")).toBe(false);
    expect(isAllowedDevId("anything[whatever]")).toBe(false);
    expect(isAllowedDevId("components.row[1]")).toBe(false);
    expect(isAllowedDevId("")).toBe(false);
  });

  it("every id a real fixture renders is one of the allowed shapes", () => {
    render(
      <>
        <Candidates ids={["a", "b"]} />
        <div data-dev-id="components.row" />
        <div data-dev-id={componentTabDevId("stm32h743vit6")} />
        <div data-dev-id={componentProviderDevId("stm32h743vit6", "digikey")} />
      </>,
    );
    const rendered = renderedDevIds();
    expect(rendered.length).toBeGreaterThan(3);
    expect(rendered.filter((id) => !isAllowedDevId(id))).toEqual([]);
  });
});

describe("a stale committed override is ignored, not applied", () => {
  it("keeps approved transforms and drops values outside the safe grammar", () => {
    const kept = applicableOverrides({
      "components.row": {
        width: "240px",
        // Approved single transform, retained and re-saved.
        transform: "translateX(10px)",
        // Editable property, value outside the grammar (a second declaration attempt).
        padding: "8px; color: red",
        // Editable property, value too far outside the length grammar.
        gap: "calc(100% - 3px)",
      },
    });
    expect(kept).toEqual({ "components.row": { width: "240px", transform: "translateX(10px)" } });
  });

  it("applies only the surviving properties and does not throw on the rest", () => {
    document.body.innerHTML = '<div data-dev-id="components.row"></div>';
    expect(() =>
      applyElementOverrides({
        "components.row": { width: "240px", transform: "translateX(10px)", padding: "}{" },
      }),
    ).not.toThrow();
    const row = nodesForDevId("components.row")[0];
    expect(row.style.getPropertyValue("width")).toBe("240px");
    expect(row.style.getPropertyValue("transform")).toBe("translateX(10px)");
    expect(row.style.getPropertyValue("padding")).toBe("");
  });

  it("keeps an id whose transform is in the closed grammar", () => {
    expect(applicableOverrides({ "components.row": { transform: "translateX(10px)" } })).toEqual({
      "components.row": { transform: "translateX(10px)" },
    });
  });
});

// --- restart -------------------------------------------------------------------------------------
// A saved instance override is committed source, so the proof that it survives a restart is that a
// fresh mount with dev mode OFF applies it - the same path every user boots through.

function wrapper({ children }: { children: ReactNode }) {
  return (
    <ThemeProvider>
      <DevModeProvider>
        <Candidates ids={["a", "b", "c"]} />
        {children}
      </DevModeProvider>
    </ThemeProvider>
  );
}

describe("saved dynamic overrides survive a restart", () => {
  it("re-applies a committed instance override on boot, to that instance only", () => {
    MOCK_ELEMENT_OVERRIDES[candidateDevId("b")] = { width: "240px" };

    const { result } = renderHook(() => useDevMode(), { wrapper });
    expect(result.current.enabled).toBe(false);

    expect(nodeFor(candidateDevId("b")).style.getPropertyValue("width")).toBe("240px");
    expect(nodeFor(candidateDevId("a")).style.getPropertyValue("width")).toBe("");
    expect(nodeFor(candidateDevId("c")).style.getPropertyValue("width")).toBe("");
  });

  it("does not broaden a committed role-only override on boot", () => {
    MOCK_ELEMENT_OVERRIDES[CANDIDATE_ROLE] = { padding: "8px" };

    renderHook(() => useDevMode(), { wrapper });
    for (const id of ["a", "b", "c"]) {
      expect(nodeFor(candidateDevId(id)).style.getPropertyValue("padding")).toBe("");
    }
  });

  it("applies a committed transform that remains valid without failing the boot", () => {
    MOCK_ELEMENT_OVERRIDES[candidateDevId("b")] = { transform: "translateX(10px)", width: "240px" };

    expect(() => renderHook(() => useDevMode(), { wrapper })).not.toThrow();
    const node = nodeFor(candidateDevId("b"));
    expect(node.style.getPropertyValue("width")).toBe("240px");
    expect(node.style.getPropertyValue("transform")).toBe("translateX(10px)");
  });
});
