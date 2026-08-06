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
 *
 * Two capabilities the id system needs from this surface, added alongside the catalogue:
 *
 *  - The LIVE group in the Catalogue lists the dev ids currently in the document. A per-instance id
 *    belongs to a record, not to a fixed list, so the catalogue can never name the tab of the
 *    component that happens to be open; one search box now finds both halves.
 *  - The Box tab asks WHICH CONTRACT an edit is under when the selection has both identities: this
 *    one (its instance id) or every one of these (the shared role it declares). Guessing would make
 *    one of the two capabilities unreachable, and the wrong guess is destructive.
 *
 * The panel's own chrome comes from the shared design system (`SectionHeader`, `ModalActions`), but
 * its STRINGS deliberately do not go through the copy layer: this is the editor, and routing the
 * editor's labels through the surface it edits means one bad override can make it unusable.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useTheme } from "../lib/theme";
import { useDevMode } from "../lib/devMode";
import { DEV_TOKENS, DEV_TOKEN_GROUPS, DEFAULT_RANGE, type DevToken } from "../lib/devTokens";
import { DEV_IDS, DEV_ID_BY_ID, DEV_ID_AREAS } from "../lib/devIds";
import { usedVarsForElement } from "../lib/inspectVars";
import {
  devIdScope,
  nodeForDevId,
  renderedDevIds,
  sharedRoleOf,
} from "../lib/componentDevIds";
import {
  containerLayoutOf,
  gridColumnsOf,
  isValidGridSlot,
  isValidOrder,
  isSafeElementValue,
  reorderSiblings,
  reorderSiblingsOf,
} from "../lib/elementLayout";
import { copyOverrideProblem, copyPlaceholders } from "../lib/copyPlaceholders";
import { Button } from "./primitives";
// The Interface Studio is part of the product, so its own chrome comes from the shared design
// system rather than from a private set of class strings that drift away from it.
import { SectionHeader } from "./productState";
import { ModalActions } from "./modalParts";
import { Icon } from "./Icon";
import { resolveIcon, sanitizeIconBody } from "./iconResolve";
import { ICON_BY_ID, ICON_IDS_BY_CATEGORY } from "../lib/iconRegistry";
import { api, ApiError } from "../api/client";
import type { DevWorkspaceStatus } from "../api/types";

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
      {/* D-06: DevPanel's own reset dot draws through <Icon> (the exact h-3 w-3 the inline svg carried,
          the weight/caps live on the dev.reset registry entry), so the panel's icons are inspectable. */}
      <Icon id="dev.reset" className="h-3 w-3" />
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

// What a placeholder problem means, in the words of the person who has to fix it. The reason lines
// are the panel's own chrome (see the Copy tab comment): they describe the editor, not the product.
const COPY_PROBLEM_TEXT: Record<string, string> = {
  malformed: "This uses a brace that is not a placeholder. Write each value as {name}.",
  "missing-placeholder": "This drops a placeholder the default needs, so its value would vanish.",
  "unknown-placeholder": "This uses a placeholder with no value behind it.",
};

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
  const defaultText = dev.selectedCopyDefault;
  const current = dev.resolveCopy(id, defaultText);
  // Validate the WORKING text against the default's declared placeholder set, so the problem is
  // named while it is being typed rather than as a 400 after Save. The render path independently
  // falls back to the default, so a saved-anyway mistake is still not a broken screen.
  const problem = current === defaultText ? null : copyOverrideProblem(defaultText, current);
  const required = copyPlaceholders(defaultText) ?? [];
  return (
    <div className="px-3.5 py-3">
      <SectionHeader
        title="Copy"
        className="mb-1.5"
        action={
          <button
            type="button"
            onClick={dev.clearSelectedCopy}
            className="text-2xs font-semibold text-t2 hover:text-t1"
          >
            Done
          </button>
        }
      />
      <div className="mb-1.5 truncate font-mono text-2xs text-t3" title={id}>
        {id}
      </div>
      <textarea
        aria-label="Edit copy text"
        value={current}
        rows={2}
        onChange={(e) => dev.setCopy(id, e.target.value)}
        className={
          "w-full resize-y rounded-control border bg-field px-2 py-1.5 text-sm text-t1 outline-none " +
          (problem ? "border-err focus:border-err" : "border-line2 focus:border-acc")
        }
      />
      {required.length > 0 ? (
        <div className="mt-1 font-mono text-2xs text-t3">
          Keep: {required.map((name) => `{${name}}`).join(" ")}
        </div>
      ) : null}
      {problem ? (
        <div role="alert" className="mt-1 text-2xs leading-relaxed text-err-text">
          {COPY_PROBLEM_TEXT[problem]} The default is shown until this is fixed.
        </div>
      ) : null}
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

type Facet = "tokens" | "copy" | "icon" | "box" | "behavior";

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
    <div className="flex shrink-0 items-center gap-1.5 border-b border-line px-3.5 py-2">
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
  // Membership is asked once per token row, for every token in every group, on every render of the
  // panel; the answer set is the selection's own variable list. One Set per selection change
  // replaces a full scan of that list per row.
  const usedVars = useMemo(() => new Set(used), [used]);
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
            <SectionHeader title={group} className="mb-1" />
            {tokens.map((t) => (
              <TokenRow
                key={t.cssVar}
                token={t}
                highlighted={hasSelection && usedVars.has(t.cssVar)}
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
    const el = nodeForDevId(selectedDevId);
    if (!el) return null;
    const c = el.querySelector("[data-copy-id]") ?? el.closest("[data-copy-id]");
    return c?.getAttribute("data-copy-id") ?? null;
  }, [selectedDevId]);

  useEffect(() => {
    if (!selectedDevId) return; // the direct <Text> click owns selectedCopyId; leave it alone
    if (copyId && copyId !== selectedCopyId) {
      const el = document.querySelector(`[data-copy-id="${CSS.escape(copyId)}"]`);
      // The raw TEMPLATE, not the rendered text: reading textContent back would bake this render's
      // substituted values into the default and make every placeholder look like a missing one.
      const template = el?.getAttribute("data-copy-default") ?? el?.textContent ?? "";
      selectCopy(copyId, template);
    } else if (!copyId && selectedCopyId) {
      clearSelectedCopy();
    }
  }, [selectedDevId, copyId, selectedCopyId, selectCopy, clearSelectedCopy]);

  return <CopyEditor />;
}

// The Icon facet (D-04): mirrors CopyTab. From the selection it derives the icon id (its
// `data-icon-id`, emitted by <Icon> in dev mode per plan 01 - the icon analog of CopyTab's
// data-copy-id), and edits what the glyph IS: (a) a same-category glyph PICKER that writes a
// swapToId, and (b) a raw-SVG EDITOR whose textarea drives a live preview through the same
// sanitizeIconBody the <Icon> uses (D-05: the frontend sanitises before preview; the backend is the
// authority on what ships). Per D-03 raw editing is offered only for the line-icon categories
// (primary + bespoke); art + brand are swap-only (their multi-group / fill markup is riskier to hand
// -edit). With no icon in the selection it shows an empty state, mirroring the Copy tab.
function IconTab() {
  const dev = useDevMode();
  const { selectedDevId } = dev;

  const iconId = useMemo(() => {
    if (!selectedDevId) return null;
    const el = nodeForDevId(selectedDevId);
    if (!el) return null;
    const i =
      (el.matches("[data-icon-id]") ? el : null) ??
      el.querySelector("[data-icon-id]") ??
      el.closest("[data-icon-id]");
    return i?.getAttribute("data-icon-id") ?? null;
  }, [selectedDevId]);

  if (!iconId) {
    return (
      <div className="px-3.5 py-3 text-2xs text-t3">
        Select an element that is or contains an icon to swap its glyph or edit its SVG.
      </div>
    );
  }

  const entry = ICON_BY_ID.get(iconId);
  if (!entry) {
    return (
      <div className="px-3.5 py-3 text-2xs text-t3">
        No registry glyph for <span className="font-mono">{iconId}</span>.
      </div>
    );
  }

  const overridden = dev.isIconOverridden(iconId);
  // The glyph this id currently resolves to after any swap chain, so the picker can mark it (D-04).
  const resolvedTarget = resolveIcon(iconId, dev.resolveIconOverride)?.entry.id ?? iconId;
  // The working body the raw editor edits (an override body if set, else the registry default).
  const draftBody = dev.iconOverrideFor(iconId)?.body ?? entry.body;
  // D-03: raw SVG editing is offered only for the line-icon categories; art/brand stay swap-only.
  const rawEditable = entry.category === "primary" || entry.category === "bespoke";
  const pickerIds = ICON_IDS_BY_CATEGORY[entry.category];

  return (
    <div className="px-3.5 py-3">
      <SectionHeader
        title="Icon"
        className="mb-1.5"
        action={
          overridden ? (
            <button
              type="button"
              onClick={() => dev.resetIcon(iconId)}
              className="text-2xs text-t3 hover:text-t1"
            >
              Reset to default
            </button>
          ) : undefined
        }
      />
      <div className="mb-2 truncate font-mono text-2xs text-t3" title={iconId}>
        {iconId}
      </div>

      {/* (a) the glyph PICKER: swap to another same-category registry glyph (D-04). */}
      <div className="mb-1 text-2xs font-semibold text-t2">Swap Glyph</div>
      <div className="mb-3 grid grid-cols-6 gap-1">
        {pickerIds.map((pid) => {
          const active = pid === resolvedTarget;
          return (
            <button
              key={pid}
              type="button"
              aria-label={`Swap to ${pid}`}
              aria-pressed={active}
              title={pid}
              onClick={() => dev.setIconSwap(iconId, pid)}
              className={
                "grid aspect-square place-items-center rounded-control border text-t2 transition-colors hover:text-t1 " +
                (active ? "border-acc bg-acc/[0.08] text-t1" : "border-line hover:bg-raise2")
              }
            >
              <Icon id={pid} className="h-4 w-4" />
            </button>
          );
        })}
      </div>

      {/* (b) the raw-SVG EDITOR: the icon body + a live, sanitiser-vetted preview (D-04 / D-05). The
          preview renders sanitizeIconBody(draft) through the entry's own frame, so what the owner
          sees is exactly what the sanitiser will keep. Restricted to line icons (D-03). */}
      {rawEditable ? (
        <div>
          <div className="mb-1 flex items-center justify-between">
            <span className="text-2xs font-semibold text-t2">Edit SVG</span>
            <span
              className="grid h-7 w-7 flex-none place-items-center rounded-control border border-line2 bg-field text-t1"
              title="Live preview (sanitised)"
            >
              <svg
                data-testid="icon-preview"
                viewBox={entry.viewBox}
                className="h-5 w-5"
                fill={entry.fill ?? "none"}
                stroke={entry.stroke ?? "currentColor"}
                strokeWidth={entry.strokeWidth}
                strokeLinecap={entry.strokeLinecap ?? "round"}
                strokeLinejoin={entry.strokeLinejoin ?? "round"}
                style={entry.style}
                aria-hidden="true"
                dangerouslySetInnerHTML={{ __html: sanitizeIconBody(draftBody) }}
              />
            </span>
          </div>
          <textarea
            aria-label="Edit icon SVG body"
            value={draftBody}
            rows={4}
            onChange={(e) => dev.setIconBody(iconId, e.target.value)}
            className="w-full resize-y rounded-control border border-line2 bg-field px-2 py-1.5 text-2xs font-mono leading-snug text-t1 outline-none focus:border-acc"
          />
        </div>
      ) : (
        <div className="text-2xs text-t3">
          This glyph is swap only. Its SVG is edited in the registry, not here.
        </div>
      )}
    </div>
  );
}

// The ELEM-02 first-cut whitelist (D-03): the box properties the [Box] tab exposes as labelled rows.
// ORDER / GRID-COLUMN / GRID-ROW are deliberately EXCLUDED here (Phase F / layout), even though the
// backend already accepts them. Labels are Title Case per the design contract; each `prop` is the raw
// kebab CSS property the runtime applies via `el.style.setProperty(prop, value)` (min-width -> minWidth).
const BOX_RESIZE_PROPS: readonly { prop: string; label: string }[] = [
  { prop: "width", label: "Width" },
  { prop: "height", label: "Height" },
  { prop: "min-width", label: "Min Width" },
  { prop: "min-height", label: "Min Height" },
  { prop: "max-width", label: "Max Width" },
  { prop: "max-height", label: "Max Height" },
];
const BOX_SPACING_PROPS: readonly { prop: string; label: string }[] = [
  { prop: "margin", label: "Margin" },
  { prop: "margin-top", label: "Margin Top" },
  { prop: "margin-right", label: "Margin Right" },
  { prop: "margin-bottom", label: "Margin Bottom" },
  { prop: "margin-left", label: "Margin Left" },
  { prop: "padding", label: "Padding" },
  { prop: "padding-top", label: "Padding Top" },
  { prop: "padding-right", label: "Padding Right" },
  { prop: "padding-bottom", label: "Padding Bottom" },
  { prop: "padding-left", label: "Padding Left" },
  { prop: "gap", label: "Gap" },
];
const BOX_APPEARANCE_PROPS: readonly { prop: string; label: string }[] = [
  { prop: "display", label: "Display" },
  { prop: "visibility", label: "Visibility" },
  { prop: "opacity", label: "Opacity" },
  { prop: "color", label: "Text Color" },
  { prop: "background-color", label: "Fill Color" },
  { prop: "border-color", label: "Border Color" },
  { prop: "border-radius", label: "Corner Radius" },
  { prop: "font-size", label: "Font Size" },
  { prop: "font-weight", label: "Font Weight" },
  { prop: "line-height", label: "Line Height" },
  { prop: "letter-spacing", label: "Letter Spacing" },
  { prop: "text-align", label: "Text Align" },
];
const BOX_ALIGNMENT_PROPS: readonly { prop: string; label: string }[] = [
  { prop: "flex-direction", label: "Direction" },
  { prop: "flex-wrap", label: "Wrap" },
  { prop: "justify-content", label: "Justify" },
  { prop: "align-items", label: "Align Items" },
  { prop: "align-content", label: "Align Content" },
];

// One box-property row (D-04): reuses the ColorRow/ScaleRow shape - a truncating label, an optional
// ResetDot, and the mono value field styled like the token fields. The field's value is the working
// override (empty when none), its placeholder is the element's live computed value for the property,
// and editing writes the override live (an emptied field removes the override, mirroring per-prop reset).
function BoxRow({
  id,
  prop,
  label,
  placeholder,
}: {
  id: string;
  prop: string;
  label: string;
  placeholder: string;
}) {
  const dev = useDevMode();
  const value = dev.elementOverridesFor(id)?.[prop] ?? "";
  const overridden = dev.isElementPropOverridden(id, prop);
  // A value outside the safe grammar is marked, not swallowed: it stays in the field so it can be
  // corrected, it is never applied by the runtime, and Save drops it rather than earning a 400.
  const invalid = value !== "" && !isSafeElementValue(prop, value);
  return (
    <div className="flex items-center gap-2 py-1">
      <span className="min-w-0 flex-1 truncate text-xs text-t2">{label}</span>
      {overridden ? <ResetDot onClick={() => dev.resetElementProp(id, prop)} /> : null}
      <input
        type="text"
        aria-label={`${label} value`}
        aria-invalid={invalid || undefined}
        title={invalid ? `${label} does not accept this value, so it will not be saved.` : undefined}
        value={value}
        placeholder={placeholder}
        onChange={(e) => {
          const next = e.target.value;
          // Clearing the text removes the override, so the token/class styling underneath re-emerges.
          if (next === "") dev.resetElementProp(id, prop);
          else dev.setElementProp(id, prop, next);
        }}
        className={
          "tnum w-[104px] flex-none rounded-control border bg-field px-2 py-1 text-2xs font-mono text-t1 outline-none " +
          (invalid ? "border-err focus:border-err" : "border-line focus:border-acc")
        }
      />
    </div>
  );
}

// The slot values the grid picker offers for a container with `cols` column tracks: `auto` (the
// default, which clears the override), each 1-based line position 1..cols, and a `span N` for 2..cols.
// Every option passes isValidGridSlot, so the picker can never emit a value the backend writer rejects.
function gridSlotOptions(cols: number): string[] {
  const opts = ["auto"];
  for (let i = 1; i <= cols; i++) opts.push(String(i));
  for (let s = 2; s <= cols; s++) opts.push(`span ${s}`);
  return opts;
}

// One grid-slot control (Phase F / LAYOUT-01): a select of derived line / span positions for a single
// grid property (grid-column or grid-row) on the selected element. Choosing `auto` clears the override
// (the grid's own flow re-emerges); any other choice writes the validated slot value live through Phase
// E's per-element setter (the same map that applies inline by id and ships in the save `elements` block).
// The current committed / working value is preselected, and shown as an option even if it is outside the
// derived set (a hand-committed value stays visible rather than silently snapping to auto).
function GridSlotControl({
  id,
  prop,
  label,
  cols,
}: {
  id: string;
  prop: string;
  label: string;
  cols: number;
}) {
  const dev = useDevMode();
  const current = dev.elementOverridesFor(id)?.[prop] ?? "auto";
  const options = gridSlotOptions(cols);
  const opts = options.includes(current) ? options : [current, ...options];
  return (
    <div className="flex items-center gap-2 py-1">
      <span className="min-w-0 flex-1 truncate text-xs text-t2">{label}</span>
      <select
        aria-label={label}
        value={current}
        onChange={(e) => {
          const v = e.target.value;
          // `auto` is the grid default: clear the override so the container's own flow returns.
          if (v === "auto") dev.resetElementProp(id, prop);
          else if (isValidGridSlot(v)) dev.setElementProp(id, prop, v);
        }}
        className="w-[104px] flex-none rounded-control border border-line bg-field px-2 py-1 text-2xs font-mono text-t1 outline-none focus:border-acc"
      >
        {opts.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </div>
  );
}

// The Layout section (Phase F / LAYOUT-01): reorder the selected element among its container siblings
// via CSS `order`, keyed by data-dev-id. Renders only when the selection sits in a flex/grid container
// (className-detected) with at least two dev-id siblings - otherwise there is nothing to reorder and it
// renders null, so the Box tab is unchanged for elements outside a layout container. The current VISUAL
// sequence is derived by sorting the DOM-order siblings by their live `order` override (ties by DOM
// index), so each Move Up / Move Down walks the element exactly one step; the recomputed order values
// are written through Phase E's per-element setter (the same map that applies inline by id and ships in
// the save `elements` block) - no new persistence path, no reparenting.
function LayoutSection({ id }: { id: string }) {
  const dev = useDevMode();
  const node = nodeForDevId(id);
  if (!node) return null;
  const layout = containerLayoutOf(node.parentElement);
  if (layout === "none") return null;
  const siblings = reorderSiblingsOf(node);
  if (siblings.length < 2) return null;

  // Current visual sequence: DOM-order siblings sorted by their effective `order` (unset = 0), ties by
  // DOM index. Reads the live working override so a prior reorder is reflected before the next step.
  const orderedIds = siblings
    .map((el, domIndex) => {
      const sid = el.getAttribute("data-dev-id") ?? "";
      const ov = dev.elementOverridesFor(sid)?.order;
      const order = ov != null ? parseInt(ov, 10) : 0;
      return { sid, order, domIndex };
    })
    .sort((a, b) => a.order - b.order || a.domIndex - b.domIndex)
    .map((o) => o.sid);

  const move = (direction: "up" | "down") => {
    const next = reorderSiblings(orderedIds, id, direction);
    // Only write values that pass the backend `order` grammar, so the panel never emits a doomed value.
    for (const [sid, order] of Object.entries(next)) {
      if (isValidOrder(order)) dev.setElementProp(sid, "order", order);
    }
  };

  // Reset order clears ONLY the `order` override on every sibling (leaving size/spacing intact), so the
  // container returns to its original DOM order with no order entries left in the map.
  const resetOrder = () => {
    for (const sid of orderedIds) dev.resetElementProp(sid, "order");
  };
  const anyOrder = orderedIds.some((sid) => dev.isElementPropOverridden(sid, "order"));

  // Grid child (decision 1b): the selection sits in a grid container, so it may also be reassigned to a
  // grid slot. The column / row controls derive their positions from the container's grid-cols-N count;
  // Reset slot clears ONLY grid-column / grid-row for THIS element (order / size / spacing untouched).
  const isGridChild = layout === "grid";
  const cols = isGridChild ? gridColumnsOf(node.parentElement) : 0;
  const resetSlot = () => {
    dev.resetElementProp(id, "grid-column");
    dev.resetElementProp(id, "grid-row");
  };
  const anySlot =
    dev.isElementPropOverridden(id, "grid-column") || dev.isElementPropOverridden(id, "grid-row");

  return (
    <section className="py-1.5">
      <SectionHeader title="Layout" className="mb-1" />
      <div className="flex items-center gap-2 py-1">
        <button
          type="button"
          onClick={() => move("up")}
          className="rounded-control border border-line px-2 py-1 text-2xs font-semibold text-t2 transition-colors hover:text-t1"
        >
          Move Up
        </button>
        <button
          type="button"
          onClick={() => move("down")}
          className="rounded-control border border-line px-2 py-1 text-2xs font-semibold text-t2 transition-colors hover:text-t1"
        >
          Move Down
        </button>
      </div>
      {anyOrder ? (
        <button
          type="button"
          onClick={resetOrder}
          className="mt-1 text-2xs font-semibold text-t2 hover:text-t1"
        >
          Reset Order
        </button>
      ) : null}
      {isGridChild ? (
        <div className="mt-1.5">
          <SectionHeader title="Grid Slot" className="mb-1" />
          <GridSlotControl id={id} prop="grid-column" label="Grid Column" cols={cols} />
          <GridSlotControl id={id} prop="grid-row" label="Grid Row" cols={cols} />
          {anySlot ? (
            <button
              type="button"
              onClick={resetSlot}
              className="mt-1 text-2xs font-semibold text-t2 hover:text-t1"
            >
              Reset Slot
            </button>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

// The Box facet (D-04, ELEM-02): the owner-facing editing surface for the per-element escape hatch.
// For the selected element it renders a labelled RESIZE + SPACING control per whitelisted property,
// each editing the element's override live through the Plan 01 dev-mode API, with a per-property reset,
// a clear-all-for-this-element, and the element's current computed value as each field's placeholder.
// With no selection it shows an empty state, mirroring the Copy / Icon tabs.
function BoxTab() {
  const dev = useDevMode();
  const { selectedDevId } = dev;
  // Which contract the edit is written under. `instance` keys the override on the selected element's
  // own id; `shared` keys it on the role it declares, which reaches every sibling carrying that role.
  const [scope, setScope] = useState<"instance" | "shared">("instance");

  // Resolve the live node once and read its computed style for the placeholders. A catalogue id with
  // no mounted element (a null node) falls back to empty placeholders. getComputedStyle is a live view,
  // so a placeholder reflects the element's current value even after an override is cleared.
  const node = useMemo(() => (selectedDevId ? nodeForDevId(selectedDevId) : null), [selectedDevId]);
  const computed = useMemo(() => (node ? getComputedStyle(node) : null), [node]);
  const role = sharedRoleOf(node);

  // A new selection starts on its own instance, never on whatever scope the last one was left in.
  useEffect(() => {
    setScope("instance");
  }, [selectedDevId]);

  if (!selectedDevId) {
    return (
      <div className="px-3.5 py-3 text-2xs text-t3">
        Select an element to override its box size and spacing.
      </div>
    );
  }

  const isInstance = devIdScope(selectedDevId) === "instance";
  const targetId = scope === "shared" && role ? role : selectedDevId;
  const overrides = dev.elementOverridesFor(targetId);
  const hasAny = overrides != null && Object.keys(overrides).length > 0;
  const placeholderFor = (prop: string) => computed?.getPropertyValue(prop) ?? "";
  const applyPreset = (preset: "fill" | "hide" | "row" | "stack" | "wrap") => {
    if (preset === "fill") dev.setElementProp(targetId, "width", "100%");
    if (preset === "hide") dev.setElementProp(targetId, "display", "none");
    if (preset === "row") {
      dev.setElementProp(targetId, "display", "flex");
      dev.setElementProp(targetId, "flex-direction", "row");
      dev.setElementProp(targetId, "align-items", "center");
    }
    if (preset === "stack") {
      dev.setElementProp(targetId, "display", "flex");
      dev.setElementProp(targetId, "flex-direction", "column");
    }
    if (preset === "wrap") {
      dev.setElementProp(targetId, "display", "flex");
      dev.setElementProp(targetId, "flex-wrap", "wrap");
    }
  };

  return (
    <div className="px-3.5 py-2">
      {/* The instance / shared choice, only where there IS one. An element that names a role as well
          as itself can be edited either way, and which one is meant is a decision, not a guess. */}
      {isInstance && role ? (
        <section className="py-1.5">
          <SectionHeader title="Applies To" className="mb-1" />
          <div className="flex gap-1">
            <button
              type="button"
              aria-pressed={scope === "instance"}
              onClick={() => setScope("instance")}
              className={
                "rounded-control border px-2 py-1 text-2xs font-semibold transition-colors " +
                (scope === "instance"
                  ? "border-transparent bg-acc text-acc-on"
                  : "border-line text-t2 hover:text-t1")
              }
            >
              This One
            </button>
            <button
              type="button"
              aria-pressed={scope === "shared"}
              onClick={() => setScope("shared")}
              className={
                "rounded-control border px-2 py-1 text-2xs font-semibold transition-colors " +
                (scope === "shared"
                  ? "border-transparent bg-acc text-acc-on"
                  : "border-line text-t2 hover:text-t1")
              }
            >
              Every One Of These
            </button>
          </div>
          <div className="mt-1 truncate font-mono text-2xs text-t3" title={targetId}>
            {targetId}
          </div>
        </section>
      ) : null}
      <section className="py-1.5">
        <SectionHeader title="Presets" className="mb-1" />
        <div className="flex flex-wrap gap-1">
          {([[
            "fill", "Fill Width"], ["row", "Row"], ["stack", "Stack"], ["wrap", "Wrap"], ["hide", "Hide"]] as const).map(([preset, label]) => (
            <button key={preset} type="button" onClick={() => applyPreset(preset)} className="rounded-control border border-line bg-field px-2 py-1 text-2xs font-semibold text-t2 hover:text-t1">
              {label}
            </button>
          ))}
        </div>
      </section>
      <section className="py-1.5">
        <SectionHeader title="Resize" className="mb-1" />
        {BOX_RESIZE_PROPS.map((p) => (
          <BoxRow
            key={p.prop}
            id={targetId}
            prop={p.prop}
            label={p.label}
            placeholder={placeholderFor(p.prop)}
          />
        ))}
      </section>
      <section className="py-1.5">
        <SectionHeader title="Spacing" className="mb-1" />
        {BOX_SPACING_PROPS.map((p) => (
          <BoxRow
            key={p.prop}
            id={targetId}
            prop={p.prop}
            label={p.label}
            placeholder={placeholderFor(p.prop)}
          />
        ))}
      </section>
      <section className="py-1.5">
        <SectionHeader title="Appearance And Type" className="mb-1" />
        {BOX_APPEARANCE_PROPS.map((p) => (
          <BoxRow key={p.prop} id={targetId} prop={p.prop} label={p.label} placeholder={placeholderFor(p.prop)} />
        ))}
      </section>
      <section className="py-1.5">
        <SectionHeader title="Container Alignment" className="mb-1" />
        {BOX_ALIGNMENT_PROPS.map((p) => (
          <BoxRow key={p.prop} id={targetId} prop={p.prop} label={p.label} placeholder={placeholderFor(p.prop)} />
        ))}
      </section>
      <LayoutSection id={targetId} />
      {hasAny ? (
        <button
          type="button"
          onClick={() => dev.clearElement(targetId)}
          className="mt-2 text-2xs font-semibold text-t2 hover:text-t1"
        >
          Clear All
        </button>
      ) : null}
    </div>
  );
}

// Module scope: the preset table reads nothing local, so it is allocated once rather than on every
// selection change.
const BEHAVIOR_PRESETS = [
  ["dropdown", "Dropdown"],
  ["segmented", "Segmented Control"],
  ["radio", "Radio Group"],
  ["searchable", "Searchable Picker"],
] as const;

function BehaviorTab() {
  const dev = useDevMode();
  const id = dev.selectedDevId;
  if (!id) return <div className="px-3.5 py-3 text-2xs text-t3">Select a control to edit its behavior.</div>;
  const node = nodeForDevId(id);
  if (!node?.hasAttribute("data-dev-control")) {
    return (
      <div className="px-3.5 py-3 text-2xs leading-relaxed text-t3">
        This element has visual controls. Behavior presets appear for semantic controls whose value
        contract can be preserved safely.
      </div>
    );
  }
  const current = dev.behaviorOverrideFor(id);
  return (
    <div className="px-3.5 py-3">
      <SectionHeader title="Control Preset" className="mb-1" />
      <div className="grid grid-cols-2 gap-1.5">
        {BEHAVIOR_PRESETS.map(([preset, label]) => (
          <button
            key={preset}
            type="button"
            aria-pressed={(current?.preset ?? "dropdown") === preset}
            onClick={() => dev.setBehaviorOverride(id, { preset })}
            className={
              "rounded-control border px-2 py-2 text-left text-xs transition-colors " +
              ((current?.preset ?? "dropdown") === preset
                ? "border-acc bg-acc-soft text-t1"
                : "border-line bg-field text-t2 hover:text-t1")
            }
          >
            {label}
          </button>
        ))}
      </div>
      <label className="mt-3 flex items-center justify-between gap-3 text-xs text-t2">
        Disabled
        <input
          type="checkbox"
          checked={current?.disabled === true}
          onChange={(event) => dev.setBehaviorOverride(id, { disabled: event.target.checked })}
          className="accent-[var(--c-acc)]"
        />
      </label>
      {current ? (
        <button type="button" onClick={() => dev.resetBehaviorOverride(id)} className="mt-3 text-2xs font-semibold text-t2 hover:text-t1">
          Reset Behavior
        </button>
      ) : null}
    </div>
  );
}

/**
 * Select one id and put its element in front of the person.
 *
 * Resolution goes through `nodeForDevId`, so an INSTANCE id lands on the exact element it names
 * rather than on the first sibling that happens to share a prefix, and an id carrying a quote or a
 * bracket is a clean miss instead of a thrown selector.
 */
function locateDevId(id: string, select: (id: string) => void, vars: (v: string[]) => void) {
  select(id);
  const node = nodeForDevId(id);
  if (!node) {
    vars([]);
    return;
  }
  vars(usedVarsForElement(node));
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

// The collapsible Catalogue: all registered ids filtered by the toolbar search and grouped by area. Clicking
// an entry selects it and locates the live element (scrollIntoView + a transient flash outline).
//
// The catalogue alone cannot answer "what can I edit right now": a per-instance id belongs to a
// record, not to a fixed list, so the tab of the component that is open has no row here and never
// will. The LIVE group above the areas closes that gap by enumerating the dev ids actually in the
// document, so one search box finds both halves of the id system.
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

  // Re-enumerated whenever the panel opens, the search changes or the selection moves: the live set
  // changes as the app does, and a stale list would point at elements that are no longer there.
  const live = useMemo(() => {
    if (!open) return [];
    const dynamic = renderedDevIds().filter((id) => devIdScope(id) === "instance");
    return q === "" ? dynamic : dynamic.filter((id) => id.toLowerCase().includes(q));
  }, [open, q, dev.selectedDevId]);

  function locate(id: string) {
    locateDevId(id, dev.selectDevId, dev.selectVars);
  }

  return (
    <div className="border-t border-line">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-1.5 px-3.5 py-2 ui-property-label hover:text-t2"
      >
        <span aria-hidden="true">{open ? "▾" : "▸"}</span>
        Catalogue
        <span className="ml-auto font-mono text-t3">{filtered.length + live.length}</span>
      </button>
      {open ? (
        <div className="px-3.5 pb-2">
          {live.length > 0 ? (
            <section className="py-1" data-testid="dev-live-ids">
              <SectionHeader title="live" className="mb-1" />
              {live.map((id) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => locate(id)}
                  className={
                    "flex w-full items-baseline gap-1.5 rounded-control px-1.5 py-1 text-left transition-colors hover:bg-raise2 " +
                    (dev.selectedDevId === id ? "bg-raise2" : "")
                  }
                >
                  <span className="min-w-0 truncate font-mono text-xs text-t2">{id}</span>
                </button>
              ))}
            </section>
          ) : null}
          {DEV_ID_AREAS.map((area) => {
            const entries = filtered.filter((e) => e.area === area);
            if (entries.length === 0) return null;
            return (
              <section key={area} className="py-1">
                <SectionHeader title={area} className="mb-1" />
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
                    <span className="flex-none font-mono text-xs text-t2">{e.id}</span>
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
  const [copied, setCopied] = useState(false);
  const selectedId = dev.selectedDevId;

  useEffect(() => {
    setCopied(false);
  }, [selectedId]);

  // Copy ID hands back the EXACT id, brackets and all - it is the string an override is keyed on and
  // the string a test selects by, so a prettified or truncated form would be worse than useless.
  // Clipboard access can be denied or absent (an embedded webview, a jsdom test); the fallback keeps
  // the id selectable rather than pretending the copy happened.
  async function copyId() {
    if (!selectedId) return;
    try {
      await navigator.clipboard?.writeText(selectedId);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div>
      <div className="border-b border-line px-3.5 py-2.5">
        <div className="flex items-baseline gap-1.5">
          <span className="ui-property-label">
            Selected
          </span>
          {selectedId ? (
            <span
              data-testid="dev-selected-id"
              className="min-w-0 truncate font-mono text-2xs text-t1"
              title={selectedId}
            >
              {"▸"} {selectedId}
            </span>
          ) : (
            <span className="text-2xs text-t3">Nothing selected</span>
          )}
          {selectedId ? (
            <button
              type="button"
              aria-label="Copy ID"
              onClick={copyId}
              className="ml-auto flex-none rounded-control border border-line px-1.5 py-0.5 text-2xs font-semibold text-t2 transition-colors hover:text-t1"
            >
              {copied ? "Copied" : "Copy ID"}
            </button>
          ) : null}
        </div>
        {entry ? (
          <div className="mt-0.5 text-2xs text-t2">
            {entry.label} <span className="text-t3">{"·"} {entry.area}</span>
          </div>
        ) : null}
        {!entry && selectedId && devIdScope(selectedId) === "instance" ? (
          <div className="mt-0.5 text-2xs text-t2">
            One instance <span className="text-t3">{"·"} edits here leave its siblings alone</span>
          </div>
        ) : null}
        {dev.highlightedVars.length > 0 ? (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {dev.highlightedVars.map((v) => (
              <span
                key={v}
                className="rounded-[3px] bg-raise2 px-1 py-0.5 font-mono text-2xs text-t2"
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
        <FacetTab id="icon" active={facet} onSelect={setFacet}>
          Icon
        </FacetTab>
        <FacetTab id="box" active={facet} onSelect={setFacet}>
          Box
        </FacetTab>
        <FacetTab id="behavior" active={facet} onSelect={setFacet}>Behavior</FacetTab>
      </div>

      {facet === "tokens" ? <TokensTab showAll={showAll} setShowAll={setShowAll} /> : null}
      {facet === "copy" ? <CopyTab /> : null}
      {facet === "icon" ? <IconTab /> : null}
      {facet === "box" ? <BoxTab /> : null}
      {facet === "behavior" ? <BehaviorTab /> : null}
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
  const [publishOpen, setPublishOpen] = useState(false);
  const [publishMessage, setPublishMessage] = useState("Refine Stockroom interface");
  const [publishing, setPublishing] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);
  const [publishedCommit, setPublishedCommit] = useState("");
  const [publishStatus, setPublishStatus] = useState<DevWorkspaceStatus | null>(null);

  useEffect(() => {
    if (!dev.enabled || dev.dirty || dev.saving) {
      setPublishStatus(null);
      return;
    }
    let current = true;
    api.devStatus()
      .then((status) => {
        if (current) setPublishStatus(status);
      })
      .catch(() => {
        if (current) setPublishStatus(null);
      });
    return () => {
      current = false;
    };
  }, [dev.enabled, dev.dirty, dev.saving, publishedCommit]);

  async function publish() {
    setPublishing(true);
    setPublishError(null);
    setPublishedCommit("");
    try {
      if (dev.dirty) throw new Error("Save the current design to source before publishing.");
      const status = await api.devStatus();
      if (!status.available) throw new Error("This app is not running from a managed source checkout.");
      if (!status.can_publish) throw new Error(status.publish_blocker || "This design is not ready to publish.");
      const result = await api.devPublish(publishMessage);
      setPublishedCommit(result.commit.slice(0, 12));
      setPublishOpen(false);
    } catch (error) {
      setPublishError(error instanceof ApiError || error instanceof Error ? error.message : "Could not publish the design");
    } finally {
      setPublishing(false);
    }
  }

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

  // A new element selection that resolves to an icon (and carries no copy competing for the surface)
  // lands the owner on the Icon tab, so an inspect-click on a glyph opens its editor directly -
  // mirroring the Copy-tab surface above. Copy wins the tie (its tab is checked first, by the effect
  // above), so a labelled control with both never yanks away from its text.
  useEffect(() => {
    const id = dev.selectedDevId;
    if (!id) return;
    const el = nodeForDevId(id);
    if (!el) return;
    const hasCopy = el.querySelector("[data-copy-id]") ?? el.closest("[data-copy-id]");
    if (hasCopy) return;
    const icon =
      (el.matches("[data-icon-id]") ? el : null) ??
      el.querySelector("[data-icon-id]") ??
      el.closest("[data-icon-id]");
    if (icon) setFacet("icon");
  }, [dev.selectedDevId]);

  if (!dev.enabled) return null;

  return (
    <aside
      className="fixed right-0 top-0 z-[200] flex h-full w-[340px] max-w-[calc(100vw-16px)] flex-col border-l border-line bg-popover shadow-pop"
      aria-label="Dev mode"
    >
      <header className="flex shrink-0 items-center gap-2 border-b border-line px-3.5 py-3">
        <span className="rounded-control bg-acc px-1.5 py-0.5 text-2xs font-semibold text-acc-on">
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
          {/* D-06: the header close glyph draws through <Icon> (the exact h-4 w-4 the inline svg carried),
              so this call site is itself inspectable/editable via the Icon tab. */}
          <Icon id="dev.close" className="h-4 w-4" />
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

      <footer className="max-h-[55vh] shrink-0 overflow-y-auto border-t border-line bg-popover px-3.5 py-3">
        {dev.lastError ? (
          <div className="mb-2 text-2xs text-err-text">{dev.lastError}</div>
        ) : null}
        {publishError ? <div className="mb-2 text-2xs text-err-text">{publishError}</div> : null}
        {!dev.dirty && publishStatus?.publish_blocker ? (
          <div className="mb-2 text-2xs text-t3">{publishStatus.publish_blocker}</div>
        ) : null}
        {publishedCommit ? <div className="mb-2 text-2xs text-ok-text">Published {publishedCommit} to main.</div> : null}
        {publishOpen ? (
          <div className="mb-3 rounded-card border border-line bg-field p-2.5">
            <label className="block text-2xs font-semibold text-t2">
              Commit Message
              <input
                value={publishMessage}
                maxLength={120}
                onChange={(event) => setPublishMessage(event.target.value)}
                className="mt-1 w-full rounded-control border border-line bg-popover px-2 py-1.5 text-xs text-t1 outline-none focus:border-acc"
              />
            </label>
            <p className="mt-2 text-2xs leading-relaxed text-t3">
              Stockroom will verify TypeScript, rebuild the production interface, commit only Dev Mode files, and push main.
            </p>
            <ModalActions className="mt-2 px-0 pb-0">
              <Button small disabled={publishing} onClick={() => setPublishOpen(false)}>
                Cancel
              </Button>
              <Button
                variant="accent"
                small
                disabled={publishing || !publishMessage.trim()}
                onClick={publish}
              >
                {publishing ? "Publishing..." : "Verify And Push"}
              </Button>
            </ModalActions>
          </div>
        ) : null}
        <div className="mb-2 flex items-center gap-3">
          <button type="button" disabled={!dev.canUndo} onClick={dev.undo} className="text-2xs font-semibold text-t2 disabled:opacity-35">Undo</button>
          <button type="button" disabled={!dev.canRedo} onClick={dev.redo} className="text-2xs font-semibold text-t2 disabled:opacity-35">Redo</button>
          <button
            type="button"
            onClick={dev.resetAll}
            className="text-2xs text-t3 transition-colors hover:text-err-text"
          >
            Reset All
          </button>
          <span className="ml-auto text-2xs text-t3">{dev.dirty ? "Unsaved" : "Saved"}</span>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="accent"
            small
            aria-label="Save to source"
            disabled={!dev.dirty || dev.saving}
            onClick={dev.save}
          >
            {dev.saving ? "Saving..." : "Save To Source"}
          </Button>
          <Button
            type="button"
            small
            disabled={dev.dirty || publishing || publishStatus?.can_publish !== true}
            onClick={() => setPublishOpen(true)}
          >
            Publish To Main
          </Button>
        </div>
      </footer>
    </aside>
  );
}
