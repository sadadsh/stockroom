/**
 * The dev-mode Design panel: a right-docked surface, shown only while dev mode is on
 * (Ctrl/Cmd+Shift+D). It nudges the registered design tokens live for the active theme, edits the
 * copy label most recently clicked, and Saves everything back to source so it ships for everyone.
 * It renders nothing when dev mode is off, so it never touches the normal app.
 */
import { useTheme } from "../lib/theme";
import { useDevMode } from "../lib/devMode";
import { DEV_TOKENS, DEV_TOKEN_GROUPS, type DevToken } from "../lib/devTokens";
import { Button } from "./primitives";

// A best-effort hex for the native colour picker. A hex passes through; an rgb/rgba collapses to
// its opaque hex (the picker cannot show alpha, but the text field below stays authoritative).
function toHex(value: string): string {
  const s = value.trim();
  if (/^#[0-9a-f]{6}$/i.test(s)) return s;
  if (/^#[0-9a-f]{3}$/i.test(s)) {
    return "#" + s.slice(1).split("").map((c) => c + c).join("");
  }
  const m = s.match(/rgba?\(([^)]+)\)/i);
  if (m) {
    const [r, g, b] = m[1].split(",").map((x) => parseFloat(x.trim()));
    if ([r, g, b].every(Number.isFinite)) {
      const h = (x: number) =>
        Math.max(0, Math.min(255, Math.round(x))).toString(16).padStart(2, "0");
      return "#" + h(r) + h(g) + h(b);
    }
  }
  return "#888888";
}

function ResetDot({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="Reset to default"
      title="Reset to default"
      className="grid h-4 w-4 flex-none place-items-center rounded-full text-t3 hover:bg-line2 hover:text-t1"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" className="h-3 w-3">
        <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
        <path d="M3 3v5h5" />
      </svg>
    </button>
  );
}

function ColorRow({ token }: { token: DevToken }) {
  const dev = useDevMode();
  const value = dev.tokenValue(token.cssVar);
  const overridden = dev.isTokenOverridden(token.cssVar);
  return (
    <div className="flex items-center gap-2 py-1">
      <span className="min-w-0 flex-1 truncate text-xs text-t2">{token.label}</span>
      {overridden ? <ResetDot onClick={() => dev.resetToken(token.cssVar)} /> : null}
      <span
        className="relative h-6 w-6 flex-none overflow-hidden rounded-control border border-line2"
        style={{ background: value }}
      >
        <input
          type="color"
          aria-label={`${token.label} color`}
          value={toHex(value)}
          onChange={(e) => dev.setToken(token.cssVar, e.target.value)}
          className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
        />
      </span>
      <input
        type="text"
        aria-label={`${token.label} value`}
        value={value}
        onChange={(e) => dev.setToken(token.cssVar, e.target.value)}
        className="tnum w-[104px] flex-none rounded-control border border-line bg-field px-2 py-1 text-2xs font-mono text-t1 outline-none focus:border-acc"
      />
    </div>
  );
}

function LengthRow({ token }: { token: DevToken }) {
  const dev = useDevMode();
  const value = dev.tokenValue(token.cssVar);
  const n = parseFloat(value) || 0;
  const overridden = dev.isTokenOverridden(token.cssVar);
  return (
    <div className="flex items-center gap-2 py-1">
      <span className="min-w-0 flex-1 truncate text-xs text-t2">{token.label}</span>
      {overridden ? <ResetDot onClick={() => dev.resetToken(token.cssVar)} /> : null}
      <input
        type="range"
        aria-label={`${token.label} slider`}
        min={0}
        max={28}
        step={1}
        value={n}
        onChange={(e) => dev.setToken(token.cssVar, `${e.target.value}px`)}
        className="w-[104px] flex-none accent-acc"
      />
      <input
        type="number"
        aria-label={`${token.label} value`}
        value={n}
        onChange={(e) => dev.setToken(token.cssVar, `${e.target.value}px`)}
        className="tnum w-[52px] flex-none rounded-control border border-line bg-field px-2 py-1 text-2xs font-mono text-t1 outline-none focus:border-acc"
      />
    </div>
  );
}

function CopyEditor() {
  const dev = useDevMode();
  if (!dev.selectedCopyId) {
    return (
      <div className="border-b border-line px-3.5 py-3 text-2xs text-t3">
        Click any underlined label in the app to edit its text.
      </div>
    );
  }
  const id = dev.selectedCopyId;
  const current = dev.resolveCopy(id, dev.selectedCopyDefault);
  return (
    <div className="border-b border-line px-3.5 py-3">
      <div className="mb-1.5 flex items-center justify-between">
        <span className="text-2xs font-semibold uppercase tracking-[0.06em] text-t3">Copy</span>
        <button
          type="button"
          onClick={dev.clearSelectedCopy}
          className="text-2xs font-semibold text-t2 hover:text-t1"
        >
          Done
        </button>
      </div>
      <div className="mb-1.5 truncate font-mono text-2xs text-t3" title={id}>
        {id}
      </div>
      <textarea
        aria-label="Edit copy text"
        value={current}
        rows={2}
        onChange={(e) => dev.setCopy(id, e.target.value)}
        className="w-full resize-y rounded-control border border-line2 bg-field px-2 py-1.5 text-sm text-t1 outline-none focus:border-acc"
      />
      {dev.isCopyOverridden(id) ? (
        <button
          type="button"
          onClick={() => dev.resetCopy(id)}
          className="mt-1.5 text-2xs text-t3 hover:text-t1"
        >
          Reset to default
        </button>
      ) : null}
    </div>
  );
}

export function DevPanel() {
  const dev = useDevMode();
  const { theme, setTheme } = useTheme();
  if (!dev.enabled) return null;

  return (
    <aside
      className="fixed right-0 top-0 z-[200] flex h-full w-[300px] flex-col border-l border-line bg-popover shadow-pop"
      aria-label="Dev mode"
    >
      <header className="flex items-center gap-2 border-b border-line px-3.5 py-3">
        <span className="rounded-control bg-acc px-1.5 py-0.5 text-2xs font-bold tracking-wide text-acc-on">
          DEV
        </span>
        <span className="text-sm font-semibold text-t1">Design</span>
        <button
          type="button"
          onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          className="ml-auto rounded-control border border-line px-2 py-1 text-2xs font-medium text-t2 hover:text-t1"
          title="Colours edit the active theme"
        >
          {theme === "dark" ? "Dark" : "Light"} theme
        </button>
        <button
          type="button"
          onClick={dev.toggle}
          aria-label="Close dev mode"
          className="grid h-6 w-6 place-items-center rounded-control text-t3 hover:bg-raise2 hover:text-t1"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" className="h-4 w-4">
            <path d="M18 6 6 18M6 6l12 12" />
          </svg>
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <CopyEditor />
        <div className="px-3.5 py-2">
          {DEV_TOKEN_GROUPS.map((group) => {
            const tokens = DEV_TOKENS.filter((t) => t.group === group);
            if (tokens.length === 0) return null;
            return (
              <section key={group} className="py-1.5">
                <div className="mb-0.5 text-2xs font-semibold uppercase tracking-[0.06em] text-t3">
                  {group}
                </div>
                {tokens.map((token) =>
                  token.kind === "color" ? (
                    <ColorRow key={token.cssVar} token={token} />
                  ) : (
                    <LengthRow key={token.cssVar} token={token} />
                  ),
                )}
              </section>
            );
          })}
        </div>
      </div>

      <footer className="border-t border-line px-3.5 py-3">
        {dev.lastError ? (
          <div className="mb-2 text-2xs text-err">{dev.lastError}</div>
        ) : null}
        <div className="flex items-center gap-2.5">
          <Button
            variant="accent"
            small
            disabled={!dev.dirty || dev.saving}
            onClick={dev.save}
          >
            {dev.saving ? "Saving..." : "Save to source"}
          </Button>
          <button
            type="button"
            onClick={dev.resetAll}
            className="text-2xs text-t3 transition-colors hover:text-err"
          >
            Reset all
          </button>
          <span className="ml-auto text-2xs text-t3">{dev.dirty ? "Unsaved" : "Saved"}</span>
        </div>
      </footer>
    </aside>
  );
}
