import { useEffect, useRef } from "react";
import {
  designOverrideIdsFor,
  ensureDesignIdentities,
  ensureDesignOccurrenceIdentities,
} from "../lib/designIdentity";
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
  const copy = useRef(dev.draft.copy);
  const targets = useRef(new Map<Element, Map<Element, string | null>>());
  const active = dev.enabled || Object.keys(dev.draft.copy).some((id) => id.startsWith("auto.direct-copy."));
  useEffect(() => {
    if (!active) return;
    const instrument = () => {
      const roots = Array.from(document.querySelectorAll(PRODUCT_ROOTS));
      for (const root of roots) ensureDesignIdentities(root, false);
      ensureDesignOccurrenceIdentities(document);
      const resolvedDocument = designOverrideIdsFor(document, true);
      for (const root of roots) {
        const resolved = new Map(
          [...resolvedDocument].filter(([element]) => element === root || root.contains(element)),
        );
        targets.current.set(root, resolved);
        applyDirectTextOverrides(root, copy.current, resolved);
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
    observer.observe(document.body, { childList: true, subtree: true });
    return () => {
      observer.disconnect();
      if (frame) cancelAnimationFrame(frame);
      targets.current.clear();
    };
  }, [active]);
  useEffect(() => {
    copy.current = dev.draft.copy;
    for (const root of document.querySelectorAll(PRODUCT_ROOTS)) {
      applyDirectTextOverrides(root, dev.draft.copy, targets.current.get(root));
    }
  }, [dev.draft.copy]);
  return null;
}
