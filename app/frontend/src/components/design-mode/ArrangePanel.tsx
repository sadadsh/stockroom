/**
 * THE ARRANGE SECTION of the Design panel: what state the arrangement is in, how to put a piece
 * back on screen, and the named local drafts.
 *
 * Everything an owner can do to the arrangement WITHOUT pointing at a piece lives here, and there
 * are exactly three such things:
 *
 *   IS THERE AN EDIT AT ALL. The workspace draws a working draft, a committed override or the
 *   shipped default (`layout/resolveWorkspaceLayout.ts`), and which of the three is in force is not
 *   visible from the canvas - a redesign that looks right looks the same whether it is saved or
 *   not. So the state is stated, and reverting to what is committed is one control.
 *
 *   THE PIECES THAT ARE NOT DRAWN. Hiding a piece removes the only surface its handle could hang
 *   off, so a hidden piece is unreachable from the canvas by construction. That is the failure mode
 *   an editor with an off switch and no on switch has, and this list is the on switch.
 *
 *   THE DRAFTS. `lib/layoutDrafts.ts` is the storage and the whole of the storage; this is its only
 *   interface. A draft is a WORKSTATION artefact and says so - saving one is not committing, and the
 *   panel never implies it is.
 *
 * WHY EVERY LABEL GOES THROUGH `useText` AND NOT `<Text>`. Both route through the copy layer and
 * both are editable in the Copy tab, but `<Text>` renders a click-to-edit span whose capture handler
 * swallows the click - which is right everywhere in the product and fatal here, because this surface
 * EXISTS ONLY WHILE DEV MODE IS ON. Every button in it would be a button that selects its own label
 * instead of doing its job. The string form has no wrapper and no handler, so the labels stay
 * rewordable and the controls stay controls.
 */
import { useCallback, useMemo, useState } from "react";
import { useText } from "../../lib/copy";
import { useDevMode } from "../../lib/devMode";
import {
  deleteLayoutDraft,
  listLayoutDrafts,
  loadLayoutDraft,
  saveLayoutDraft,
  LAYOUT_DRAFT_NAME_MAX,
} from "../../lib/layoutDrafts";
import { layoutPlacements } from "../../layout/document";
import { restorePlacement } from "../../layout/editOperations";
import { resolveWorkspaceLayout } from "../../layout/resolveWorkspaceLayout";
import { SectionHeader } from "../productState";
import { Icon } from "../Icon";

/** One placement the arrangement is currently not drawing, and which setting is doing it. */
interface OffScreenPlacement {
  placementId: string;
  pieceId: string;
  collapsed: boolean;
  hidden: boolean;
}

export function ArrangeSection({
  open,
  setOpen,
}: {
  open: boolean;
  setOpen: (value: boolean) => void;
}) {
  const dev = useDevMode();
  const { layoutDraft, isLayoutEdited, setLayoutDraft, resetLayoutDraft } = dev;
  const [name, setName] = useState("");
  // The saved list is read from storage, which is not React state, so a save or a delete has to say
  // the list moved. A counter rather than holding the list in state: storage is the truth, and a
  // mirror of it is a second answer that can disagree with the first.
  const [revision, setRevision] = useState(0);
  const [failed, setFailed] = useState(false);

  const title = useText("design.arrange-section", "Arrangement");
  const hint = useText(
    "design.arrange-hint",
    "Drag a handle onto another slot. Arrow Up and Arrow Down move a focused handle.",
  );
  const editedLabel = useText("design.state-edited", "Edited");
  const cleanLabel = useText("design.state-clean", "Not Edited");
  const resetLabel = useText("design.reset", "Reset To Applied");
  const offScreenTitle = useText("design.off-screen", "Hidden And Collapsed");
  const nothingOffScreen = useText("design.off-screen-none", "Nothing is off screen");
  const restoreLabel = useText("design.restore", "Restore");
  const draftsTitle = useText("design.drafts", "Drafts");
  const draftNameLabel = useText("design.draft-name", "Draft Name");
  const saveLabel = useText("design.draft-save", "Save Draft");
  const loadLabel = useText("design.draft-load", "Load");
  const deleteLabel = useText("design.draft-delete", "Delete");
  const noDrafts = useText("design.draft-none", "No drafts on this machine");
  const failedLabel = useText("design.draft-failed", "This machine did not store that draft");

  // The arrangement in force, which is what a draft has to capture: an owner who has edited nothing
  // and saves a draft means "the arrangement as it is", not "no arrangement".
  const layout = useMemo(() => resolveWorkspaceLayout(layoutDraft), [layoutDraft]);

  // One pass over the placements rather than a filter feeding a map: the two questions are the same
  // question, since what makes a placement interesting here is exactly the pair of booleans the row
  // then shows.
  const offScreen = useMemo<OffScreenPlacement[]>(() => {
    const rows: OffScreenPlacement[] = [];
    for (const visit of layoutPlacements(layout)) {
      const collapsed = visit.node.collapsed === true;
      const hidden = visit.node.hidden === true;
      if (!collapsed && !hidden) continue;
      rows.push({ placementId: visit.node.id, pieceId: visit.node.piece, collapsed, hidden });
    }
    return rows;
  }, [layout]);

  const drafts = useMemo(() => {
    // `revision` is the dependency, deliberately: it is what says storage moved.
    void revision;
    return listLayoutDrafts();
  }, [revision]);

  const restore = useCallback(
    (entry: OffScreenPlacement) => {
      const next = restorePlacement(layout, { placement: entry.placementId });
      if (next !== layout) setLayoutDraft(next);
    },
    [layout, setLayoutDraft],
  );

  const save = useCallback(() => {
    const stored = saveLayoutDraft(name, layout);
    setFailed(!stored);
    if (stored) {
      setName("");
      setRevision((value) => value + 1);
    }
  }, [name, layout]);

  const load = useCallback(
    (draftName: string) => {
      const stored = loadLayoutDraft(draftName);
      setFailed(stored === null);
      if (stored) setLayoutDraft(stored);
    },
    [setLayoutDraft],
  );

  const remove = useCallback((draftName: string) => {
    setFailed(!deleteLayoutDraft(draftName));
    setRevision((value) => value + 1);
  }, []);

  return (
    <div data-dev-id="design.arrange">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-1.5 px-3.5 py-2 ui-property-label hover:text-t2"
      >
        <Icon id={open ? "design.disclosure-open" : "design.disclosure-closed"} className="h-3 w-3" />
        {title}
        <span data-dev-id="design.arrange-state" className="ml-auto font-mono text-t3">
          {isLayoutEdited ? editedLabel : cleanLabel}
        </span>
      </button>
      {open ? (
        <div className="flex flex-col gap-2 px-3.5 pb-3">
          <p className="text-2xs leading-relaxed text-t3">{hint}</p>
          <button
            type="button"
            data-dev-id="design.arrange-reset"
            disabled={!isLayoutEdited}
            onClick={resetLayoutDraft}
            className="self-start rounded-control border border-line px-2 py-1 text-2xs font-semibold text-t2 transition-colors hover:text-t1 disabled:opacity-35"
          >
            {resetLabel}
          </button>

          <section>
            <SectionHeader title={offScreenTitle} className="mb-1" />
            {offScreen.length === 0 ? (
              <p className="text-2xs text-t3">{nothingOffScreen}</p>
            ) : (
              offScreen.map((entry) => (
                <div key={entry.placementId} className="flex items-center gap-1.5 py-0.5">
                  <span
                    className="min-w-0 flex-1 truncate font-mono text-2xs text-t2"
                    title={entry.placementId}
                  >
                    {entry.placementId}
                  </span>
                  <button
                    type="button"
                    data-dev-id="design.arrange-restore"
                    onClick={() => restore(entry)}
                    className="flex-none rounded-control border border-line px-1.5 py-0.5 text-2xs font-semibold text-t2 transition-colors hover:text-t1"
                  >
                    {restoreLabel}
                  </button>
                </div>
              ))
            )}
          </section>

          <section data-dev-id="design.arrange-drafts">
            <SectionHeader title={draftsTitle} className="mb-1" />
            <div className="flex items-center gap-1.5">
              <input
                type="text"
                data-dev-id="design.arrange-draft-name"
                aria-label={draftNameLabel}
                placeholder={draftNameLabel}
                maxLength={LAYOUT_DRAFT_NAME_MAX}
                value={name}
                onChange={(event) => setName(event.target.value)}
                className="min-w-0 flex-1 rounded-control border border-line bg-field px-2 py-1 text-2xs text-t1 outline-none focus:border-focus"
              />
              <button
                type="button"
                data-dev-id="design.arrange-draft-save"
                disabled={name.trim().length === 0}
                onClick={save}
                className="flex-none rounded-control border border-line px-2 py-1 text-2xs font-semibold text-t2 transition-colors hover:text-t1 disabled:opacity-35"
              >
                {saveLabel}
              </button>
            </div>
            {failed ? (
              <p role="alert" className="mt-1 text-2xs text-err-text">
                {failedLabel}
              </p>
            ) : null}
            {drafts.length === 0 ? (
              <p className="mt-1 text-2xs text-t3">{noDrafts}</p>
            ) : (
              drafts.map((draft) => (
                <div
                  key={draft.name}
                  data-dev-id="design.arrange-draft"
                  className="flex items-center gap-1.5 py-0.5"
                >
                  <span className="min-w-0 flex-1 truncate text-2xs text-t2" title={draft.name}>
                    {draft.name}
                  </span>
                  <button
                    type="button"
                    onClick={() => load(draft.name)}
                    className="flex-none rounded-control border border-line px-1.5 py-0.5 text-2xs font-semibold text-t2 transition-colors hover:text-t1"
                  >
                    {loadLabel}
                  </button>
                  <button
                    type="button"
                    onClick={() => remove(draft.name)}
                    className="flex-none rounded-control px-1.5 py-0.5 text-2xs text-t3 transition-colors hover:text-err-text"
                  >
                    {deleteLabel}
                  </button>
                </div>
              ))
            )}
          </section>
        </div>
      ) : null}
    </div>
  );
}
