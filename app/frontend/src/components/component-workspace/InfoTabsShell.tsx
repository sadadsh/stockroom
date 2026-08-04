/**
 * The four information tabs and the band they sit on.
 *
 * Exactly four questions, in the order a person asks them: what is it, what are its numbers, where
 * do we buy it, where did the answers come from. The strip is the app's one `TabStrip`, so these
 * tabs read and key-navigate identically to every other tabbed surface, and the panel below it is
 * a non-scrolling region that its content must fit inside.
 */
import type { ReactNode } from "react";
import type { ComponentInfoTab } from "../../lib/uiSession";
import { useText } from "../../lib/copy";
import { TabStrip, type TabItem } from "../primitives";

export function InfoTabsShell({
  tabs,
  active,
  onSelect,
  children,
}: {
  tabs: readonly TabItem<ComponentInfoTab>[];
  active: ComponentInfoTab;
  onSelect: (tab: ComponentInfoTab) => void;
  children: ReactNode;
}) {
  const tabsLabel = useText("component-browser.info-tabs-label", "Component information");
  return (
    <section
      data-dev-id="component-browser.info"
      className="flex min-h-0 flex-[3_1_0%] flex-col overflow-hidden px-4 pb-3"
    >
      <div className="mb-2 flex flex-none items-center">
        <TabStrip
          tabs={tabs}
          active={active}
          onSelect={onSelect}
          idBase="component-info"
          devIdBase="component-browser.info"
          density="compact"
          aria-label={tabsLabel}
        />
      </div>
      {children}
    </section>
  );
}
