/**
 * FamilyPicker (TABLE-02): the family / MCU multi-select that scopes the viewer. It reads the
 * family option set from GET /api/stm/families and emits the full scope object up to
 * StmViewerPage; it holds NO fetch of the spec matrix itself (that is the page's useStmMcus) and
 * issues NO network request per toggle (CONTEXT decision 3).
 *
 * Two levels, both sourced from FamilyDTO: a family toggle (scope.families) and, when a family is
 * expanded, its sub-series lines (scope.mcus). Selecting whole families and/or specific lines is
 * the real "family / MCU multi-select" TABLE-02 names; a cleared selection means "all families".
 */
import { useState } from "react";
import { useStmFamilies } from "../../api/stmQueries";
import type { FamilyDTO } from "../../api/types";
import type { StmScope } from "../../pages/StmViewerPage";
import { Badge, Eyebrow } from "../primitives";

// A small disclosure chevron (no shared icon for it); rotates 90deg when the family is expanded.
function ChevronIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className={className}>
      <path d="M9 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

interface Props {
  scope: StmScope;
  onScopeChange: (next: StmScope) => void;
}

function toggle(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

export function FamilyPicker({ scope, onScopeChange }: Props) {
  const families = useStmFamilies();
  const [expanded, setExpanded] = useState<string | null>(null);

  const rows = families.data?.families ?? [];
  const selectedCount = scope.families.length + scope.mcus.length;

  return (
    <div className="flex min-h-0 flex-col">
      <div className="mb-2 flex items-center justify-between px-1">
        <Eyebrow>Families</Eyebrow>
        {selectedCount > 0 ? (
          <button
            type="button"
            onClick={() => onScopeChange({ families: [], mcus: [] })}
            className="rounded-control px-1.5 py-0.5 text-2xs font-medium text-t3 hover:text-t1"
          >
            Clear
          </button>
        ) : null}
      </div>

      {families.isLoading ? (
        <p className="px-2 py-3 text-xs text-t3">Loading families...</p>
      ) : families.isError ? (
        <p className="px-2 py-3 text-xs text-err">Could not load families.</p>
      ) : rows.length === 0 ? (
        <p className="px-2 py-3 text-xs text-t3">No families in the index.</p>
      ) : (
        <div className="-mx-1 min-h-0 flex-1 overflow-y-auto px-1">
          <ScopeRow
            label="All Families"
            count={rows.reduce((sum, f) => sum + f.mcu_count, 0)}
            active={scope.families.length === 0 && scope.mcus.length === 0}
            onToggle={() => onScopeChange({ families: [], mcus: [] })}
          />
          {rows.map((fam) => (
            <FamilyGroup
              key={fam.family}
              family={fam}
              scope={scope}
              expanded={expanded === fam.family}
              onExpand={() =>
                setExpanded((cur) => (cur === fam.family ? null : fam.family))
              }
              onToggleFamily={() =>
                onScopeChange({ ...scope, families: toggle(scope.families, fam.family) })
              }
              onToggleLine={(line) =>
                onScopeChange({ ...scope, mcus: toggle(scope.mcus, line) })
              }
            />
          ))}
        </div>
      )}
    </div>
  );
}

function FamilyGroup({
  family,
  scope,
  expanded,
  onExpand,
  onToggleFamily,
  onToggleLine,
}: {
  family: FamilyDTO;
  scope: StmScope;
  expanded: boolean;
  onExpand: () => void;
  onToggleFamily: () => void;
  onToggleLine: (line: string) => void;
}) {
  const active = scope.families.includes(family.family);
  const hasLines = family.lines.length > 0;
  return (
    <div>
      <div
        className={
          "group flex items-center gap-2 rounded-control px-1.5 py-1.5 " +
          (active ? "bg-acc-soft" : "hover:bg-[var(--c-hover)]")
        }
      >
        <button
          type="button"
          onClick={onToggleFamily}
          aria-pressed={active}
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
        >
          <CheckBox checked={active} />
          <span className={"min-w-0 flex-1 truncate text-sm " + (active ? "text-t1" : "text-t2")}>
            {family.family}
          </span>
          <span className="tnum flex-none font-mono text-2xs text-t3">{family.mcu_count}</span>
        </button>
        {hasLines ? (
          <button
            type="button"
            onClick={onExpand}
            aria-label={expanded ? `Collapse ${family.family}` : `Expand ${family.family}`}
            className="flex-none rounded-[5px] p-0.5 text-t3 hover:text-t1"
          >
            <ChevronIcon
              className={"h-3.5 w-3.5 transition-transform " + (expanded ? "rotate-90" : "")}
            />
          </button>
        ) : null}
      </div>

      {expanded && hasLines ? (
        <div className="ml-3.5 flex flex-col border-l border-line pl-2">
          {family.lines.map((line) => {
            const lineActive = scope.mcus.includes(line);
            return (
              <button
                key={line}
                type="button"
                onClick={() => onToggleLine(line)}
                aria-pressed={lineActive}
                className={
                  "flex items-center gap-2 rounded-control px-1.5 py-1 text-left " +
                  (lineActive ? "bg-acc-soft" : "hover:bg-[var(--c-hover)]")
                }
              >
                <CheckBox checked={lineActive} small />
                <span
                  className={
                    "min-w-0 flex-1 truncate font-mono text-xs " +
                    (lineActive ? "text-t1" : "text-t3")
                  }
                >
                  {line}
                </span>
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

// A neutral checkbox indicator (the app's own field-checkbox idiom): accent fill when checked, a
// hairline square when not. Not a saturated hue (selection stays neutral, design contract).
function CheckBox({ checked, small = false }: { checked: boolean; small?: boolean }) {
  const size = small ? "h-[15px] w-[15px] text-[10px]" : "h-[17px] w-[17px] text-[11px]";
  return (
    <span
      className={
        "flex flex-none items-center justify-center rounded-[5px] border-[1.5px] " +
        size +
        " " +
        (checked ? "border-acc bg-acc text-acc-on" : "border-line2 text-transparent")
      }
    >
      {checked ? "✓" : ""}
    </span>
  );
}

function ScopeRow({
  label,
  count,
  active,
  onToggle,
}: {
  label: string;
  count: number;
  active: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={active}
      className={
        "flex w-full items-center gap-2 rounded-control px-1.5 py-1.5 text-left " +
        (active ? "bg-acc-soft" : "hover:bg-[var(--c-hover)]")
      }
    >
      <span className={"min-w-0 flex-1 truncate text-sm " + (active ? "text-t1" : "text-t2")}>
        {label}
      </span>
      <Badge tone="neutral" size="sm" className="tnum font-mono">
        {count.toLocaleString()}
      </Badge>
    </button>
  );
}
