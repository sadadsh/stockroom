/**
 * The Library flagship: one header, five tabs (Parts, Add Parts, BOM Coverage,
 * Duplicates, Doctor). Each tab is a real route, so the rail, the Ctrl+K palette,
 * and the window-wide drop (which lands on Add Parts) all deep-link into the right
 * tab; the shell only owns the header and the tab strip, the bodies stay whole pages.
 */
import { BomPage } from "./BomPage";
import { ComponentsPage } from "./ComponentsPage";
import { DoctorPage } from "./DoctorPage";
import { DuplicatesPage } from "./DuplicatesPage";
import { IngestPage } from "./IngestPage";
import { useRouter } from "../lib/router";
import { TabPanel, TabStrip, type TabItem } from "../components/primitives";

export type LibraryTab = "components" | "ingest" | "bom" | "duplicates" | "doctor";

const TABS: readonly TabItem<LibraryTab>[] = [
  { id: "components", label: "Parts" },
  { id: "ingest", label: "Add Parts" },
  { id: "bom", label: "BOM Coverage" },
  { id: "duplicates", label: "Duplicates" },
  { id: "doctor", label: "Doctor" },
];

export function LibraryPage({ tab }: { tab: LibraryTab }) {
  const { navigate } = useRouter();
  return (
    <>
      <div className="flex h-14 flex-none items-center gap-5 px-[18px]">
        <div className="text-lg font-semibold text-t1">Library</div>
        <TabStrip
          tabs={TABS}
          active={tab}
          onSelect={navigate}
          idBase="library"
          aria-label="Library sections"
        />
      </div>
      <TabPanel idBase="library" tab={tab} className="flex min-h-0 flex-1 flex-col">
        {tab === "components" ? (
          <ComponentsPage />
        ) : tab === "ingest" ? (
          <IngestPage />
        ) : tab === "bom" ? (
          <BomPage />
        ) : tab === "duplicates" ? (
          <DuplicatesPage />
        ) : (
          <DoctorPage />
        )}
      </TabPanel>
    </>
  );
}
