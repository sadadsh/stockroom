/**
 * The Library flagship: one header and two tabs (Parts, BOM Coverage). Each tab
 * maps to a real route so the rail and the window-wide drop keep working; Add Parts
 * is not a tab (it is the full-screen wizard reached from the Parts toolbar),
 * Duplicates is a filter inside Parts, and Doctor moved to Settings.
 */
import { BomPage } from "./BomPage";
import { ComponentsPage } from "./ComponentsPage";
import { useRouter } from "../lib/router";
import { TabPanel, TabStrip, type TabItem } from "../components/primitives";

// The routes the Library flagship owns as tabs (each tab id IS its route).
export type LibraryRoute = "components" | "bom";

const TABS: readonly TabItem<LibraryRoute>[] = [
  { id: "components", label: "Parts" },
  { id: "bom", label: "BOM Coverage" },
];

export function LibraryPage({ route }: { route: LibraryRoute }) {
  const { navigate } = useRouter();

  return (
    <>
      <div className="flex h-14 flex-none items-center gap-5 px-[18px]">
        <div className="text-lg font-semibold text-t1">Components</div>
        <TabStrip
          tabs={TABS}
          active={route}
          onSelect={navigate}
          idBase="library"
          aria-label="Component sections"
        />
      </div>
      <TabPanel idBase="library" tab={route} className="flex min-h-0 flex-1 flex-col">
        {route === "components" ? <ComponentsPage /> : <BomPage />}
      </TabPanel>
    </>
  );
}
