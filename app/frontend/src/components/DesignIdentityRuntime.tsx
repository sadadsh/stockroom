import { useEffect } from "react";
import { ensureDesignIdentities } from "../lib/designIdentity";

const PRODUCT_ROOT_IDS = ["shell.root", "onboarding.gate"] as const;
const PRODUCT_ROOTS = [
  ...PRODUCT_ROOT_IDS.map((id) => `[data-dev-id="${id}"]`),
  "[data-design-product-root]",
].join(", ");

/** Keeps dynamic, cloned, and imperative Stockroom DOM addressable after the JSX build transform. */
export function DesignIdentityRuntime() {
  useEffect(() => {
    const instrument = () => {
      for (const root of document.querySelectorAll(PRODUCT_ROOTS)) ensureDesignIdentities(root);
    };
    instrument();
    const observer = new MutationObserver(instrument);
    observer.observe(document.body, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, []);
  return null;
}
