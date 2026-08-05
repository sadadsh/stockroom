/**
 * Copy MPN.
 *
 * The one rule this control exists to keep: the string that lands on the clipboard is the CANONICAL
 * manufacturer part number, byte for byte. No trimming, no upper-casing, no appended package, no
 * "MPN: " prefix. A part number is looked up in a distributor's search box, and a search box does
 * not forgive a stray character.
 *
 * The second rule is that confirming does not move anything. The glyph swaps to a checkmark for a
 * second inside a fixed-size box, so the control does not grow, the label does not change width,
 * and the buttons either side of it stay exactly where the pointer left them.
 */
import { useEffect, useRef, useState } from "react";
import { Text, useText } from "../../lib/copy";
import { DuplicateIcon } from "../icons";
import { Icon } from "../Icon";
import { Button } from "../primitives";

/** How long the checkmark stays up. Long enough to read, short enough not to be a state. */
export const COPIED_FEEDBACK_MS = 1000;

export async function writeToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

export function CopyMpnButton({ mpn }: { mpn: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | null>(null);
  const label = useText("component-browser.copy-mpn", "Copy MPN");
  const tooltip = useText(
    "component-browser.copy-mpn-title",
    "Copy the manufacturer part number exactly as recorded",
  );
  const copiedLabel = useText("component-browser.copy-mpn-copied", "Copied");

  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    },
    [],
  );

  return (
    <Button
      small
      data-dev-id="component-browser.copy-mpn"
      disabled={!mpn}
      title={tooltip}
      aria-label={copied ? copiedLabel : label}
      onClick={() => {
        if (!mpn) return;
        void writeToClipboard(mpn).then((ok) => {
          if (!ok) return;
          setCopied(true);
          if (timer.current !== null) window.clearTimeout(timer.current);
          timer.current = window.setTimeout(() => setCopied(false), COPIED_FEEDBACK_MS);
        });
      }}
      // The glyph box is FIXED. Swapping a 14px copy glyph for a 14px check inside a fixed box is
      // the whole trick: nothing reflows, so the row cannot shift under the pointer mid-click.
      icon={
        <span
          data-copied={copied ? "true" : "false"}
          className="inline-flex h-3.5 w-3.5 flex-none items-center justify-center"
        >
          {copied ? (
            <Icon id="modal.check" className="h-3.5 w-3.5 text-ok" />
          ) : (
            <DuplicateIcon className="h-3.5 w-3.5" />
          )}
        </span>
      }
    >
      {/* The LABEL never changes, for the same reason: "Copied" is two characters wider than
          "Copy MPN" in some faces and one narrower in others, and either way the row moves. */}
      <Text id="component-browser.copy-mpn">Copy MPN</Text>
    </Button>
  );
}
