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
 *
 * A sentence that has to carry a value takes NAMED placeholders rather than concatenation:
 *
 *     <Text id="provider.downloaded" values={{ count, total }}>
 *       Downloaded {count} of {total} files
 *     </Text>
 *
 * The default declares the required names; `lib/copyPlaceholders.ts` owns the grammar and the
 * fail-safe rules. An override that drops a required name, invents an unknown one, or is malformed
 * is NOT rendered: the default is used instead and a diagnostic is recorded, so a stale committed
 * override can never show a person template syntax or delete the number a sentence exists to say.
 */
import { useDevMode } from "./devMode";
import {
  clearCopyDiagnostic,
  copyOverrideProblem,
  copyPlaceholders,
  declareCopyPlaceholders,
  formatCopy,
  recordCopyDiagnostic,
  type CopyValues,
} from "./copyPlaceholders";

export type { CopyValues } from "./copyPlaceholders";

/**
 * The one resolve path every form shares: learn what the default declares, then take the committed
 * override ONLY when it still satisfies that declaration. Returns the template, unsubstituted.
 */
function useSafeTemplate(id: string, fallback: string): string {
  const { resolveCopy } = useDevMode();
  declareCopyPlaceholders(id, fallback);
  const candidate = resolveCopy(id, fallback);
  if (candidate === fallback) {
    clearCopyDiagnostic(id);
    return fallback;
  }
  const problem = copyOverrideProblem(fallback, candidate);
  if (problem) {
    recordCopyDiagnostic(id, problem, copyPlaceholders(fallback) ?? []);
    return fallback;
  }
  clearCopyDiagnostic(id);
  return candidate;
}

function useResolvedCopy(id: string, fallback: string, values?: CopyValues): string {
  return formatCopy(useSafeTemplate(id, fallback), values);
}

export function Text({
  id,
  values,
  children,
}: {
  id: string;
  values?: CopyValues;
  children: string;
}) {
  const { enabled, studioMode, selectCopy, selectedCopyId, isCopyOverridden } = useDevMode();
  const resolved = useResolvedCopy(id, children, values);

  if (!enabled) return <>{resolved}</>;

  // Preview is the real product, not an editor overlay. Keep the stable copy identity in the DOM
  // for Layers and target coverage, but add no underline, tab stop, tooltip, or event interception
  // until Edit is explicitly chosen.
  if (studioMode !== "edit") {
    return (
      <span data-copy-id={id} data-copy-default={children}>
        {resolved}
      </span>
    );
  }

  const selected = selectedCopyId === id;
  const overridden = isCopyOverridden(id);
  return (
    <span
      data-copy-id={id}
      // The raw TEMPLATE, not the substituted text: the panel edits the sentence with its
      // placeholders in it, and reading the rendered text back would bake this render's values in.
      data-copy-default={children}
      title={`Edit copy: ${id}`}
      // Reachable and operable from the keyboard, not the pointer alone. This element exists ONLY
      // while Dev Mode is on - the branch above returns a bare fragment otherwise - so the tab stop
      // is a tab stop through the EDITOR, and selecting a string to reword was previously something
      // only a mouse could do.
      //
      // Deliberately NO `role="button"`, though a lint rule asks for one on a focusable click
      // target. A routed string is usually a real control's LABEL, so this span sits inside a real
      // `<button>` - and a button-roled span inside a button puts TWO controls with the same
      // accessible name in the tree for every labelled control in the application. That was measured
      // (`ConfirmDialog.test.tsx` finds two buttons named Cancel with the role on), and duplicating
      // every name is worse for a screen-reader user than an unroled focusable span. Announcing this
      // properly needs a different affordance for the editor - a modifier-click, or selection driven
      // from the panel itself - not a role on an element that cannot legally carry one here.
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key !== "Enter" && e.key !== " ") return;
        // Same stop as the click below: Space inside a button would otherwise press the button too.
        e.stopPropagation();
        e.preventDefault();
        selectCopy(id, children);
      }}
      onClickCapture={(e) => {
        if (e.target instanceof Element && e.target.closest("[data-design-inserted-icon]")) return;
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
export function useText(id: string, fallback: string, values?: CopyValues): string {
  return useResolvedCopy(id, fallback, values);
}

/**
 * The deferred form, for a sentence whose values are only known inside a callback (a toast written
 * when a request comes back, say). A hook cannot run there, so this resolves the template during
 * render and hands back a formatter to call later with the numbers of the moment.
 *
 * The alternative is what this replaces: resolving a fragment with `useText` and concatenating a
 * count onto it at the call site. That is not a sentence anyone can reword - the word order is in
 * the JavaScript, not in the string - and it is exactly what named placeholders exist to end.
 */
export function useCopyFormatter(
  id: string,
  fallback: string,
): (values?: CopyValues) => string {
  const template = useSafeTemplate(id, fallback);
  return (values?: CopyValues) => formatCopy(template, values);
}
