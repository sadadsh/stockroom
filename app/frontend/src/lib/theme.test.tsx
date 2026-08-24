import { describe, expect, it, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AstryxThemeBridge, ThemeProvider, useTheme } from "./theme";

function Probe() {
  const { theme, colorScheme, toggle, setTheme, setColorScheme } = useTheme();
  return (
    <div>
      <span data-testid="theme">{theme}</span>
      <span data-testid="color-scheme">{colorScheme}</span>
      <button onClick={toggle}>Toggle Theme</button>
      <button onClick={() => setTheme("light")}>Go Light</button>
      <button onClick={() => setColorScheme("blue")}>Go Blue</button>
    </div>
  );
}

describe("ThemeProvider", () => {
  beforeEach(() => {
    localStorage.clear();
    // See AppShell.test.tsx: the theme is stored in the machine config and injected by the host, so
    // the injected copy is part of the slate a test has to reset.
    window.__STOCKROOM_UI__ = {};
    delete document.documentElement.dataset.theme;
    delete document.documentElement.dataset.astryxTheme;
    delete document.documentElement.dataset.colorScheme;
  });

  it("defaults to dark and marks the root", () => {
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );
    expect(screen.getByTestId("theme").textContent).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("bridges the machine theme into the editable ASTRYX neutral theme", () => {
    render(
      <ThemeProvider>
        <AstryxThemeBridge><Probe /></AstryxThemeBridge>
      </ThemeProvider>,
    );
    expect(document.documentElement.dataset.astryxTheme).toBe("neutral");
    expect(document.querySelector('[data-astryx-theme="neutral"][data-theme="dark"]')).not.toBeNull();
  });

  it("toggles to light and marks the root", async () => {
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );
    await userEvent.click(screen.getByText("Toggle Theme"));
    expect(screen.getByTestId("theme").textContent).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("persists the choice across mounts", async () => {
    const first = render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );
    await userEvent.click(screen.getByText("Toggle Theme"));
    expect(localStorage.getItem("sr-theme")).toBe("light");
    first.unmount();
    // a fresh mount reads the persisted preference
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );
    expect(screen.getByTestId("theme").textContent).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("setTheme applies a specific theme", async () => {
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );
    await userEvent.click(screen.getByText("Go Light"));
    expect(screen.getByTestId("theme").textContent).toBe("light");
  });

  it("persists one paired color scheme for both themes", async () => {
    const first = render(<ThemeProvider><Probe /></ThemeProvider>);
    await userEvent.click(screen.getByText("Go Blue"));
    expect(document.documentElement.dataset.colorScheme).toBe("blue");
    expect(localStorage.getItem("sr-color-scheme")).toBe("blue");
    first.unmount();

    render(<ThemeProvider><Probe /></ThemeProvider>);
    expect(screen.getByTestId("color-scheme")).toHaveTextContent("blue");
    expect(document.documentElement.dataset.colorScheme).toBe("blue");
  });
});
