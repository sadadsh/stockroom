/**
 * The Bench's scope rail: the family picker, and under it the package grid - the UNION of the
 * selected families' packages, each showing its coverage, narrowed by a text filter and a kind chip
 * row. Extracted from CompatibilityWorkbench, which is the Bench's data flow; this file is the one
 * pane, and it owns the two narrowings (the text filter and the kind chip) outright because nothing
 * outside the rail reads them.
 */
import { useMemo, useState } from "react";
import { instanceDevId } from "../../lib/componentDevIds";
import { Text, useCopyFormatter, useText } from "../../lib/copy";
import { Eyebrow } from "../primitives";
import type { StmScope } from "../../pages/StmViewerPage";
import { FamilyPicker } from "./FamilyPicker";
import { PACKAGE_KINDS, packageKind, type PackageKind, type PackageOption } from "./benchModel";

export function BenchScopeRail({
  scope,
  onScopeChange,
  packageOptions,
  selectedPackage,
  onSelectPackage,
}: {
  scope: StmScope;
  onScopeChange: (scope: StmScope) => void;
  packageOptions: PackageOption[];
  selectedPackage: string | null;
  onSelectPackage: (update: (current: string | null) => string | null) => void;
}) {
  const [pkgFilter, setPkgFilter] = useState("");
  const [pkgKind, setPkgKind] = useState<PackageKind>("All");
  const packageFilterLabel = useText("stm.compat.package-filter.placeholder", "Filter Packages");
  const packageOfferedLabel = useText(
    "stm.compat.package-offered.title",
    "Present on each selected series",
  );
  const packageMissingLabel = useCopyFormatter(
    "stm.compat.package-missing.title",
    "Absent from {families}",
  );

  const selectedFamilies = scope.families;
  const visiblePackages = useMemo(() => {
    const needle = pkgFilter.trim().toUpperCase();
    return packageOptions.filter(
      (p) =>
        (pkgKind === "All" || packageKind(p.name) === pkgKind) &&
        (!needle || p.name.toUpperCase().includes(needle)),
    );
  }, [packageOptions, pkgFilter, pkgKind]);

  return (
    <div className="flex w-[220px] flex-none flex-col gap-2 overflow-hidden px-2 py-1">
      <div
        className={`min-h-0 ${
          selectedFamilies.length ? "order-2 flex-1" : "order-1 flex-1"
        }`}
      >
        <FamilyPicker scope={scope} onScopeChange={onScopeChange} />
      </div>

      <div
        className={`flex min-h-0 flex-col border-line ${
          selectedFamilies.length
            ? "order-1 max-h-[44%] min-h-40 border-b pb-2"
            : "order-2 flex-none border-t pt-2"
        }`}
      >
        <Eyebrow className="mb-1.5 px-1">
          <Text id="stm.compat.package-title">Package</Text>
        </Eyebrow>
        {selectedFamilies.length === 0 ? (
          <p className="px-1 text-xs text-t3">
            <Text id="stm.compat.package-prompt">Select one or more series to see packages.</Text>
          </p>
        ) : (
          <div className="flex min-h-0 flex-1 flex-col gap-1.5">
            <input
              value={pkgFilter}
              onChange={(e) => setPkgFilter(e.target.value)}
              placeholder={packageFilterLabel}
              aria-label={packageFilterLabel}
              className="w-full rounded-control bg-field px-2 py-1 text-xs text-t1 outline-none placeholder:text-t3"
            />
            <div className="flex flex-wrap gap-0.5">
              {PACKAGE_KINDS.map((kind) => (
                <button
                  key={kind}
                  type="button"
                  aria-pressed={pkgKind === kind}
                  onClick={() => setPkgKind(kind)}
                  className={
                    "rounded-control px-1.5 py-0.5 text-2xs " +
                    (pkgKind === kind ? "bg-acc-soft text-t1" : "text-t3 hover:text-t1")
                  }
                >
                  {kind}
                </button>
              ))}
            </div>
            {visiblePackages.length === 0 ? (
              <p className="px-1 text-xs text-t3">
                <Text id="stm.compat.package-empty">No packages match this filter.</Text>
              </p>
            ) : (
              <div
                className="grid min-h-0 grid-cols-2 gap-1 overflow-y-auto pr-0.5"
                data-testid="bench-packages"
              >
                {visiblePackages.map((p) => {
                  const active = selectedPackage === p.name;
                  const partial = p.missing.length > 0;
                  return (
                    <button
                      key={p.name}
                      type="button"
                      data-dev-id={instanceDevId("stm.package", p.name)}
                      data-dev-role="stm.package"
                      aria-pressed={active}
                      title={
                        partial
                          ? packageMissingLabel({ families: p.missing.join(", ") })
                          : packageOfferedLabel
                      }
                      onClick={() =>
                        onSelectPackage((cur) => (cur === p.name ? null : p.name))
                      }
                      className={
                        "flex items-center justify-between gap-1 rounded-control border px-1.5 py-1 " +
                        (active
                          ? "border-acc bg-acc-soft text-t1"
                          : "border-line2 text-t2 hover:text-t1")
                      }
                    >
                      <span className="truncate font-mono text-xs">{p.name}</span>
                      {partial ? (
                        <span className="tnum flex-none font-mono text-2xs text-t3">
                          {p.covered.length}/{selectedFamilies.length}
                        </span>
                      ) : null}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
