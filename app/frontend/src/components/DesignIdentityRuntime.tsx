import { useEffect } from "react";
import { ensureDesignIdentities } from "../lib/designIdentity";
import { useDevMode } from "../lib/devMode";
import { applyDirectTextOverrides } from "../design-studio/targetDomains";

const PRODUCT_ROOT_IDS = ["shell.root", "onboarding.gate"] as const;
const PRODUCT_ROOTS = [
  ...PRODUCT_ROOT_IDS.map((id) => `[data-dev-id="${id}"]`),
  "[data-design-product-root]",
].join(", ");

/** Keeps dynamic, cloned, and imperative Stockroom DOM addressable after the JSX build transform. */
export function DesignIdentityRuntime() {
  const dev = useDevMode();
  useEffect(() => {
    const instrument = () => {
      for (const root of document.querySelectorAll(PRODUCT_ROOTS)) {
        ensureDesignIdentities(root);
        applyDirectTextOverrides(root, dev.draft.copy);
      }
    };
    instrument();
    let frame = 0;
    const observer = new MutationObserver(() => {
      if (!frame) frame = requestAnimationFrame(() => {
        frame = 0;
        instrument();
      });
    });
    observer.observe(document.body, { childList: true, characterData: true, subtree: true });
    return () => {
      observer.disconnect();
      if (frame) cancelAnimationFrame(frame);
    };
  }, [dev.draft.copy]);
  return null;
}
