/**
 * The Components flagship: a header over the parts view. BOM Coverage moved to the
 * project's own BOM (D1), Duplicates became a Parts filter (D2), and Doctor moved to
 * Settings (D3), so Parts is the only surface here - there is no tab strip anymore.
 */
import { ComponentsPage } from "./ComponentsPage";

export function LibraryPage() {
  return (
    <>
      <div className="flex h-14 flex-none items-center px-[18px]">
        <div className="text-lg font-semibold text-t1">Components</div>
      </div>
      <ComponentsPage />
    </>
  );
}
