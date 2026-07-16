/**
 * Library Health: the two library-keeping tools (Doctor and Duplicates) folded
 * under one Library tab so the flagship's strip reads as three concerns (the
 * Parts entity view, BOM Coverage, and health) instead of a flat row that mixes
 * them. An internal segmented control switches the two, each still its own route
 * so the Ctrl+K palette keeps deep-linking straight to either one.
 */
import { DoctorPage } from "./DoctorPage";
import { DuplicatesPage } from "./DuplicatesPage";
import { useRouter } from "../lib/router";
import { SegmentedControl, type SegmentItem } from "../components/primitives";

export type HealthRoute = "doctor" | "duplicates";

const SEGMENTS: readonly SegmentItem<HealthRoute>[] = [
  { id: "doctor", label: "Doctor" },
  { id: "duplicates", label: "Duplicates" },
];

export function LibraryHealthPage({ active }: { active: HealthRoute }) {
  const { navigate } = useRouter();
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-none items-center px-[18px] pb-1.5 pt-2">
        <SegmentedControl
          options={SEGMENTS}
          value={active}
          onChange={navigate}
          size="small"
          aria-label="Library health sections"
        />
      </div>
      <div className="flex min-h-0 flex-1 flex-col">
        {active === "doctor" ? <DoctorPage /> : <DuplicatesPage />}
      </div>
    </div>
  );
}
