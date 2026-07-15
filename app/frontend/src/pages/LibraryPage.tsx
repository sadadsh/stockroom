/**
 * The Library flagship: one header, four tabs (Parts, Add Parts, Duplicates,
 * Doctor). Each tab is a real route, so the rail, the Ctrl+K palette, and the
 * window-wide drop (which lands on Add Parts) all deep-link into the right tab;
 * the shell only owns the header and the tab strip, the bodies stay whole pages.
 */
import { ComponentsPage } from "./ComponentsPage";
import { DoctorPage } from "./DoctorPage";
import { DuplicatesPage } from "./DuplicatesPage";
import { IngestPage } from "./IngestPage";
import { useRouter } from "../lib/router";

export type LibraryTab = "components" | "ingest" | "duplicates" | "doctor";

const TABS: { route: LibraryTab; label: string }[] = [
  { route: "components", label: "Parts" },
  { route: "ingest", label: "Add Parts" },
  { route: "duplicates", label: "Duplicates" },
  { route: "doctor", label: "Doctor" },
];

export function LibraryPage({ tab }: { tab: LibraryTab }) {
  const { navigate } = useRouter();
  return (
    <>
      <div className="flex h-14 flex-none items-center gap-5 px-[18px]">
        <div className="text-lg font-semibold text-t1">Library</div>
        <div role="tablist" className="inline-flex rounded-card border border-line2 p-0.5">
          {TABS.map((t) => (
            <button
              key={t.route}
              type="button"
              role="tab"
              aria-selected={tab === t.route}
              onClick={() => navigate(t.route)}
              className={
                "rounded-control px-3 py-1 text-sm transition-colors " +
                (tab === t.route ? "bg-raise2 text-t1" : "text-t3 hover:text-t2")
              }
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>
      {tab === "components" ? (
        <ComponentsPage />
      ) : tab === "ingest" ? (
        <IngestPage />
      ) : tab === "duplicates" ? (
        <DuplicatesPage />
      ) : (
        <DoctorPage />
      )}
    </>
  );
}
