/**
 * The Library flagship: one header and three grouped tabs (Parts, BOM Coverage,
 * Library Health) so the strip reads as three concerns, not a flat row that
 * mixed an entity view with an action flow and two health tools. Each tab maps
 * to a real route so the rail, the Ctrl+K palette, and the window-wide drop keep
 * deep-linking; Library Health fans the doctor and duplicates routes behind one
 * tab (its own segmented control), and Add Parts is no longer a tab at all (it
 * is the full-screen wizard reached from the Parts toolbar).
 */
import { BomPage } from "./BomPage";
import { ComponentsPage } from "./ComponentsPage";
import { LibraryHealthPage } from "./LibraryHealthPage";
import { useRouter } from "../lib/router";
import { TabPanel, TabStrip, type TabItem } from "../components/primitives";

// The routes the Library flagship owns as tabs.
export type LibraryRoute = "components" | "bom" | "duplicates" | "doctor";

// The visible tab ids. Library Health stands in for both health routes.
type LibraryTab = "components" | "bom" | "health";

const TABS: readonly TabItem<LibraryTab>[] = [
  { id: "components", label: "Parts" },
  { id: "bom", label: "BOM Coverage" },
  { id: "health", label: "Component Health" },
];

// Clicking Library Health lands on the health route already open, else Doctor.
const DEFAULT_HEALTH: LibraryRoute = "doctor";

function tabForRoute(route: LibraryRoute): LibraryTab {
  return route === "duplicates" || route === "doctor" ? "health" : route;
}

export function LibraryPage({ route }: { route: LibraryRoute }) {
  const { navigate } = useRouter();
  const activeTab = tabForRoute(route);

  function onSelect(tab: LibraryTab) {
    if (tab === "health") {
      navigate(activeTab === "health" ? route : DEFAULT_HEALTH);
    } else {
      navigate(tab);
    }
  }

  return (
    <>
      <div className="flex h-14 flex-none items-center gap-5 px-[18px]">
        <div className="text-lg font-semibold text-t1">Components</div>
        <TabStrip
          tabs={TABS}
          active={activeTab}
          onSelect={onSelect}
          idBase="library"
          aria-label="Component sections"
        />
      </div>
      <TabPanel idBase="library" tab={activeTab} className="flex min-h-0 flex-1 flex-col">
        {route === "components" ? (
          <ComponentsPage />
        ) : route === "bom" ? (
          <BomPage />
        ) : (
          <LibraryHealthPage active={route} />
        )}
      </TabPanel>
    </>
  );
}
