/**
 * The dev-mode Design panel: a right-docked surface, shown only while dev mode is on
 * (Ctrl/Cmd+Shift+D). Rebuilt (Dev Mode v2) into the inspect-first CONTEXTUAL editor per
 * .planning/DEVMODE-UI.md: you select an element and the panel becomes the editor for exactly that
 * element. Top -> bottom it is Header (badge / theme / close) · Toolbar (Inspect · Show IDs · search)
 * · Selection pane (Selected id + used-token chips + scoped facet tabs) · Catalogue (collapsible) ·
 * Footer (Save / Reset / dirty). It renders nothing when dev mode is off, so it never touches the app.
 *
 * CRITICAL invariant (tested): no capability regresses. With NO selection the Tokens tab shows the
 * FULL grouped token list (every global token editable, today's behaviour) and the Copy tab still
 * edits every copy id; a selection merely SCOPES the Tokens tab to the element's used tokens (with a
 * "Show All" fallback) and points the Copy tab at the element's data-copy-id. Editing a token still
 * edits the GLOBAL token (setToken) and editing copy still edits the global copy (setCopy). The
 * token-row helpers (ColorRow/ScaleRow/ShadowRow) and CopyEditor are reused as-is, not rewritten.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useTheme } from "../lib/theme";
import { useDevMode } from "../lib/devMode";
import { DEV_TOKENS, DEV_TOKEN_GROUPS, DEFAULT_RANGE, type DevToken } from "../lib/devTokens";
import { DEV_IDS, DEV_ID_BY_ID, DEV_ID_AREAS } from "../lib/devIds";
import { usedVarsForElement } from "../lib/inspectVars";
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

// A slider + number for the length and number tokens (radii, type sizes, icon stroke). The unit
// (`px` for a length, none for a unitless number) and the slider bounds come from the token, so one
// row serves every scalar knob and a fractional step (type / stroke) works as well as an integer.
function ScaleRow({ token }: { token: DevToken }) {
  const dev = useDevMode();
  const value = dev.tokenValue(token.cssVar);
  const n = parseFloat(value) || 0;
  const overridden = dev.isTokenOverridden(token.cssVar);
  const { min, max, step } = token.range ?? DEFAULT_RANGE;
  const unit = token.kind === "length" ? "px" : "";
  const set = (raw: string) => dev.setToken(token.cssVar, `${raw}${unit}`);
  return (
    <div className="flex items-center gap-2 py-1">
      <span className="min-w-0 flex-1 truncate text-xs text-t2">{token.label}</span>
      {overridden ? <ResetDot onClick={() => dev.resetToken(token.cssVar)} /> : null}
      <input
        type="range"
        aria-label={`${token.label} slider`}
        min={min}
        max={max}
        step={step}
        value={n}
        onChange={(e) => set(e.target.value)}
        className="w-[104px] flex-none accent-acc"
      />
      <input
        type="number"
        aria-label={`${token.label} value`}
        min={min}
        max={max}
        step={step}
        value={n}
        onChange={(e) => set(e.target.value)}
        className="nospin tnum w-[52px] flex-none rounded-control border border-line bg-field px-2 py-1 text-2xs font-mono text-t1 outline-none focus:border-acc"
      />
    </div>
  );
}

// A raw text field for a shadow token (the box-shadow string is long and free-form, so a slider
// cannot serve it). Full width under the label; the aria-label carries a `shadow` suffix so an
// Elevation token named like a Surfaces colour (both "Card") stays uniquely addressable.
function ShadowRow({ token }: { token: DevToken }) {
  const dev = useDevMode();
  const value = dev.tokenValue(token.cssVar);
  const overridden = dev.isTokenOverridden(token.cssVar);
  return (
    <div className="py-1">
      <div className="flex items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-xs text-t2">{token.label}</span>
        {overridden ? <ResetDot onClick={() => dev.resetToken(token.cssVar)} /> : null}
      </div>
      <textarea
        aria-label={`${token.label} shadow`}
        value={value}
        rows={2}
        onChange={(e) => dev.setToken(token.cssVar, e.target.value)}
        className="mt-1 w-full resize-y rounded-control border border-line bg-field px-2 py-1 text-2xs font-mono leading-snug text-t1 outline-none focus:border-acc"
      />
    </div>
  );
}

// One token row for the Tokens tab, wrapping the kind-specific editor with a `data-var` handle (so
// the tab can scroll the first used row into view) and a highlighted style when it is a used token.
function TokenRow({ token, highlighted = false }: { token: DevToken; highlighted?: boolean }) {
  return (
    <div
      data-var={token.cssVar}
      className={highlighted ? "-mx-1.5 rounded-control bg-acc/[0.06] px-1.5" : undefined}
    >
      {token.kind === "color" ? (
        <ColorRow token={token} />
      ) : token.kind === "shadow" ? (
        <ShadowRow token={token} />
      ) : (
        <ScaleRow token={token} />
      )}
    </div>
  );
}

function CopyEditor() {
  const dev = useDevMode();
  if (!dev.selectedCopyId) {
    return (
      <div className="px-3.5 py-3 text-2xs text-t3">
        Click any underlined label in the app, or select an element with copy, to edit its text.
      </div>
    );
  }
  const id = dev.selectedCopyId;
  const current = dev.resolveCopy(id, dev.selectedCopyDefault);
  return (
    <div className="px-3.5 py-3">
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

type Facet = "tokens" | "copy" | "icon" | "box";

// A small pressed-state toolbar toggle (Inspect / Show IDs).
function ToggleButton({
  pressed,
  onClick,
  label,
}: {
  pressed: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      className={
        "rounded-control border px-2 py-1 text-2xs font-semibold transition-colors " +
        (pressed
          ? "border-transparent bg-acc text-acc-on"
          : "border-line text-t2 hover:text-t1")
      }
    >
      {label}
    </button>
  );
}

function Toolbar({ search, setSearch }: { search: string; setSearch: (s: string) => void }) {
  const dev = useDevMode();
  return (
    <div className="flex items-center gap-1.5 border-b border-line px-3.5 py-2">
      <ToggleButton pressed={dev.inspect} onClick={dev.toggleInspect} label="Inspect" />
      <ToggleButton pressed={dev.showIds} onClick={dev.toggleShowIds} label="Show IDs" />
      <input
        type="search"
        aria-label="Search ids"
        placeholder="Search"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="ml-auto w-[104px] flex-none rounded-control border border-line bg-field px-2 py-1 text-2xs text-t1 outline-none focus:border-acc"
      />
    </div>
  );
}

function FacetTab({
  id,
  active,
  onSelect,
  disabled = false,
  children,
}: {
  id: Facet;
  active: Facet;
  onSelect: (f: Facet) => void;
  disabled?: boolean;
  children: string;
}) {
  const selected = active === id;
  return (
    <button
      type="button"
      role="tab"
      aria-selected={selected}
      disabled={disabled}
      onClick={() => onSelect(id)}
      className={
        "rounded-control px-2.5 py-1 text-2xs font-semibold transition-colors " +
        (disabled
          ? "cursor-not-allowed text-t3 opacity-40"
          : selected
            ? "bg-raise2 text-t1"
            : "text-t3 hover:text-t2")
      }
    >
      {children}
    </button>
  );
}

// The Tokens facet: with a selection it shows only the used token rows (with a "Show All" fallback
// to the full grouped list); with no selection it shows the full grouped list, so global token
// editing is ALWAYS reachable (the no-capability-regress invariant).
function TokensTab({ showAll, setShowAll }: { showAll: boolean; setShowAll: (v: boolean) => void }) {
  const dev = useDevMode();
  const containerRef = useRef<HTMLDivElement>(null);
  const hasSelection = dev.selectedDevId != null;
  const used = dev.highlightedVars;
  const first = used[0];
  const scoped = hasSelection && !showAll;

  // Scroll the first used row into view when the selection's used tokens change.
  useEffect(() => {
    if (!scoped || !first) return;
    const row = containerRef.current?.querySelector(`[data-var="${first}"]`);
    (row as HTMLElement | null)?.scrollIntoView?.({ block: "nearest" });
  }, [scoped, first]);

  if (scoped) {
    const rows = DEV_TOKENS.filter((t) => used.includes(t.cssVar));
    return (
      <div ref={containerRef} className="px-3.5 py-2">
        {rows.length === 0 ? (
          <div className="py-2 text-2xs text-t3">This element uses no editable tokens.</div>
        ) : (
          rows.map((t) => <TokenRow key={t.cssVar} token={t} highlighted />)
        )}
        <button
          type="button"
          onClick={() => setShowAll(true)}
          className="mt-2 text-2xs font-semibold text-t2 hover:text-t1"
        >
          Show All
        </button>
      </div>
    );
  }

  return (
    <div ref={containerRef} className="px-3.5 py-2">
      {hasSelection ? (
        <button
          type="button"
          onClick={() => setShowAll(false)}
          className="mb-1 text-2xs font-semibold text-t2 hover:text-t1"
        >
          Show Used
        </button>
      ) : null}
      {DEV_TOKEN_GROUPS.map((group) => {
        const tokens = DEV_TOKENS.filter((t) => t.group === group);
        if (tokens.length === 0) return null;
        return (
          <section key={group} className="py-1.5">
            <div className="mb-0.5 text-2xs font-semibold uppercase tracking-[0.06em] text-t3">
              {group}
            </div>
            {tokens.map((t) => (
              <TokenRow
                key={t.cssVar}
                token={t}
                highlighted={hasSelection && used.includes(t.cssVar)}
              />
            ))}
          </section>
        );
      })}
    </div>
  );
}

// The Copy facet: derives the selected element's data-copy-id and drives the shared CopyEditor. The
// direct <Text> click path (which sets selectedCopyId with no selectedDevId) still works untouched.
function CopyTab() {
  const dev = useDevMode();
  const { selectedDevId, selectedCopyId, selectCopy, clearSelectedCopy } = dev;

  const copyId = useMemo(() => {
    if (!selectedDevId) return null;
    const el = document.querySelector(`[data-dev-id="${selectedDevId}"]`);
    if (!el) return null;
    const c = el.querySelector("[data-copy-id]") ?? el.closest("[data-copy-id]");
    return c?.getAttribute("data-copy-id") ?? null;
  }, [selectedDevId]);

  useEffect(() => {
    if (!selectedDevId) return; // the direct <Text> click owns selectedCopyId; leave it alone
    if (copyId && copyId !== selectedCopyId) {
      const el = document.querySelector(`[data-copy-id="${copyId}"]`);
      selectCopy(copyId, el?.textContent ?? "");
    } else if (!copyId && selectedCopyId) {
      clearSelectedCopy();
    }
  }, [selectedDevId, copyId, selectedCopyId, selectCopy, clearSelectedCopy]);

  return <CopyEditor />;
}

// The collapsible Catalogue: the 196 ids filtered by the toolbar search and grouped by area. Clicking
// an entry selects it and locates the live element (scrollIntoView + a transient flash outline).
function Catalogue({
  search,
  open,
  setOpen,
}: {
  search: string;
  open: boolean;
  setOpen: (v: boolean) => void;
}) {
  const dev = useDevMode();
  const q = search.trim().toLowerCase();
  const filtered = useMemo(
    () =>
      q === ""
        ? DEV_IDS
        : DEV_IDS.filter(
            (e) =>
              e.id.toLowerCase().includes(q) ||
              e.label.toLowerCase().includes(q) ||
              e.area.toLowerCase().includes(q),
          ),
    [q],
  );

  function locate(id: string) {
    dev.selectDevId(id);
    const el = document.querySelector(`[data-dev-id="${id}"]`);
    if (!el) {
      dev.selectVars([]);
      return;
    }
    dev.selectVars(usedVarsForElement(el));
    const node = el as HTMLElement;
    node.scrollIntoView?.({ block: "center", behavior: "smooth" });
    const prevOutline = node.style.outline;
    const prevOffset = node.style.outlineOffset;
    node.style.outline = "2px solid var(--c-acc)";
    node.style.outlineOffset = "2px";
    window.setTimeout(() => {
      node.style.outline = prevOutline;
      node.style.outlineOffset = prevOffset;
    }, 700);
  }

  return (
    <div className="border-t border-line">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-1.5 px-3.5 py-2 text-2xs font-semibold uppercase tracking-[0.06em] text-t3 hover:text-t2"
      >
        <span aria-hidden="true">{open ? "▾" : "▸"}</span>
        Catalogue
        <span className="ml-auto font-mono text-t3">{filtered.length}</span>
      </button>
      {open ? (
        <div className="px-3.5 pb-2">
          {DEV_ID_AREAS.map((area) => {
            const entries = filtered.filter((e) => e.area === area);
            if (entries.length === 0) return null;
            return (
              <section key={area} className="py-1">
                <div className="mb-0.5 text-2xs font-semibold uppercase tracking-[0.06em] text-t3">
                  {area}
                </div>
                {entries.map((e) => (
                  <button
                    key={e.id}
                    type="button"
                    onClick={() => locate(e.id)}
                    className={
                      "flex w-full items-baseline gap-1.5 rounded-control px-1.5 py-1 text-left transition-colors hover:bg-raise2 " +
                      (dev.selectedDevId === e.id ? "bg-raise2" : "")
                    }
                  >
                    <span className="flex-none font-mono text-[10px] text-t2">{e.id}</span>
                    <span className="ml-auto truncate text-2xs text-t3">{e.label}</span>
                  </button>
                ))}
              </section>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

function SelectionPane({
  facet,
  setFacet,
  showAll,
  setShowAll,
}: {
  facet: Facet;
  setFacet: (f: Facet) => void;
  showAll: boolean;
  setShowAll: (v: boolean) => void;
}) {
  const dev = useDevMode();
  const entry = dev.selectedDevId ? DEV_ID_BY_ID.get(dev.selectedDevId) : undefined;
  return (
    <div>
      <div className="border-b border-line px-3.5 py-2.5">
        <div className="flex items-baseline gap-1.5">
          <span className="text-2xs font-semibold uppercase tracking-[0.06em] text-t3">
            Selected
          </span>
          {dev.selectedDevId ? (
            <span className="min-w-0 truncate font-mono text-2xs text-t1">
              {"▸"} {dev.selectedDevId}
            </span>
          ) : (
            <span className="text-2xs text-t3">Nothing selected</span>
          )}
        </div>
        {entry ? (
          <div className="mt-0.5 text-2xs text-t2">
            {entry.label} <span className="text-t3">{"·"} {entry.area}</span>
          </div>
        ) : null}
        {dev.highlightedVars.length > 0 ? (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {dev.highlightedVars.map((v) => (
              <span
                key={v}
                className="rounded-[3px] bg-raise2 px-1 py-0.5 font-mono text-[9px] text-t2"
              >
                {v}
              </span>
            ))}
          </div>
        ) : null}
      </div>

      <div
        role="tablist"
        aria-label="Selection facets"
        className="flex items-center gap-1 border-b border-line px-3.5 py-1.5"
      >
        <FacetTab id="tokens" active={facet} onSelect={setFacet}>
          Tokens
        </FacetTab>
        <FacetTab id="copy" active={facet} onSelect={setFacet}>
          Copy
        </FacetTab>
        <FacetTab id="icon" active={facet} onSelect={setFacet} disabled>
          Icon
        </FacetTab>
        <FacetTab id="box" active={facet} onSelect={setFacet} disabled>
          Box
        </FacetTab>
      </div>

      {facet === "tokens" ? <TokensTab showAll={showAll} setShowAll={setShowAll} /> : null}
      {facet === "copy" ? <CopyTab /> : null}
    </div>
  );
}

export function DevPanel() {
  const dev = useDevMode();
  const { theme, setTheme } = useTheme();
  const [facet, setFacet] = useState<Facet>("tokens");
  const [search, setSearch] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [catalogueOpen, setCatalogueOpen] = useState(false);

  // A NEW copy selection (a direct <Text> click) surfaces the Copy tab, preserving the one-click-to
  // -edit-copy shortcut inside the new shell.
  const lastCopy = useRef<string | null>(dev.selectedCopyId);
  useEffect(() => {
    if (dev.selectedCopyId && dev.selectedCopyId !== lastCopy.current) {
      setFacet("copy");
    }
    lastCopy.current = dev.selectedCopyId;
  }, [dev.selectedCopyId]);

  // A new element selection lands the Tokens tab scoped (used view), not stuck on "Show All".
  useEffect(() => {
    setShowAll(false);
  }, [dev.selectedDevId]);

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

      <Toolbar search={search} setSearch={setSearch} />

      <div className="min-h-0 flex-1 overflow-y-auto">
        <SelectionPane
          facet={facet}
          setFacet={setFacet}
          showAll={showAll}
          setShowAll={setShowAll}
        />
        <Catalogue search={search} open={catalogueOpen} setOpen={setCatalogueOpen} />
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
