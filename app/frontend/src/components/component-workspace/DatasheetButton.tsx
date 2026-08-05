/**
 * The header's Datasheet control: a split button when there is a choice, a plain one when there is
 * not, and an honest statement when there is no datasheet at all.
 *
 * The bug this replaces was small and expensive: the button rendered because a FILE existed, and
 * the handler only knew how to open a URL. Pressing it on a component whose datasheet was on disk
 * did nothing at all. Now the primary action opens whatever the projection ranked first - stored
 * bytes or a URL, whichever that copy is - and the arrow menu carries the rest: the other
 * revisions of the same document, and every other document the part references.
 *
 * A split button is only a split button when there IS a safe default plus alternatives. With one
 * document it is a single control, because an arrow that opens a menu of nothing is a dead click,
 * and with no document there is no button at all: `Datasheet Missing` is a state, and `Find
 * Datasheet` beside it is the action that can change the state.
 */
import { useCallback, useEffect, useId, useRef, useState } from "react";
import type { DocumentsView } from "../../api/dossierTypes";
import { Text, useCopyFormatter, useText } from "../../lib/copy";
import { Icon } from "../Icon";
import { Button, StatusText } from "../primitives";
import { UI_MENU_LABEL } from "../typography";
import {
  otherDocumentTargets,
  preferredTarget,
  revisionLabel,
  revisionTargets,
  type DatasheetTarget,
} from "./datasheetWorkflow";

export function DatasheetButton({
  documents,
  onOpen,
  onFindDatasheet,
}: {
  documents: DocumentsView;
  onOpen: (target: DatasheetTarget) => void;
  /** No datasheet is on record: open the surface that can go and find one. */
  onFindDatasheet: () => void;
}) {
  const [open, setOpen] = useState(false);
  const anchorRef = useRef<HTMLSpanElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const menuId = useId();
  const menuLabel = useText("component-browser.datasheet-menu", "Other documents");
  const moreLabel = useText("component-browser.datasheet-more", "More datasheet options");

  const preferred = preferredTarget(documents);
  const revisions = revisionTargets(documents);
  const others = otherDocumentTargets(documents);
  const hasMenu = revisions.length > 0 || others.length > 0;

  const close = useCallback((restoreFocus: boolean) => {
    setOpen(false);
    if (restoreFocus) {
      anchorRef.current
        ?.querySelector<HTMLButtonElement>("[data-dev-id='component-browser.datasheet-more']")
        ?.focus();
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.stopPropagation();
      close(true);
    };
    const onPointer = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (!target) return;
      if (listRef.current?.contains(target) || anchorRef.current?.contains(target)) return;
      close(false);
    };
    document.addEventListener("keydown", onKey, true);
    document.addEventListener("pointerdown", onPointer, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      document.removeEventListener("pointerdown", onPointer, true);
    };
  }, [close, open]);

  if (!preferred) {
    // Never a dead disabled button. The state is stated as a state, and the ACTION beside it is
    // the one that can change the state.
    return (
      <span className="flex items-center gap-1.5">
        <StatusText tone="warn" data-dev-id="component-browser.datasheet-missing">
          <Text id="component-browser.datasheet-missing">Datasheet Missing</Text>
        </StatusText>
        <Button small data-dev-id="component-browser.datasheet-find" onClick={onFindDatasheet}>
          <Text id="component-browser.datasheet-find">Find Datasheet</Text>
        </Button>
      </span>
    );
  }

  return (
    <span ref={anchorRef} className="relative inline-flex items-center gap-px">
      <Button
        small
        data-dev-id="component-browser.header-datasheet"
        onClick={() => onOpen(preferred)}
      >
        <Text id="component-browser.header-datasheet">Datasheet</Text>
      </Button>
      {hasMenu ? (
        <>
          <Button
            small
            data-dev-id="component-browser.datasheet-more"
            aria-haspopup="menu"
            aria-expanded={open}
            aria-controls={open ? menuId : undefined}
            aria-label={moreLabel}
            title={moreLabel}
            className="px-1"
            onClick={() => setOpen((current) => !current)}
          >
            <Icon id="overlay.chevron" className="h-3 w-3 flex-none" />
          </Button>
          {open ? (
            <div
              ref={listRef}
              id={menuId}
              role="menu"
              aria-label={menuLabel}
              data-dev-id="component-browser.datasheet-menu"
              className={
                "absolute right-0 top-full z-30 mt-1 min-w-[17rem] rounded-card border " +
                "border-line-dark bg-raise py-1 shadow-card"
              }
            >
              <DatasheetMenuItem
                target={preferred}
                devId="component-browser.datasheet-current"
                onPick={(picked) => {
                  close(false);
                  onOpen(picked);
                }}
              >
                <Text id="component-browser.datasheet-current">Current Datasheet</Text>
              </DatasheetMenuItem>
              {revisions.map((target) => (
                <DatasheetMenuItem
                  key={`revision:${target.id}`}
                  target={target}
                  devId="component-browser.datasheet-revision"
                  onPick={(picked) => {
                    close(false);
                    onOpen(picked);
                  }}
                >
                  <RevisionLabel target={target} />
                </DatasheetMenuItem>
              ))}
              {others.length > 0 ? <span aria-hidden className="my-1 block h-px bg-line" /> : null}
              {others.map((target) => (
                <DatasheetMenuItem
                  key={`other:${target.id}`}
                  target={target}
                  devId="component-browser.datasheet-other"
                  onPick={(picked) => {
                    close(false);
                    onOpen(picked);
                  }}
                >
                  <span>{target.document.title}</span>
                </DatasheetMenuItem>
              ))}
            </div>
          ) : null}
        </>
      ) : null}
    </span>
  );
}

function RevisionLabel({ target }: { target: DatasheetTarget }) {
  const label = useCopyFormatter(
    "component-browser.datasheet-revision",
    "Revision {revision}",
  );
  return <span>{label({ revision: revisionLabel(target.document) })}</span>;
}

function DatasheetMenuItem({
  target,
  devId,
  onPick,
  children,
}: {
  target: DatasheetTarget;
  devId: string;
  onPick: (target: DatasheetTarget) => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      data-dev-id={devId}
      data-document-id={target.id}
      onClick={() => onPick(target)}
      className={
        "flex h-[25px] w-full items-center gap-2 px-2.5 text-left transition-colors " +
        UI_MENU_LABEL +
        " hover:bg-control-hover focus-visible:bg-control-hover focus-visible:outline " +
        "focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus"
      }
    >
      <span className="min-w-0 flex-1 truncate">{children}</span>
      <span className="ui-component-metadata flex-none">{target.document.documentTypeLabel}</span>
    </button>
  );
}
