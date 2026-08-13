/**
 * THE ISSUES SECTION of the Design panel: what this arrangement costs, live, in one list.
 *
 * Plan 1.4 states the surface in one sentence - "the issues list renders live in edit mode, stays
 * inspectable outside it" - and both halves of that are decisions this file has to keep.
 *
 *   LIVE means the list is recomputed from the arrangement IN FORCE and the palette CURRENTLY ON
 *   SCREEN, not from what shipped. The arrangement comes from `resolveWorkspaceLayout`, the one place
 *   the draft-over-commit-over-default order is decided, so a drag of a section and a load of a named
 *   draft both show up here without this file knowing either happened. The palette comes from the
 *   token slice through `draftThemeTokens`, so nudging a colour in the Tokens rows moves this list on
 *   the same render that moves the application behind it. That is the whole of plan decision 3: the
 *   editor performs the edit and the list says what it cost.
 *
 *   OUTSIDE EDIT MODE matters more than it looks. The section is mounted whenever DEV MODE is on and
 *   is not gated on `editMode` at all, because a committed layout's known issues are part of the
 *   commit (plan 1.4: honesty travels with the design). An issues list that only existed while the
 *   owner was actively dragging would be a list nobody could consult about a design that already
 *   shipped.
 *
 * WHY THE ROWS ARE THEIR OWN COMPONENT. A row renders its issue through the copy layer - the
 * validator returns a copy ID and a fallback and never prose (`layout/validatorIssues.ts`), so the
 * row is where `useText` is called. A hook cannot be called inside a `.map`, so each row is a
 * component; that is the only reason `IssueRow` exists.
 *
 * WHY A CLICK SELECTS A DEV ID. The panel is already an inspect-first editor: the Selection pane and
 * every facet tab are pointed at one `data-dev-id`. An issue names a PLACEMENT or a PIECE, and the
 * registry's manifest states the dev ids that piece renders, so the row can hand the rest of the
 * panel the thing the issue is about instead of leaving the owner to find it. An issue about a token
 * pairing or an action names nothing on screen and its row is inert rather than pretending.
 *
 * COST. `validateDocument` is pure and walks the document once per layer, so the whole list is a
 * `useMemo` over two inputs and nothing more elaborate; `validateDocument.test.ts` and the four layer
 * suites are what prove it stays cheap enough to run on every draft edit.
 *
 * Every label goes through `useText` in its STRING form rather than through `<Text>`, for the reason
 * `ArrangePanel.tsx` states at length: a `<Text>` renders a click-to-edit span whose capture handler
 * swallows the click, which is right everywhere in the product and fatal on a surface that exists
 * only while dev mode is on.
 */
import { useCallback, useMemo } from "react";
import { useText } from "../../lib/copy";
import { useDevMode } from "../../lib/devMode";
import { layoutPlacements, type LayoutDocument } from "../../layout/document";
import { resolveWorkspaceLayout } from "../../layout/resolveWorkspaceLayout";
import { draftThemeTokens } from "../../layout/validateContrast";
import { validateDocument } from "../../layout/validateDocument";
import type { IssueSubject, ValidatorIssue } from "../../layout/validatorIssues";
import { WORKSPACE_PIECE_REGISTRY } from "../../layout/workspacePieces";
import { SectionHeader } from "../productState";

/**
 * The dev id a row can point the rest of the panel at, or `null`.
 *
 * A manifest lists the dev ids its piece renders, its own first (`layout/registry.ts`), so the first
 * one is the piece's own handle in the id system. A placement is resolved to its piece through the
 * document, because the issue names the placement and the registry knows only pieces.
 */
function devIdForSubject(layout: LayoutDocument, subject: IssueSubject): string | null {
  const pieceId =
    subject.kind === "piece"
      ? subject.id
      : subject.kind === "placement"
        ? layoutPlacements(layout).find((visit) => visit.node.id === subject.id)?.node.piece
        : undefined;
  if (!pieceId) return null;
  return WORKSPACE_PIECE_REGISTRY.get(pieceId)?.devIds[0] ?? null;
}

/** The machine-readable specifics as one short line, or "" - a measured ratio, a folded tier. */
function detailLine(issue: ValidatorIssue): string {
  const detail = issue.detail;
  if (!detail) return "";
  return Object.keys(detail)
    .sort()
    .map((key) => `${key}=${detail[key]}`)
    .join(" ");
}

function IssueRow({
  issue,
  devId,
  onSelect,
}: {
  issue: ValidatorIssue;
  devId: string | null;
  onSelect: (devId: string) => void;
}) {
  const text = useText(issue.copy.id, issue.copy.fallback);
  const detail = detailLine(issue);
  return (
    <button
      type="button"
      data-dev-id="design.issue"
      data-issue-code={issue.code}
      disabled={devId === null}
      onClick={() => {
        if (devId !== null) onSelect(devId);
      }}
      className={
        "flex w-full flex-col items-start gap-0.5 rounded-control px-1.5 py-1 text-left " +
        "transition-colors disabled:cursor-default " +
        (devId === null ? "" : "hover:bg-raise2")
      }
    >
      <span className="text-2xs leading-relaxed text-t2">{text}</span>
      <span className="w-full truncate font-mono text-2xs text-t3" title={issue.subject.id}>
        {issue.subject.id}
      </span>
      {detail ? (
        <span className="w-full truncate font-mono text-2xs text-t4" title={detail}>
          {detail}
        </span>
      ) : null}
    </button>
  );
}

export function IssuesSection({
  open,
  setOpen,
}: {
  open: boolean;
  setOpen: (value: boolean) => void;
}) {
  const dev = useDevMode();
  const { layoutDraft, tokenOverrides, selectDevId } = dev;

  const title = useText("design.issues-section", "Issues");
  const hint = useText(
    "design.issues-hint",
    "This list warns and never refuses. Each row states what an edit cost.",
  );
  const nothing = useText("design.issues-none", "Nothing to report");
  const warningsTitle = useText("design.issues-warnings", "Warnings");
  const infoTitle = useText("design.issues-info", "Notes");

  // The arrangement in force: a working draft, else the committed override, else the shipped
  // default. One question, answered in one module - see `resolveWorkspaceLayout`.
  const layout = useMemo(() => resolveWorkspaceLayout(layoutDraft), [layoutDraft]);
  // The palettes as the screen has them, both themes, with the live token draft over the defaults.
  const themes = useMemo(() => draftThemeTokens(tokenOverrides), [tokenOverrides]);
  const issues = useMemo(
    () => validateDocument(layout, WORKSPACE_PIECE_REGISTRY, themes),
    [layout, themes],
  );

  const warnings = issues.filter((issue) => issue.severity === "warning");
  const notes = issues.filter((issue) => issue.severity === "info");

  const select = useCallback((devId: string) => selectDevId(devId), [selectDevId]);

  // Keyed on WHAT THE ROW SAYS rather than on its position, because the list re-sorts on every edit
  // (`compareIssues` is a total order over the whole model) and a positional key would make React
  // reuse the row that happens to have slid into the slot. The four parts are exactly the ones that
  // order builds its key from, so two rows collide only when they are the same row twice - which
  // `validateDocument` treats as one finding reported twice, not as two findings.
  const rows = (list: readonly ValidatorIssue[]) =>
    list.map((issue) => (
      <IssueRow
        key={`${issue.code}|${issue.subject.kind}:${issue.subject.id}|${(issue.path ?? []).join("/")}|${detailLine(issue)}`}
        issue={issue}
        devId={devIdForSubject(layout, issue.subject)}
        onSelect={select}
      />
    ));

  return (
    <div data-dev-id="design.issues">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-1.5 px-3.5 py-2 ui-property-label hover:text-t2"
      >
        <span aria-hidden="true">{open ? "▾" : "▸"}</span>
        {title}
        <span data-dev-id="design.issues-count" className="ml-auto font-mono text-t3">
          {`${warnings.length} / ${notes.length}`}
        </span>
      </button>
      {open ? (
        <div className="flex flex-col gap-2 px-3.5 pb-3">
          <p className="text-2xs leading-relaxed text-t3">{hint}</p>
          {issues.length === 0 ? <p className="text-2xs text-t3">{nothing}</p> : null}
          {warnings.length > 0 ? (
            <section>
              <SectionHeader title={warningsTitle} className="mb-1" />
              {rows(warnings)}
            </section>
          ) : null}
          {notes.length > 0 ? (
            <section>
              <SectionHeader title={infoTitle} className="mb-1" />
              {rows(notes)}
            </section>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
