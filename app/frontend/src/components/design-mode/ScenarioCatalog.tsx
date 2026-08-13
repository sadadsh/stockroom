import { useMemo, useState } from "react";
import { useDesignStudio } from "../../design-studio/DesignStudioProvider";
import { bootstrapScenarioRegistry } from "../../design-studio/scenarios";
import { useText } from "../../lib/copy";

export function ScenarioCatalog() {
  const studio = useDesignStudio();
  const [query, setQuery] = useState("");
  const [activating, setActivating] = useState("");
  const screensLabel = useText("design-studio.screens.title", "Screens And States");
  const searchLabel = useText("design-studio.screens.search", "Search Screens And States");
  const scenarios = useMemo(
    () => bootstrapScenarioRegistry.searchScenarios(query),
    [query],
  );
  const groups = useMemo(() => {
    const values = new Map<string, typeof scenarios>();
    for (const scenario of scenarios) {
      const key = `${scenario.area} · ${scenario.group}`;
      values.set(key, [...(values.get(key) ?? []), scenario]);
    }
    return [...values.entries()];
  }, [scenarios]);

  async function activate(id: string) {
    setActivating(id);
    try {
      await studio.activateScenario(id);
    } finally {
      setActivating("");
    }
  }

  return (
    <section aria-labelledby="studio-screens-heading" className="min-h-0 overflow-y-auto">
      <h2 id="studio-screens-heading" className="sr-only">{screensLabel}</h2>
      <div className="p-2">
        <input
          type="search"
          aria-label={searchLabel}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={searchLabel}
          className="mb-2 h-8 w-full rounded-control bg-field px-2 text-xs text-t1 outline-none focus:ring-1 focus:ring-acc"
        />
        <div className="space-y-1">
          {groups.map(([group, items]) => {
            const containsActive = items.some((scenario) => scenario.id === (studio.activeScenario?.id ?? "global.real-data"));
            return <details key={`${group}:${query.trim() ? "search" : "browse"}`} open={containsActive || query.trim().length > 0 ? true : undefined} className="group rounded-control bg-field/40" data-active-group={containsActive || undefined}>
              <summary className="cursor-pointer list-none rounded-control px-2 py-1.5 text-xs font-semibold text-t2 hover:bg-raise2 hover:text-t1">
                {items[0]?.group ?? group}<span className="ml-2 text-2xs font-normal text-t3">{items.length}</span>
              </summary>
              <div className="space-y-0.5 px-1 pb-1">
          {items.map((scenario) => {
            const active = scenario.id === "global.real-data"
              ? studio.activeScenario === null
              : studio.activeScenario?.id === scenario.id;
            return (
              <button
                key={scenario.id}
                type="button"
                data-scenario-catalog-id={scenario.id}
                aria-pressed={active}
                disabled={activating !== ""}
                onClick={() => void activate(scenario.id)}
                className={
                  "flex w-full items-center rounded-control px-2 py-1.5 text-left text-xs transition-colors disabled:text-t5 " +
                  (active ? "bg-acc-soft font-semibold text-t1" : "text-t2 hover:bg-raise2 hover:text-t1")
                }
              >
                <span className="truncate">{scenario.title}</span>
              </button>
            );
          })}
              </div>
            </details>;
          })}
        </div>
      </div>
    </section>
  );
}
