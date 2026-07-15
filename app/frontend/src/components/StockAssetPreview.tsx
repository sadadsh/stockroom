/**
 * The built-in KiCad footprint + 3D model preview for a file-less passive, shown in the
 * Add-A-Part flow BEFORE the part is committed (so there is no part id — both render
 * from the stock footprint lib_id, e.g. "Resistor_SMD:R_0603_1608Metric"). The owner's
 * ask: for a passive, show the built-in footprint and 3D model; the symbol matters less.
 * The 3D reuses the same auto-rotating viewer the committed-part preview uses.
 */
import { useStockModelGlb, useStockPreviewSvg } from "../api/queries";
import { useObjectUrl } from "../lib/useObjectUrl";
import { useTheme } from "../lib/theme";
import { Glb3DView } from "./Glb3DView";

function Panel({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-xs text-t3">{label}</span>
      <div className="flex h-[160px] items-center justify-center overflow-hidden rounded-card border border-line2 bg-raise">
        {children}
      </div>
    </div>
  );
}

export function StockAssetPreview({ footprintLibId }: { footprintLibId: string }) {
  const svg = useStockPreviewSvg(footprintLibId);
  const svgUrl = useObjectUrl(svg.data);
  const { theme } = useTheme();
  const glb = useStockModelGlb(footprintLibId, true);

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      <Panel label="Footprint">
        {svg.isError ? (
          <span className="px-4 text-center text-xs text-t3">
            Footprint preview needs KiCad installed.
          </span>
        ) : svgUrl ? (
          <img
            src={svgUrl}
            alt="Footprint preview"
            draggable={false}
            className="h-[130px] w-[86%] object-contain"
            style={{ filter: theme === "dark" ? "invert(1)" : "none" }}
          />
        ) : (
          <div className="h-16 w-24 animate-pulse rounded-control bg-raise2" />
        )}
      </Panel>
      <Panel label="3D Model">
        <Glb3DView
          data={glb.data as ArrayBuffer | undefined}
          isLoading={glb.isLoading}
          isError={glb.isError}
          error={glb.error}
        />
      </Panel>
    </div>
  );
}
