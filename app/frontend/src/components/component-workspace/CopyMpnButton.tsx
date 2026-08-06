/**
 * The clipboard control for the manufacturer part number.
 *
 * The one rule this control exists to keep: the string that lands on the clipboard is the CANONICAL
 * manufacturer part number, byte for byte. No trimming, no upper-casing, no appended package, no
 * "MPN " prefix. A part number is looked up in a distributor's search box, and a search box does
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

async function writeToClipboard(text: string): Promise<boolean> {
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
  // The COMPLETE action name, on an icon-plus-object control: this is what the tooltip shows and
  // what a screen reader reads, so shortening the visible text costs nothing.
  const label = useText(
    "component-browser.copy-mpn",
    "Place The Manufacturer Part Number On The Clipboard",
  );
  const copiedLabel = useText("component-browser.copy-mpn-copied", "Placed On The Clipboard");

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
      title={label}
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
      {/* THE GLYPH CARRIES THE VERB; THE TEXT CARRIES ONLY THE OBJECT. A copy glyph is one of the
          handful that is genuinely universal, so the visible text is the OBJECT alone - `MPN` - and
          the verb lives in the tooltip and the accessible name, which is where a keyboard and a
          screen reader read it. The visible text still never changes width, for the reason above:
          "Copied" is wider than "MPN" in some faces and the row would move under the pointer. */}
      <Text id="component-browser.copy-mpn-object">MPN</Text>
    </Button>
  );
}
