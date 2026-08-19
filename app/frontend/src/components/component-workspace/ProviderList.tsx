import { Text, useText } from "../../lib/copy";
import { Icon } from "../Icon";
import type { ManageModelsProvider } from "./manageModelsModel";

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
  const providerListLabel = useText(
    "component-browser.manage-models-providers-aria",
    "CAD model providers",
  );

  return (
    <div
      data-dev-id="component-browser.provider-list"
      className="flex flex-none items-center gap-2 border-b border-line bg-band px-2 py-1.5"
    >
      <span className="ui-section-title flex-none">
        <Text id="component-browser.manage-models-providers">Providers</Text>
      </span>
      <div
        role="radiogroup"
        aria-label={providerListLabel}
        className="flex min-w-0 flex-1 items-stretch gap-1 overflow-x-auto"
      >
        {providers.map((provider) => (
          <button
            key={provider.row.id}
            type="button"
            role="radio"
            data-dev-role="component-browser.provider-row"
            aria-checked={provider.row.id === selectedId}
            disabled={disabled || !provider.reachable}
            tabIndex={
              provider.row.id === selectedId
                || (!selectedId && provider.row.id === providers.find((item) => item.reachable)?.row.id)
                ? 0
                : -1
            }
            className={
              "flex h-8 flex-none items-center gap-1.5 rounded-control border px-3 text-left " +
              (provider.row.id === selectedId
                ? "border-acc bg-control-pressed"
                : "border-transparent hover:bg-control-hover")
            }
            onClick={() => onSelect(provider.row.id)}
            onKeyDown={(event) => {
              if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) {
                return;
              }
              const enabledProviders = providers.filter((item) => item.reachable);
              if (enabledProviders.length === 0) return;
              event.preventDefault();
              const currentIndex = Math.max(
                0,
                enabledProviders.findIndex((item) => item.row.id === provider.row.id),
              );
              const targetIndex = event.key === "Home"
                ? 0
                : event.key === "End"
                  ? enabledProviders.length - 1
                  : (currentIndex + (event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 1) + enabledProviders.length)
                    % enabledProviders.length;
              onSelect(enabledProviders[targetIndex].row.id);
              const buttons = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>(
                'button[role="radio"]:not(:disabled)',
              );
              buttons?.[targetIndex]?.focus();
            }}
          >
            <Icon id="detail.provider" className="h-3.5 w-3.5 flex-none text-t3" />
            <span className="whitespace-nowrap text-xs font-medium text-t1">{provider.row.label}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
