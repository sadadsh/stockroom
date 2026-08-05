/**
 * The Manage menu: everything that changes the component, in one place, off the reading surface.
 *
 * The header used to carry these as buttons - Complete Component, Edit Identity, Resolve Source
 * Conflict, Delete Part - which meant four controls competed with the part number for the top of
 * the screen and the destructive one sat inches from the one people press most. A menu puts the
 * whole inventory one click away, orders it by what it touches, and gives the destructive item the
 * only place it belongs: the bottom, behind a separator, and named for the thing it destroys.
 *
 * Every item here does something. An item whose surface does not exist yet is not listed, because
 * a menu entry that opens nothing is worse than a menu entry that is absent.
 */
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Text, useText } from "../../lib/copy";
import { Icon } from "../Icon";
import { Button } from "../primitives";
import { UI_MENU_LABEL } from "../typography";

/** One entry. `destructive` is a TEXT tone; it never becomes a filled red control. */
export interface ManageMenuItem {
  id: string;
  /** The copy id for the label. */
  copyId: string;
  /** The default label, ellipsis included when another surface follows. */
  label: string;
  destructive?: boolean;
  /** A rule ABOVE this item. Only the destructive group takes one. */
  separated?: boolean;
  run: () => void;
  disabled?: boolean;
}

/**
 * The canonical order. Identity first (what the component IS), then the data (what it claims), then
 * the assets, then where the claims came from, then - alone, after a rule - removal.
 *
 * An ellipsis means another surface follows. `Refresh Component Data` has none because it happens
 * where you stand.
 */
export function manageMenuItems(actions: {
  onEditIdentity: () => void;
  onEditClassification: () => void;
  onReviewMissing: () => void;
  onRefresh: () => void;
  refreshing: boolean;
  onReviewCadSources: () => void;
  onViewProvenance: () => void;
  onDelete: () => void;
  /**
   * Export Component... / Open In... / Reveal Component Files..., when this host can perform
   * them. They arrive as a list rather than as three more callbacks because whether each one
   * EXISTS is decided by the machine (is there a native window, is anything installed, does this
   * component have files) and that decision belongs with the surface that asked, not here.
   */
  shellItems?: ManageMenuItem[];
}): ManageMenuItem[] {
  return [
    {
      id: "edit-identity",
      copyId: "component-browser.manage-edit-identity",
      label: "Edit Identity...",
      run: actions.onEditIdentity,
    },
    {
      id: "edit-classification",
      copyId: "component-browser.manage-edit-classification",
      label: "Edit Category and Classification...",
      run: actions.onEditClassification,
    },
    {
      id: "review-missing",
      copyId: "component-browser.manage-review-missing",
      label: "Review Missing Specifications...",
      run: actions.onReviewMissing,
    },
    {
      id: "refresh",
      copyId: "component-browser.manage-refresh",
      label: "Refresh Component Data",
      disabled: actions.refreshing,
      run: actions.onRefresh,
    },
    {
      id: "review-cad-sources",
      copyId: "component-browser.manage-review-cad",
      label: "Review CAD Sources...",
      run: actions.onReviewCadSources,
    },
    {
      id: "view-provenance",
      copyId: "component-browser.manage-provenance",
      label: "View Data Provenance...",
      run: actions.onViewProvenance,
    },
    ...(actions.shellItems ?? []),
    {
      id: "delete",
      copyId: "component-browser.manage-delete",
      label: "Delete Component...",
      destructive: true,
      separated: true,
      run: actions.onDelete,
    },
  ];
}

export function ManageMenu({ items }: { items: ManageMenuItem[] }) {
  const [open, setOpen] = useState(false);
  // The kit's Button is a plain function component on React 18, so it takes no ref. The anchor
  // holds it instead, which is the element the popover is positioned against anyway.
  const anchorRef = useRef<HTMLSpanElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const menuId = useId();
  const label = useText("component-browser.manage", "Manage");

  const close = useCallback((restoreFocus: boolean) => {
    setOpen(false);
    if (restoreFocus) {
      anchorRef.current
        ?.querySelector<HTMLButtonElement>("[data-dev-id='component-browser.manage']")
        ?.focus();
    }
  }, []);

  // Escape closes and hands focus back; a click anywhere else closes without stealing it. Both are
  // the menu's own contract rather than the caller's, so no surface can forget one of them.
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

  useEffect(() => {
    if (!open) return;
    listRef.current?.querySelector<HTMLButtonElement>("[role='menuitem']:not([disabled])")?.focus();
  }, [open]);

  function onListKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    const keys = ["ArrowDown", "ArrowUp", "Home", "End"];
    if (!keys.includes(event.key)) return;
    const entries = Array.from(
      listRef.current?.querySelectorAll<HTMLButtonElement>("[role='menuitem']:not([disabled])") ??
        [],
    );
    if (entries.length === 0) return;
    const current = entries.findIndex((node) => node === document.activeElement);
    const last = entries.length - 1;
    let next: number;
    if (event.key === "Home") next = 0;
    else if (event.key === "End") next = last;
    else if (event.key === "ArrowDown") next = current >= last ? 0 : current + 1;
    else next = current <= 0 ? last : current - 1;
    event.preventDefault();
    entries[next]?.focus();
  }

  return (
    <span ref={anchorRef} className="relative inline-flex">
      <Button
        small
        data-dev-id="component-browser.manage"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((current) => !current)}
      >
        <Text id="component-browser.manage">Manage</Text>
        <Icon id="overlay.chevron" className="h-3 w-3 flex-none" />
      </Button>
      {open ? (
        <div
          ref={listRef}
          id={menuId}
          role="menu"
          aria-label={label}
          data-dev-id="component-browser.manage-menu"
          onKeyDown={onListKeyDown}
          // A floating surface, so it is the one place a small shadow is allowed. Opaque, square-ish,
          // and right-aligned under its trigger.
          className="absolute right-0 top-full z-30 mt-1 min-w-[15rem] rounded-card border border-line-dark bg-raise py-1 shadow-card"
        >
          {items.map((item) => (
            <span key={item.id} className="block">
              {item.separated ? (
                <span aria-hidden className="my-1 block h-px bg-line" />
              ) : null}
              <button
                type="button"
                role="menuitem"
                data-dev-id="component-browser.manage-item"
                data-manage-item={item.id}
                disabled={item.disabled}
                onClick={() => {
                  close(false);
                  item.run();
                }}
                className={
                  "flex h-[25px] w-full items-center px-2.5 text-left transition-colors " +
                  UI_MENU_LABEL +
                  " hover:bg-control-hover focus-visible:bg-control-hover focus-visible:outline " +
                  "focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus " +
                  "disabled:cursor-not-allowed disabled:text-t5 " +
                  (item.destructive ? "text-err" : "")
                }
              >
                <Text id={item.copyId}>{item.label}</Text>
              </button>
            </span>
          ))}
        </div>
      ) : null}
    </span>
  );
}
