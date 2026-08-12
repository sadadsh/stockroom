import type { ComponentDossier } from "../../api/dossierTypes";
import { Text, useText } from "../../lib/copy";
import type { CadWorkspaceView } from "../../lib/uiSession";

export function CadWorkspaceTabs({
  view,
  onView,
}: {
  view: CadWorkspaceView;
  onView: (view: CadWorkspaceView) => void;
}) {
  const label = useText("component-browser.cad-model-tabs", "CAD Models");
  return (
    <div role="tablist" aria-label={label} className="flex items-center gap-1">
      {(["models", "manage-models"] as const).map((id) => {
        const selected = view === id;
        return (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={selected}
            data-dev-id={`component-browser.cad-tab-${id}`}
            className={
              "ui-control-label rounded-control px-2 py-0.5 " +
              (selected ? "bg-control-pressed text-t1" : "text-t2 hover:bg-control-hover")
            }
            onClick={() => onView(id)}
          >
            {id === "models" ? (
              <Text id="component-browser.cad-tab-models">Models</Text>
            ) : (
              <Text id="component-browser.cad-tab-manage">Manage Models</Text>
            )}
          </button>
        );
      })}
    </div>
  );
}

export function ManageModelsWorkspace({
  componentId,
  dossier: _dossier,
  onView,
}: {
  componentId: string;
  dossier: ComponentDossier;
  onView: (view: CadWorkspaceView) => void;
}) {
  return (
    <section
      data-testid="manage-models-workspace"
      data-dev-id="component-browser.manage-models"
      data-component-id={componentId}
      className="flex min-h-0 flex-1 flex-col bg-surface"
    >
      <header className="flex h-[32px] flex-none items-center gap-3 border-b border-line bg-band px-3">
        <h2 className="ui-section-title">
          <Text id="component-browser.manage-models-title">CAD Models</Text>
        </h2>
        <CadWorkspaceTabs view="manage-models" onView={onView} />
      </header>
      <div className="flex min-h-0 flex-1 items-center justify-center text-sm text-t3">
        <Text id="component-browser.manage-models-loading">Checking providers</Text>
      </div>
    </section>
  );
}
