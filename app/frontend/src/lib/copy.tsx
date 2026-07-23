/**
 * The copy layer. Wrap a static UI label in <Text id="unique.id">Default text</Text>: it renders
 * the committed override for that id if one exists, else the default (its children). In dev mode
 * the label becomes click-to-select - clicking it (without firing the button it may sit inside)
 * marks it for editing in the Design panel - and carries a dashed underline so you can see what
 * is editable. Outside dev mode it renders as a plain string with no wrapper or behaviour change.
 *
 * `id` must be stable and unique (it is the persistence key); children must be a plain string
 * (the default text and the diff baseline). For copy that lives in an attribute (aria-label,
 * placeholder, title) use `useText(id, default)`, which resolves the same override as a string.
 */
import { useDevMode } from "./devMode";

export function Text({ id, children }: { id: string; children: string }) {
  const { enabled, resolveCopy, selectCopy, selectedCopyId, isCopyOverridden } = useDevMode();
  const resolved = resolveCopy(id, children);

  if (!enabled) return <>{resolved}</>;

  const selected = selectedCopyId === id;
  const overridden = isCopyOverridden(id);
  return (
    <span
      data-copy-id={id}
      title={`Edit copy: ${id}`}
      onClickCapture={(e) => {
        // Capture + stop so a label inside a button edits instead of triggering the button.
        e.stopPropagation();
        e.preventDefault();
        selectCopy(id, children);
      }}
      className={
        "cursor-text rounded-[3px] px-[1px] underline decoration-dashed decoration-1 underline-offset-2 transition-colors " +
        (selected
          ? "bg-acc/20 decoration-acc"
          : overridden
            ? "decoration-ok/80 hover:bg-acc/10"
            : "decoration-acc/50 hover:bg-acc/10")
      }
    >
      {resolved}
    </span>
  );
}

// The string form for copy that lives in an attribute (aria-label / placeholder / title), where a
// wrapper element cannot go. Resolves the same override; it is not click-to-edit.
export function useText(id: string, fallback: string): string {
  const { resolveCopy } = useDevMode();
  return resolveCopy(id, fallback);
}
