/**
 * SuggestionGroupList (COMPAT-04): the auto-discovered compatible sets for a (package, family) scope,
 * grouped by pin-divergence signature and rendered as a clickable list. Picking a group loads its
 * refs into the workbench assembly as an EXPLICIT user action (CONTEXT decision 6) - it never
 * auto-selects, never auto-replaces the current selection silently, and never auto-runs the union
 * (the user still presses Build Set).
 *
 * The query is enabled-gated on package + family; a 409 routes to the reused "index not built"
 * message (decision 9).
 */
import { useStmSuggestions } from "../../api/stmQueries";
import { ApiError } from "../../api/client";
import { Badge, Button, Eyebrow } from "../primitives";

export function SuggestionGroupList({
  package: pkg,
  family,
  onLoadSet,
}: {
  package: string | null;
  family: string | null;
  onLoadSet: (refs: string[]) => void;
}) {
  const suggestions = useStmSuggestions(pkg, family);
  const groups = suggestions.data?.groups ?? [];
  const notBuilt = suggestions.error instanceof ApiError && suggestions.error.status === 409;

  return (
    <div>
      <Eyebrow className="mb-2 px-1">Compatible Sets</Eyebrow>
      {!pkg || !family ? (
        <p className="px-1 text-xs text-t3">Select one family and a package to discover compatible sets.</p>
      ) : notBuilt ? (
        <p className="px-1 text-xs text-t3">Build the index to discover compatible sets.</p>
      ) : suggestions.isLoading ? (
        <p className="px-1 text-xs text-t3">Loading compatible sets...</p>
      ) : suggestions.isError ? (
        <p className="px-1 text-xs text-err">Could not load compatible sets.</p>
      ) : groups.length === 0 ? (
        <p className="px-1 text-xs text-t3">No compatible sets for this scope.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {groups.map((g) => (
            <li
              key={g.signature_id}
              data-testid="suggestion-group"
              className="flex flex-col gap-1.5 rounded-card border border-line2 px-3 py-2"
            >
              <div className="flex items-center justify-between gap-2">
                <Badge tone={g.tier === "baseline" ? "ok" : "warn"} size="sm">
                  {g.tier === "baseline" ? "Baseline" : "Divergent"}
                </Badge>
                <span className="tnum flex-none font-mono text-2xs text-t3">
                  {g.refs.length} parts · {g.divergent_positions} divergent
                </span>
              </div>
              <div className="truncate font-mono text-2xs text-t3">{g.refs.join(", ")}</div>
              <Button variant="soft" small onClick={() => onLoadSet(g.refs)} className="self-start">
                Load This Set
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
