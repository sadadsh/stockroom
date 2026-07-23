import { render, fireEvent } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { Icon, sanitizeIconBody } from "./Icon";
import { ThemeProvider } from "../lib/theme";
import { DevModeProvider, useDevMode } from "../lib/devMode";
import { ICON_BY_ID } from "../lib/iconRegistry";
import { ICON_OVERRIDES } from "../lib/icon.overrides";

// ICON_OVERRIDES is the live, committed override map that <Icon> reads at render time. Tests mutate
// it to simulate a saved override, then clear it so cases stay isolated.
afterEach(() => {
  for (const key of Object.keys(ICON_OVERRIDES)) delete ICON_OVERRIDES[key];
});

function renderIcon(props: Parameters<typeof Icon>[0]) {
  const { container } = render(<Icon {...props} />);
  return container.querySelector("svg");
}

describe("Icon - default rendering", () => {
  it("renders the registry default body for a primary icon", () => {
    const svg = renderIcon({ id: "action.add" });
    expect(svg).not.toBeNull();
    const path = svg?.querySelector("path");
    expect(path?.getAttribute("d")).toBe("M12 5v14M5 12h14");
  });

  it("applies the shared .ico class + stroke-width so --icon-stroke retunes primary icons", () => {
    const svg = renderIcon({ id: "action.add" });
    expect(svg?.classList.contains("ico")).toBe(true);
    expect(svg?.getAttribute("viewBox")).toBe("0 0 24 24");
    expect(svg?.getAttribute("stroke")).toBe("currentColor");
    // 1.9 is the offline fallback; the .ico class routes the live weight through --icon-stroke.
    expect(svg?.getAttribute("stroke-width")).toBe("1.9");
  });

  it("merges the caller className alongside .ico, or defaults the size when none is given", () => {
    expect(renderIcon({ id: "action.add", className: "h-4 w-4" })?.getAttribute("class")).toBe(
      "ico h-4 w-4",
    );
    expect(renderIcon({ id: "action.add" })?.getAttribute("class")).toBe("ico h-3.5 w-3.5");
  });

  it("renders a bespoke icon with its own size + weight and no .ico class", () => {
    const svg = renderIcon({ id: "action.search" });
    expect(svg?.classList.contains("ico")).toBe(false);
    expect(svg?.getAttribute("width")).toBe("14");
    expect(svg?.getAttribute("height")).toBe("14");
    expect(svg?.getAttribute("stroke-width")).toBe("2");
    expect(svg?.querySelector("circle")?.getAttribute("r")).toBe("7");
  });

  it("renders an art glyph with its rectangular size and theme-var markup", () => {
    const svg = renderIcon({ id: "art.symbol" });
    expect(svg?.getAttribute("width")).toBe("132");
    expect(svg?.getAttribute("height")).toBe("94");
    expect(svg?.innerHTML).toContain("var(--c-icon-line)");
  });
});

describe("Icon - overrides", () => {
  it("renders swapToId's glyph instead of the id's own", () => {
    ICON_OVERRIDES["action.add"] = { swapToId: "action.trash" };
    const svg = renderIcon({ id: "action.add" });
    const trashBody = ICON_BY_ID.get("action.trash")?.body ?? "";
    const trashD = /d="([^"]+)"/.exec(trashBody)?.[1];
    expect(svg?.querySelector("path")?.getAttribute("d")).toBe(trashD);
  });

  it("renders an override body over the registry default", () => {
    ICON_OVERRIDES["action.add"] = { body: '<circle cx="12" cy="12" r="5"/>' };
    const svg = renderIcon({ id: "action.add" });
    expect(svg?.querySelector("circle")?.getAttribute("r")).toBe("5");
    expect(svg?.querySelector("path")).toBeNull();
    // The frame is still the id's own (primary preset), only the body was replaced.
    expect(svg?.classList.contains("ico")).toBe(true);
  });

  it("does not loop on a swapToId cycle", () => {
    ICON_OVERRIDES["action.add"] = { swapToId: "action.edit" };
    ICON_OVERRIDES["action.edit"] = { swapToId: "action.add" };
    const svg = renderIcon({ id: "action.add" });
    // Resolves to a terminal entry rather than hanging; either endpoint is acceptable.
    expect(svg).not.toBeNull();
    expect(svg?.querySelector("path")).not.toBeNull();
  });

  it("falls back to the registry default when swapToId targets an unknown id", () => {
    ICON_OVERRIDES["action.add"] = { swapToId: "not.a.real.icon" };
    const svg = renderIcon({ id: "action.add" });
    expect(svg?.querySelector("path")?.getAttribute("d")).toBe("M12 5v14M5 12h14");
  });
});

describe("Icon - safety", () => {
  it("is a no-op for an unknown id", () => {
    const { container } = render(<Icon id="does.not.exist" />);
    expect(container.querySelector("svg")).toBeNull();
    expect(container.innerHTML).toBe("");
  });

  it("strips <script> and on* handlers from an override body", () => {
    ICON_OVERRIDES["action.add"] = {
      body: '<path d="M0 0" onclick="steal()"/><script>alert(1)</script>',
    };
    const svg = renderIcon({ id: "action.add" });
    expect(svg?.querySelector("script")).toBeNull();
    expect(svg?.innerHTML).not.toContain("alert");
    expect(svg?.querySelector("path")?.getAttribute("onclick")).toBeNull();
  });

  it("sanitizeIconBody removes dangerous elements, handlers and remote refs", () => {
    const dirty =
      '<path d="M0 0" onload="x()"/>' +
      "<script>bad()</script>" +
      '<foreignObject><div>x</div></foreignObject>' +
      '<use href="http://evil.example/x"/>' +
      '<image xlink:href="https://evil.example/y.png"/>';
    const clean = sanitizeIconBody(dirty);
    expect(clean).toContain('<path d="M0 0"');
    expect(clean).not.toMatch(/onload/i);
    expect(clean).not.toMatch(/<script/i);
    expect(clean).not.toMatch(/<foreignObject/i);
    expect(clean).not.toMatch(/evil\.example/i);
  });

  it("keeps a local #fragment ref and inline theme-var style", () => {
    const body = '<rect fill="url(#grad)" style="stroke:var(--c-icon-line)"/>';
    expect(sanitizeIconBody(body)).toBe(body);
  });
});

// --- Dev Mode v2: <Icon> resolves overrides through the context + advertises its id in dev mode ---

// A control harness: renders <Icon id> inside real providers, with buttons that drive the working
// override state and the dev-mode toggle, so a test can prove a working edit renders live (D-02).
const OVERRIDE_BODY = '<circle cx="12" cy="12" r="5"/>';

function Controls({ id }: { id: string }) {
  const dm = useDevMode();
  return (
    <>
      <button type="button" onClick={() => dm.setIconBody(id, OVERRIDE_BODY)}>
        set-body
      </button>
      <button type="button" onClick={() => dm.setIconSwap(id, "action.trash")}>
        set-swap
      </button>
      <button type="button" onClick={() => dm.toggle()}>
        toggle-dev
      </button>
      <Icon id={id} />
    </>
  );
}

function renderProvided(id: string) {
  const utils = render(
    <ThemeProvider>
      <DevModeProvider>
        <Controls id={id} />
      </DevModeProvider>
    </ThemeProvider>,
  );
  return { ...utils, svg: () => utils.container.querySelector("svg") };
}

afterEach(() => {
  // The provider's token effect writes inline CSS vars on <html>; clear them so cases stay isolated.
  document.documentElement.removeAttribute("style");
  document.documentElement.removeAttribute("data-theme");
});

describe("Icon - context-driven overrides (dev mode v2)", () => {
  it("renders a working-state body override live under a provider (no committed module edit)", () => {
    const { getByText, svg } = renderProvided("action.add");
    // Before any edit the provider resolves the committed path: the registry default.
    expect(svg()?.querySelector("path")?.getAttribute("d")).toBe("M12 5v14M5 12h14");

    fireEvent.click(getByText("set-body"));
    // The working override now renders live: body replaced, frame (primary .ico preset) intact.
    expect(svg()?.querySelector("circle")?.getAttribute("r")).toBe("5");
    expect(svg()?.querySelector("path")).toBeNull();
    expect(svg()?.classList.contains("ico")).toBe(true);
    // ICON_OVERRIDES (the committed module) was never touched - this is working-state only.
    expect(ICON_OVERRIDES["action.add"]).toBeUndefined();
  });

  it("renders a working-state swapToId target live under a provider", () => {
    const { getByText, svg } = renderProvided("action.add");
    fireEvent.click(getByText("set-swap"));
    const trashBody = ICON_BY_ID.get("action.trash")?.body ?? "";
    const trashD = /d="([^"]+)"/.exec(trashBody)?.[1];
    expect(svg()?.querySelector("path")?.getAttribute("d")).toBe(trashD);
  });

  it("with no provider renders the registry default unchanged (byte-identical to today)", () => {
    const svg = renderIcon({ id: "action.add" });
    expect(svg?.querySelector("path")?.getAttribute("d")).toBe("M12 5v14M5 12h14");
    expect(svg?.getAttribute("data-icon-id")).toBeNull();
  });

  it("an entry with neither body nor swap in working-state resolves exactly as committed", () => {
    // A provider with an empty working-state resolves the same registry default as the module path.
    const { svg } = renderProvided("action.add");
    expect(svg()?.querySelector("path")?.getAttribute("d")).toBe("M12 5v14M5 12h14");
  });
});

describe("Icon - dev-mode identity (data-icon-id)", () => {
  it("emits data-icon-id equal to the id only while dev mode is enabled", () => {
    const { getByText, svg } = renderProvided("action.add");
    // Dev mode off (provider mounted but not enabled): no data-icon-id, off-dev DOM untouched.
    expect(svg()?.getAttribute("data-icon-id")).toBeNull();

    fireEvent.click(getByText("toggle-dev"));
    expect(svg()?.getAttribute("data-icon-id")).toBe("action.add");

    fireEvent.click(getByText("toggle-dev"));
    expect(svg()?.getAttribute("data-icon-id")).toBeNull();
  });

  it("carries data-icon-id on a bespoke glyph too when dev mode is enabled", () => {
    const { getByText, svg } = renderProvided("action.search");
    expect(svg()?.getAttribute("data-icon-id")).toBeNull();
    fireEvent.click(getByText("toggle-dev"));
    expect(svg()?.getAttribute("data-icon-id")).toBe("action.search");
  });

  it("emits no data-icon-id with no provider (off-dev output is byte-identical)", () => {
    const svg = renderIcon({ id: "action.search" });
    expect(svg?.getAttribute("data-icon-id")).toBeNull();
  });
});

describe("Icon - accessibility", () => {
  it("adds role/aria-label/title when titled, aria-hidden when not", () => {
    const titled = renderIcon({ id: "action.add", title: "Add part" });
    expect(titled?.getAttribute("role")).toBe("img");
    expect(titled?.getAttribute("aria-label")).toBe("Add part");
    expect(titled?.querySelector("title")?.textContent).toBe("Add part");
    expect(titled?.getAttribute("aria-hidden")).toBeNull();

    const bare = renderIcon({ id: "action.add" });
    expect(bare?.getAttribute("aria-hidden")).toBe("true");
    expect(bare?.querySelector("title")).toBeNull();
  });
});
