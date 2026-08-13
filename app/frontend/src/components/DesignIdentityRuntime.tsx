import { useEffect } from "react";
import { ensureDesignIdentities } from "../lib/designIdentity";

const PRODUCT_ROOTS = '[data-dev-id="shell.root"], [data-dev-id="onboarding.gate"], [data-design-product-root]';

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
