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
  const fixtureLabel = useText("design-studio.scenario.fixture", "Fixture");
  const scenarios = useMemo(
    () => bootstrapScenarioRegistry.searchScenarios(query),
    [query],
  );

  async function activate(id: string) {
    setActivating(id);
    try {
      await studio.activateScenario(id);
    } finally {
      setActivating("");
    }
  }

  return (
    <section aria-labelledby="studio-screens-heading">
      <header className="bg-band px-2.5 py-1.5">
        <h2 id="studio-screens-heading" className="text-xs font-semibold text-t1">{screensLabel}</h2>
      </header>
      <div className="p-2">
        <input
          type="search"
          aria-label={searchLabel}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={searchLabel}
          className="mb-2 h-[26px] w-full rounded-control border border-line bg-field px-2 text-xs text-t1 outline-none focus:border-acc"
        />
        <div className="space-y-0.5">
          {scenarios.map((scenario) => {
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
                  "flex w-full items-center rounded-control px-2 py-1 text-left text-xs transition-colors disabled:text-t5 " +
                  (active ? "bg-acc-soft font-semibold text-t1" : "text-t2 hover:bg-raise2 hover:text-t1")
                }
              >
                <span className="truncate">{scenario.title}</span>
                {scenario.fixtures.length > 0 ? <span className="ml-auto text-2xs text-t3">{fixtureLabel}</span> : null}
              </button>
            );
          })}
        </div>
      </div>
    </section>
  );
}
