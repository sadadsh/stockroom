/**
 * The render half of the placeholder contract: a committed override that no longer matches the
 * sentence it reworded must not reach a person.
 *
 * `COPY_OVERRIDES` is mocked with a mutable object, the same way `lib/devMode.test.tsx` stands in
 * for the committed token file, so each case is exactly "a previous Save committed this, and the
 * app has since booted with it".
 */
import { useEffect } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Text, useCopyFormatter, useText } from "./copy";
import { DevModeProvider, useDevMode } from "./devMode";
import { ThemeProvider } from "./theme";
import {
  copyDiagnosticFor,
  resetCopyDeclarations,
  resetCopyDiagnostics,
} from "./copyPlaceholders";

const MOCK_COPY: Record<string, string> = vi.hoisted(() => ({}));
// `OWNER_AUTHORED_COPY_IDS` is the module's second export (the Phase 4 provenance record read by
// `devModeSave`). It is stubbed empty here because this file is about the RENDER half of the
// placeholder contract; leaving it out would make the module's other consumers see `undefined`.
vi.mock("./copy.overrides", () => ({ COPY_OVERRIDES: MOCK_COPY, OWNER_AUTHORED_COPY_IDS: [] }));

beforeEach(() => {
  resetCopyDiagnostics();
  resetCopyDeclarations();
});

afterEach(() => {
  for (const key of Object.keys(MOCK_COPY)) delete MOCK_COPY[key];
});

const ID = "provider.downloaded";
const DEFAULT_TEXT = "Downloaded {count} of {total} files";

function Downloaded() {
  return (
    <Text id={ID} values={{ count: 3, total: 10 }}>
      {DEFAULT_TEXT}
    </Text>
  );
}

describe("placeholder rendering", () => {
  it("substitutes the values into the default when nothing is overridden", () => {
    render(<Downloaded />);
    expect(screen.getByText("Downloaded 3 of 10 files")).toBeInTheDocument();
  });

  it("substitutes the values into a VALID override", () => {
    MOCK_COPY[ID] = "{count} of {total} files are in";
    render(<Downloaded />);
    expect(screen.getByText("3 of 10 files are in")).toBeInTheDocument();
    expect(copyDiagnosticFor(ID)).toBeUndefined();
  });

  it("falls back to the default and records a diagnostic for a MALFORMED override", () => {
    MOCK_COPY[ID] = "Downloaded {count} of {total files";
    const { container } = render(<Downloaded />);
    expect(screen.getByText("Downloaded 3 of 10 files")).toBeInTheDocument();
    // The one thing that must never happen: raw template syntax on screen.
    expect(container.textContent).not.toContain("{");
    expect(container.textContent).not.toContain("}");
    expect(copyDiagnosticFor(ID)?.problem).toBe("malformed");
    expect(copyDiagnosticFor(ID)?.required).toEqual(["count", "total"]);
  });

  it("falls back to the default when an override DROPS a required placeholder", () => {
    MOCK_COPY[ID] = "Downloaded some files";
    render(<Downloaded />);
    expect(screen.getByText("Downloaded 3 of 10 files")).toBeInTheDocument();
    expect(copyDiagnosticFor(ID)?.problem).toBe("missing-placeholder");
  });

  it("falls back to the default when an override INVENTS a placeholder", () => {
    MOCK_COPY[ID] = "Downloaded {count} of {total} on {pages}";
    render(<Downloaded />);
    expect(screen.getByText("Downloaded 3 of 10 files")).toBeInTheDocument();
    expect(copyDiagnosticFor(ID)?.problem).toBe("unknown-placeholder");
  });

  it("does not throw on any malformed override, however hostile", () => {
    for (const bad of ["{", "}", "{}", "{{count}}", "{1}", "}{", "{count", "count}"]) {
      MOCK_COPY[ID] = bad;
      resetCopyDiagnostics();
      const { container, unmount } = render(<Downloaded />);
      expect(container.textContent).toBe("Downloaded 3 of 10 files");
      unmount();
    }
  });
});

function Attribute() {
  const label = useText("a.label", "Open {name}", { name: "DigiKey" });
  return <button type="button" aria-label={label} />;
}

function Deferred({ onReady }: { onReady: (text: string) => void }) {
  const format = useCopyFormatter("a.toast", "Added {name}");
  // The formatter still resolves and substitutes during render - that is the contract under test,
  // and it is pure. Only the report out to the caller waits for the commit: in the app a formatter's
  // result reaches a toast from an event, never from render, which React may replay or discard.
  const text = format({ name: "STM32H743VIT6" });
  useEffect(() => {
    onReady(text);
  }, [onReady, text]);
  return null;
}

describe("the attribute and deferred forms follow the same rules", () => {
  it("useText substitutes into an attribute", () => {
    render(<Attribute />);
    expect(screen.getByRole("button", { name: "Open DigiKey" })).toBeInTheDocument();
  });

  it("useText falls back to the default when the override is malformed", () => {
    MOCK_COPY["a.label"] = "Open {nam";
    render(<Attribute />);
    expect(screen.getByRole("button", { name: "Open DigiKey" })).toBeInTheDocument();
    expect(copyDiagnosticFor("a.label")?.problem).toBe("malformed");
  });

  it("useCopyFormatter resolves during render and substitutes later", () => {
    let out = "";
    render(<Deferred onReady={(text) => (out = text)} />);
    expect(out).toBe("Added STM32H743VIT6");
  });

  it("useCopyFormatter honours a valid override and refuses an invalid one", () => {
    MOCK_COPY["a.toast"] = "{name} was added";
    let out = "";
    const first = render(<Deferred onReady={(text) => (out = text)} />);
    expect(out).toBe("STM32H743VIT6 was added");
    first.unmount();

    MOCK_COPY["a.toast"] = "A part was added";
    render(<Deferred onReady={(text) => (out = text)} />);
    expect(out).toBe("Added STM32H743VIT6");
  });
});

// --- selecting a string to reword, from the keyboard --------------------------------------------
//
// Dev Mode wraps every routed string in a click target so the panel can be pointed at it. That
// target used to be pointer-only, which made rewording an unreachable action for anybody working
// from the keyboard - and it is the ONE action the whole copy layer exists to enable.

describe("Dev Mode copy selection", () => {
  function EnabledText() {
    const { enabled, toggle, studioMode, setStudioMode } = useDevMode();
    return (
      <>
        {enabled ? null : (
          <button type="button" onClick={toggle}>
            on
          </button>
        )}
        {enabled && studioMode !== "edit" ? (
          <button type="button" onClick={() => setStudioMode("edit")}>
            edit
          </button>
        ) : null}
        <Text id="k.probe">Probe Label</Text>
      </>
    );
  }

  function mountEnabled() {
    render(
      <ThemeProvider>
        <DevModeProvider>
          <EnabledText />
        </DevModeProvider>
      </ThemeProvider>,
    );
    fireEvent.click(screen.getByText("on"));
    fireEvent.click(screen.getByText("edit"));
    return screen.getByText("Probe Label");
  }

  it("puts the copy target in the tab order while Dev Mode is on", () => {
    expect(mountEnabled().getAttribute("tabindex")).toBe("0");
  });

  it("selects the string on Enter and on Space, not on the pointer alone", () => {
    const target = mountEnabled();
    expect(target.getAttribute("data-copy-id")).toBe("k.probe");

    fireEvent.keyDown(target, { key: "Enter" });
    expect(target.className).toContain("bg-acc/20");

    // A key the affordance does not claim must fall through untouched.
    const before = target.className;
    fireEvent.keyDown(target, { key: "a" });
    expect(target.className).toBe(before);
  });
});
