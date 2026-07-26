/**
 * The Components flagship. BOM Coverage moved to the project's own BOM (D1),
 * Duplicates became a Parts filter (D2), and Doctor moved to Settings (D3), so Parts
 * is the only surface here. ComponentsPage owns its own header (title + live stats),
 * so this is now a thin route entry.
 */
import { ComponentsPage } from "./ComponentsPage";

export function LibraryPage() {
  return <ComponentsPage />;
}
