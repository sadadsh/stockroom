/**
 * What is left of the sheets' private kit once the general shapes moved out.
 *
 * The section, the empty block and the table shell that used to live here are now `Section`,
 * `EmptyState` and `DataTable` in the shared kit (`components/productState.tsx`, re-exported from
 * `components/primitives.tsx`): nothing about them was workspace-specific, and keeping them here
 * is what let the same three shapes be re-derived on the settings groups and the project
 * workbenches. What remains is genuinely about THIS domain - where one value came from, and what
 * happened to one source - so it stays beside the sheets that ask those questions.
 */
import type { SourceCandidate, SourceState } from "../../api/dossierTypes";
import { useText } from "../../lib/copy";
import { Badge } from "../primitives";
import { SourceStateLabel, sourceStateOf, sourceStateTone } from "./provenanceText";

/**
 * Where one value came from.
 *
 * A value with no recorded source is MANUAL, which is a real provenance and is said out loud -
 * an unattributed blank would read as an oversight rather than as "a person typed this".
 */
export function SourceNote({ source }: { source?: SourceCandidate | null }) {
  const manual = useText("component-browser.manual", "Manual");
  if (!source) return <span className="flex-none text-2xs text-t3">{manual}</span>;
  return (
    <span className="flex-none text-2xs text-t3" title={source.retrievedAt || undefined}>
      {source.sourceLabel || source.sourceId}
    </span>
  );
}

/** One source's outcome, in the closed per-source vocabulary. */
export function SourceStateBadge({ state }: { state: SourceState | undefined }) {
  const resolved = sourceStateOf(state);
  return (
    <Badge size="sm" tone={sourceStateTone(resolved)}>
      <SourceStateLabel state={resolved} />
    </Badge>
  );
}
