import { Text } from "../../lib/copy";
import type { ManageModelsProvider } from "./manageModelsModel";

const ARTIFACT_LABELS = {
  symbol: "Symbol",
  footprint: "Footprint",
  model: "3D Model",
} as const;

export function ProviderList({
  providers,
  selectedId,
  disabled = false,
  onSelect,
}: {
  providers: readonly ManageModelsProvider[];
  selectedId: string | null;
  disabled?: boolean;
  onSelect: (providerId: string) => void;
}) {
  return (
    <aside className="flex min-h-0 w-[280px] flex-none flex-col border-r border-line bg-band">
      <div className="border-b border-line px-3 py-2">
        <div className="ui-section-title">
          <Text id="component-browser.manage-models-providers">Providers</Text>
        </div>
        <p className="mt-0.5 text-xs text-t3">
          <Text id="component-browser.manage-models-provider-help">
            Complete sets include Symbol, Footprint, and 3D Model.
          </Text>
        </p>
      </div>
      <div
        role="radiogroup"
        aria-label="CAD model providers"
        className="min-h-0 flex-1 space-y-1 overflow-y-auto p-2"
      >
        {providers.map((provider) => (
          <button
            key={provider.row.id}
            type="button"
            role="radio"
            aria-checked={provider.row.id === selectedId}
            disabled={disabled}
            className={
              "w-full rounded-control border px-2.5 py-2 text-left " +
              (provider.row.id === selectedId
                ? "border-accent bg-control-pressed"
                : "border-transparent hover:bg-control-hover")
            }
            onClick={() => onSelect(provider.row.id)}
          >
            <span className="flex items-center justify-between gap-2">
              <span className="truncate text-sm font-medium text-t1">{provider.row.label}</span>
              {provider.complete ? (
                <span className="rounded-full bg-positive/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-positive">
                  <Text id="component-browser.manage-models-complete">Complete Set</Text>
                </span>
              ) : null}
            </span>
            <span className="mt-1 block text-xs text-t3">
              {provider.complete ? (
                <Text id="component-browser.manage-models-all-three">All three models</Text>
              ) : (
                <>
                  <Text id="component-browser.manage-models-missing">Missing</Text>{" "}
                  {provider.missing.map((artifact) => ARTIFACT_LABELS[artifact]).join(", ")}
                </>
              )}
            </span>
          </button>
        ))}
      </div>
    </aside>
  );
}
